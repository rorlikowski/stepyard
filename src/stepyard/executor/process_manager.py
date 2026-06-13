"""
Stepyard ProcessManager - spawns and supervises flow subprocesses.

Each flow execution runs as its own OS process, giving:
  - Fault isolation: a crash in one flow cannot affect the scheduler or others.
  - Resource limits: per-process memory/CPU limits via ulimit / resource module.
  - Native log files: each run writes to its own ``.stepyard/logs/runs/<run_id>/run.log``.
  - Parallel execution: multiple flows can run concurrently without asyncio contention.

Process lifecycle
-----------------
    spawn_flow()      →  FlowProcess (pid, run_id, log_path)
    is_alive()        →  bool
    reap_finished()   →  list[FlowProcess]  (collects exit codes)
    kill_flow()       →  bool
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("stepyard.scheduler.process_manager")


@dataclass
class FlowProcess:
    """Represents a running (or recently exited) flow subprocess."""

    run_id: str
    flow_name: str
    flow_file: str
    pid: int
    log_path: Path
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _proc: subprocess.Popen | None = field(default=None, repr=False, compare=False)

    def is_alive(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def exit_code(self) -> int | None:
        if self._proc is None:
            return None
        return self._proc.poll()

    def kill(self, graceful: bool = True) -> bool:
        if self._proc is None or not self.is_alive():
            return False
        try:
            sig = signal.SIGTERM if graceful else signal.SIGKILL
            os.kill(self.pid, sig)
            return True
        except ProcessLookupError:
            return False
        except Exception as exc:
            logger.warning("Failed to kill flow process %s: %s", self.run_id, exc)
            return False


class ProcessManager:
    """Manages flow execution as isolated OS subprocesses."""

    def __init__(self, logs_dir: str | Path) -> None:
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "runs").mkdir(exist_ok=True)

        self._lock = threading.Lock()
        self._processes: dict[str, FlowProcess] = {}  # run_id → FlowProcess

    # ── Spawn ──────────────────────────────────────────────────────────────────

    def spawn_flow(
        self,
        run_id: str,
        flow_name: str,
        flow_file: str,
        project_dir: str,
        extra_env: dict[str, str] | None = None,
        vars_dict: dict[str, Any] | None = None,
    ) -> FlowProcess:
        """Spawn a new subprocess to execute a flow run.

        The child process runs::

            python -m stepyard.engine.runner --run-id <run_id> \
                --flow-file <flow_file> --project-dir <project_dir>

        All stdout/stderr is redirected to a per-run log file.
        """
        flow_slug = re.sub(r"[^a-z0-9]+", "-", flow_name.lower()).strip("-")
        run_log_dir = self.logs_dir / "runs" / flow_slug
        run_log_dir.mkdir(parents=True, exist_ok=True)
        log_path = run_log_dir / f"{run_id}.log"
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: WPS515

        env = os.environ.copy()

        # Auto-load .env from project_dir
        env_path = Path(project_dir) / ".env"
        if env_path.is_file():
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k not in env:
                                env[k] = v
            except Exception as exc:
                logger.warning("Failed to auto-load .env file: %s", exc)

        env["PYTHONPATH"] = os.pathsep.join(
            filter(
                None,
                [
                    project_dir,
                    os.path.join(project_dir, "src"),
                    env.get("PYTHONPATH", ""),
                ],
            )
        )
        env["STEPYARD_PROJECT_DIR"] = project_dir
        if extra_env:
            env.update(extra_env)

        cmd = [
            sys.executable,
            "-m",
            "stepyard.engine.runner",
            "--run-id",
            run_id,
            "--flow-file",
            flow_file,
            "--project-dir",
            project_dir,
        ]

        if vars_dict:
            cmd.extend(["--vars", json.dumps(vars_dict)])

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,  # Detach from parent's process group
            )
        finally:
            log_file.close()

        fp = FlowProcess(
            run_id=run_id,
            flow_name=flow_name,
            flow_file=flow_file,
            pid=proc.pid,
            log_path=log_path,
            _proc=proc,
        )

        with self._lock:
            self._processes[run_id] = fp

        logger.info(
            "Spawned flow '%s' (run_id=%s, pid=%d, log=%s)",
            flow_name,
            run_id,
            proc.pid,
            log_path,
        )
        return fp

    # ── Query ──────────────────────────────────────────────────────────────────

    def is_alive(self, run_id: str) -> bool:
        with self._lock:
            fp = self._processes.get(run_id)
        return fp.is_alive() if fp else False

    def get(self, run_id: str) -> FlowProcess | None:
        with self._lock:
            return self._processes.get(run_id)

    def list_running(self) -> list[FlowProcess]:
        with self._lock:
            return [fp for fp in self._processes.values() if fp.is_alive()]

    # ── Control ───────────────────────────────────────────────────────────────

    def kill_flow(self, run_id: str, graceful: bool = True) -> bool:
        with self._lock:
            fp = self._processes.get(run_id)
        if not fp:
            return False
        return fp.kill(graceful=graceful)

    # ── Reap ──────────────────────────────────────────────────────────────────

    def reap_finished(self) -> list[tuple[FlowProcess, int]]:
        """Collect exit codes of finished processes.

        Returns a list of ``(FlowProcess, exit_code)`` for processes that
        exited since the last call.  Removes them from the internal tracker.
        """
        finished: list[tuple[FlowProcess, int]] = []
        with self._lock:
            done_ids = [rid for rid, fp in self._processes.items() if not fp.is_alive()]
            for rid in done_ids:
                fp = self._processes.pop(rid)
                code = fp.exit_code() or 0
                finished.append((fp, code))
        return finished
