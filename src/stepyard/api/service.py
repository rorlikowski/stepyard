"""
Stepyard Service Facade.

Single high-level API used by the CLI and any future integrations.
The CLI should never import directly from ``core/``, ``engine/``, or
``scheduler/`` - all operations go through this class.

Usage::

    svc = StepyardService.from_cwd()          # auto-detect project root
    svc = StepyardService("/path/to/project") # explicit path

    logs = svc.get_log_lines(run_id)
    svc.start_scheduler(foreground=False)
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stepyard.core.flow import Flow, FlowResolver
from stepyard.logging_.log_store import LogStore
from stepyard.storage.facade import Storage

# ─── Result types ─────────────────────────────────────────────────────────────


@dataclass
class SchedulerStatus:
    is_running: bool
    pid: int | None = None


@dataclass
class FlowInfo:
    name: str
    file_path: str
    is_active: bool
    has_trigger: bool
    trigger_type: str | None = None
    trigger_schedule: str | None = None


# ─── Service ──────────────────────────────────────────────────────────────────


class StepyardService:
    """High-level facade - the ONLY entry point for CLI commands."""

    def __init__(self, project_dir: str) -> None:
        self.project_dir = os.path.abspath(project_dir)
        self.storage = Storage(self.project_dir)
        self._stepyard_dir = os.path.join(self.project_dir, ".stepyard")

        # Transparent Background Initialization
        os.makedirs(self._stepyard_dir, exist_ok=True)

        self._log_store = LogStore(self._stepyard_dir)
        self._resolver = FlowResolver(self.project_dir)

        os.makedirs(self._resolver.flows_dir, exist_ok=True)

    @classmethod
    def from_cwd(cls) -> StepyardService:
        """Auto-detect the project root by walking up from cwd."""
        curr = os.getcwd()
        while True:
            if os.path.isdir(os.path.join(curr, ".stepyard")):
                return cls(curr)
            parent = os.path.dirname(curr)
            if parent == curr:
                break
            curr = parent
        return cls(os.getcwd())

    # ── Flow execution ────────────────────────────────────────────────────────

    def run_flow(
        self,
        flow_name: str,
        vars: dict[str, Any] | None = None,
        trigger_type: str = "manual",
    ) -> str:
        """Queue a flow for execution. Returns the new run_id."""
        flow_file = self.find_flow_file(flow_name)
        if not flow_file:
            from stepyard.core.errors import FlowNotFoundError

            raise FlowNotFoundError(flow_name)

        import datetime

        run_id = f"run-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.storage.create_run(run_id, flow_name, trigger_type=trigger_type)
        return run_id

    def find_flow_file(self, flow_name: str) -> str | None:
        """Resolve flow name to YAML file path."""
        return self._resolver.find(flow_name)

    def list_flows(self) -> list[FlowInfo]:
        """List all available flows from the flows directory."""
        flows_dir = self._resolver.flows_dir
        if not os.path.isdir(flows_dir):
            return []

        result: list[FlowInfo] = []
        for fn in sorted(os.listdir(flows_dir)):
            if not fn.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(flows_dir, fn)
            name = fn.rsplit(".", 1)[0]
            try:
                flow = Flow.from_file(filepath)
                trigger = flow.model.trigger
                result.append(
                    FlowInfo(
                        name=flow.model.name,
                        file_path=filepath,
                        is_active=self.storage.is_flow_active(flow.model.name),
                        has_trigger=trigger is not None,
                        trigger_type=trigger.uses if trigger else None,
                        trigger_schedule=trigger.with_config.get("schedule") if trigger else None,
                    )
                )
            except Exception:
                result.append(
                    FlowInfo(
                        name=name,
                        file_path=filepath,
                        is_active=False,
                        has_trigger=False,
                    )
                )
        return result

    # ── Run inspection ────────────────────────────────────────────────────────

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self.storage.get_run(run_id)

    def get_step_runs(self, run_id: str) -> list[dict[str, Any]]:
        return self.storage.get_step_runs(run_id)

    def cancel_run(self, run_id: str) -> bool:
        """Attempt to cancel a running flow (state-driven cancellation)."""
        self.storage.update_run_status(run_id, "cancelled")
        return True

    # ── Logs ──────────────────────────────────────────────────────────────────

    def get_log_lines(self, run_id: str, last_n: int | None = None) -> list[str]:
        return self._log_store.tail(run_id, last_n)

    def follow_logs(self, run_id: str) -> Iterator[str]:
        return self._log_store.follow(run_id)

    def get_scheduler_logs(self, last_n: int | None = None) -> list[str]:
        return self._log_store.tail_scheduler(last_n)

    def follow_scheduler_logs(self) -> Iterator[str]:
        return self._log_store.follow_scheduler()

    def search_logs(self, query: str, run_id: str | None = None) -> list[dict]:
        return self._log_store.search(query, run_id)

    # ── Scheduler management ──────────────────────────────────────────────────

    def _scheduler_pid_path(self) -> str:
        return os.path.join(self._stepyard_dir, "scheduler.pid")

    def _scheduler_command(self, executable: str | None = None) -> list[str]:
        return [
            executable or sys.executable,
            "-m",
            "stepyard.scheduler",
            "--project-dir",
            self.project_dir,
        ]

    def _launchd_plist_path(self, label: str = "com.stepyard.scheduler") -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"

    def _systemd_service_path(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user" / "stepyard.service"

    def scheduler_status(self) -> SchedulerStatus:
        pid_file = self._scheduler_pid_path()
        if not os.path.exists(pid_file):
            return SchedulerStatus(is_running=False)
        try:
            with open(pid_file) as fh:
                pid = int(fh.read().strip())
            os.kill(pid, 0)  # Check if process exists
            return SchedulerStatus(is_running=True, pid=pid)
        except (ProcessLookupError, ValueError, OSError):
            return SchedulerStatus(is_running=False)

    def start_scheduler(self, foreground: bool = False) -> None:
        """Start the scheduler daemon."""
        if foreground:
            import asyncio

            from stepyard.executor.process_manager import ProcessManager
            from stepyard.executor.worker import ExecutorWorker
            from stepyard.scheduler.daemon import SchedulerDaemon, _configure_logging

            log_path = str(self._log_store.scheduler_log_path())
            _configure_logging(log_path)
            pm = ProcessManager(logs_dir=os.path.join(self._stepyard_dir, "logs"))
            scheduler = SchedulerDaemon(
                storage=self.storage,
                log_store=self._log_store,
            )
            executor = ExecutorWorker(
                storage=self.storage,
                process_manager=pm,
                log_store=self._log_store,
            )

            async def run_supervisor():
                await asyncio.gather(
                    scheduler.run_forever(),
                    executor.run_forever(),
                )

            asyncio.run(run_supervisor())
        else:
            # Spawn detached background process
            cmd = self._scheduler_command()
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            with open(self._scheduler_pid_path(), "w") as fh:
                fh.write(str(proc.pid))

    def stop_scheduler(self) -> bool:
        status = self.scheduler_status()
        if not status.is_running or status.pid is None:
            return False
        try:
            import signal

            os.kill(status.pid, signal.SIGTERM)
            try:
                os.remove(self._scheduler_pid_path())
            except OSError:
                pass
            return True
        except ProcessLookupError:
            return False

    def install_system_service(self) -> str:
        """Generate and install a system service file (launchd/systemd).

        Returns a human-readable description of what was installed.
        """
        executable = sys.executable
        if sys.platform == "darwin":
            return self._install_launchd(executable)
        return self._install_systemd(executable)

    def _install_launchd(self, executable: str) -> str:
        import plistlib

        log_path = str(self._log_store.scheduler_log_path())
        label = "com.stepyard.scheduler"
        plist = {
            "Label": label,
            "ProgramArguments": self._scheduler_command(executable),
            "KeepAlive": True,
            "RunAtLoad": True,
            "StandardOutPath": log_path,
            "StandardErrorPath": log_path,
            "WorkingDirectory": self.project_dir,
        }
        plist_path = self._launchd_plist_path(label)
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(plist_path, "wb") as fh:
            plistlib.dump(plist, fh)
        return f"launchd plist installed at {plist_path}\nRun: launchctl load {plist_path}"

    def _install_systemd(self, executable: str) -> str:
        try:
            login = os.getlogin()
        except Exception:
            login = "root"
        log_path = str(self._log_store.scheduler_log_path())
        exec_start = " ".join(self._scheduler_command(executable))
        service_content = f"""[Unit]
Description=Stepyard Scheduler Daemon
After=network.target

[Service]
ExecStart={exec_start}
Restart=always
User={login}
WorkingDirectory={self.project_dir}
StandardOutput=append:{log_path}
StandardError=append:{log_path}

[Install]
WantedBy=default.target
"""
        service_path = self._systemd_service_path()
        service_path.parent.mkdir(parents=True, exist_ok=True)
        service_path.write_text(service_content)
        return (
            f"systemd unit installed at {service_path}\n"
            f"Run: systemctl --user enable --now stepyard.service"
        )

    def uninstall_system_service(self) -> str:
        """Remove the system service file (launchd/systemd).

        Returns a human-readable description of what was removed.
        """
        if sys.platform == "darwin":
            return self._uninstall_launchd()
        return self._uninstall_systemd()

    def _uninstall_launchd(self) -> str:
        label = "com.stepyard.scheduler"
        plist_path = self._launchd_plist_path(label)

        try:
            import subprocess

            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
        except Exception:  # noqa: BLE001 - launchctl may be absent on non-macOS
            pass

        if plist_path.exists():
            plist_path.unlink()
            return f"launchd plist removed at {plist_path}"
        return f"launchd plist not found at {plist_path}"

    def _uninstall_systemd(self) -> str:
        service_path = self._systemd_service_path()

        try:
            import subprocess

            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "stepyard.service"], capture_output=True
            )
        except Exception:  # noqa: BLE001 - systemctl may be absent on non-Linux
            pass

        if service_path.exists():
            service_path.unlink()
            return f"systemd unit removed at {service_path}"
        return f"systemd unit not found at {service_path}"

    # ── DX helpers ────────────────────────────────────────────────────────────

    def init_project(self, *, force: bool = False) -> dict[str, list[str]]:
        """Scaffold a new Stepyard project in :attr:`project_dir`.

        Creates ``flows/``, ``.gitignore``, and an example flow if the
        directory is empty or *force* is ``True``.

        Returns
        -------
        dict
            ``{"created": [...], "skipped": [...]}`` listing which files were
            written and which were already present.
        """
        created: list[str] = []
        skipped: list[str] = []

        def _write(path: str, content: str) -> None:
            if os.path.exists(path) and not force:
                skipped.append(path)
                return
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            created.append(path)

        flows_dir = os.path.join(self.project_dir, "flows")
        os.makedirs(flows_dir, exist_ok=True)

        _write(
            os.path.join(flows_dir, "hello.yaml"),
            """\
name: hello
description: "A minimal example flow"
steps:
  - id: greet
    uses: shell.run
    with:
      command: echo "Hello from Stepyard!"
""",
        )

        _write(
            os.path.join(self.project_dir, ".gitignore"),
            """\
# Stepyard runtime data
.stepyard/
.stepyard_history
""",
        )

        # Force Storage initialisation so the .stepyard/ dir is created.
        _ = self.storage

        return {"created": created, "skipped": skipped}

    def validate_flow(self, flow_file: str) -> list[dict]:
        """Validate *flow_file* and return a list of error dicts.

        Each error dict has keys ``field``, ``message``, and ``hint``.

        Returns an empty list when the flow is valid.
        """
        import difflib  # noqa: PLC0415

        from stepyard.core.flow import Flow  # noqa: PLC0415

        errors: list[dict] = []

        try:
            flow = Flow.from_file(flow_file)
        except Exception as exc:
            # Extract Pydantic validation locations when available.
            if hasattr(exc, "errors"):
                for err in exc.errors():
                    loc = ".".join(str(x) for x in err.get("loc", []))
                    errors.append(
                        {
                            "field": loc or "(root)",
                            "message": err.get("msg", str(err)),
                            "hint": "",
                        }
                    )
            else:
                errors.append({"field": "(root)", "message": str(exc), "hint": ""})
            return errors

        # Semantic validation: check that all `uses` values are registered.
        registry = None
        try:
            from stepyard.plugin import discover_capabilities  # noqa: PLC0415

            registry = discover_capabilities(self.project_dir)
        except Exception:  # noqa: BLE001 - plugin discovery is best-effort during validation
            pass

        if registry is not None:
            available = sorted(registry.nodes.keys())
            for step in _iter_steps(flow.model.steps):
                if not step.uses:
                    continue
                if step.uses not in registry.nodes:
                    close = difflib.get_close_matches(step.uses, available, n=3, cutoff=0.5)
                    hint = f"Did you mean: {', '.join(close)}?" if close else ""
                    errors.append(
                        {
                            "field": f"steps[{step.id}].uses",
                            "message": f"Unknown node '{step.uses}'",
                            "hint": hint,
                        }
                    )

        return errors

    def export_flow_schema(self, output_path: str | None = None) -> str:
        """Export a JSON Schema for flow YAML files.

        If *output_path* is omitted the schema is written to
        ``.stepyard/flow.schema.json`` and that path is returned.
        """
        import json  # noqa: PLC0415

        from stepyard.core.flow import FlowModel  # noqa: PLC0415

        schema = FlowModel.model_json_schema()

        # Enrich the `uses` field with available node names.
        try:
            from stepyard.plugin import discover_capabilities  # noqa: PLC0415

            registry = discover_capabilities(self.project_dir)
            node_names = sorted(registry.nodes.keys())
            if node_names and "properties" in schema:
                # Inject enum into every `uses` property recursively.
                _inject_uses_enum(schema, node_names)
        except Exception:  # noqa: BLE001 - schema enum enrichment is optional
            pass

        if output_path is None:
            output_path = os.path.join(self._stepyard_dir, "flow.schema.json")

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(schema, fh, indent=2)

        return output_path


def _iter_steps(steps, parent_id: str | None = None):
    """Recursively yield all StepModel instances from *steps*."""
    for step in steps:
        yield step
        if getattr(step, "steps", None):
            yield from _iter_steps(step.steps)


def _inject_uses_enum(schema: dict, node_names: list[str]) -> None:
    """Recursively add an ``enum`` hint for ``uses`` fields in the schema."""
    if isinstance(schema, dict):
        if schema.get("title") == "Uses" or "uses" in str(schema.get("description", "")).lower():
            pass
        for key, value in schema.items():
            if key == "uses" and isinstance(value, dict):
                value["enum"] = node_names
                value["description"] = (
                    value.get("description", "")
                    + f"  Available: {', '.join(node_names[:10])}"
                    + (" …" if len(node_names) > 10 else "")
                )
            elif isinstance(value, dict):
                _inject_uses_enum(value, node_names)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _inject_uses_enum(item, node_names)
