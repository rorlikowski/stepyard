"""
Stepyard LogStore - file-based log storage with rotation.

Directory layout::

    .stepyard/
    └── logs/
        ├── scheduler.log          # Scheduler daemon output
        ├── scheduler.log.1        # Previous rotation
        └── runs/
            ├── my-flow/
            │   └── run-abc123.log # Per-run combined stdout+stderr
            └── another-flow/
                └── run-def456.log

Each flow process writes directly to its run log file.
The scheduler writes to scheduler.log.
LogStore provides tail / follow / search over these files.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path


class LogStore:
    """Read/write access to Stepyard's file-based log storage."""

    # Limits
    MAX_SIZE_MB: int = 100
    MAX_ROTATIONS: int = 5
    SCHEDULER_LOG_NAME = "scheduler.log"

    def __init__(self, stepyard_dir: str | Path) -> None:
        self.base = Path(stepyard_dir) / "logs"
        self.runs_dir = self.base / "runs"
        self.base.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(exist_ok=True)

    # ── Paths ──────────────────────────────────────────────────────────────────

    def run_log_path(self, run_id: str, flow_name: str | None = None) -> Path:
        if flow_name:
            import re

            flow_slug = re.sub(r"[^a-z0-9]+", "-", flow_name.lower()).strip("-")
            log_dir = self.runs_dir / flow_slug
            log_dir.mkdir(parents=True, exist_ok=True)
            return log_dir / f"{run_id}.log"

        # Fallback: search across all flow directories for the run_id
        matches = list(self.runs_dir.glob(f"*/{run_id}.log"))
        if matches:
            return matches[0]

        # Fallback if not found and flow_name wasn't provided
        return self.runs_dir / "unknown" / f"{run_id}.log"

    def scheduler_log_path(self) -> Path:
        return self.base / self.SCHEDULER_LOG_NAME

    # ── Tail ──────────────────────────────────────────────────────────────────

    def tail(self, run_id: str, lines: int | None = None) -> list[str]:
        """Return all run log lines, or the last *lines* lines when set."""
        return self._tail_file(self.run_log_path(run_id), lines)

    def tail_scheduler(self, lines: int | None = None) -> list[str]:
        return self._tail_file(self.scheduler_log_path(), lines)

    @staticmethod
    def _tail_file(path: Path, lines: int | None) -> list[str]:
        if not path.exists():
            return []
        try:
            if lines is not None and lines <= 0:
                return []
            buf: deque[str] = deque(maxlen=lines)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    buf.append(line.rstrip("\n"))
            return list(buf)
        except OSError:
            return []

    # ── Follow (live tail) ────────────────────────────────────────────────────

    def follow(self, run_id: str, poll_interval: float = 0.25) -> Iterator[str]:
        """Yield new log lines as they arrive (live tail).

        Stops when the log file has not grown for more than 30 seconds after
        an initial EOF - caller should wrap in a thread or async task.
        """
        yield from self._follow_file(self.run_log_path(run_id), poll_interval)

    def follow_scheduler(self, poll_interval: float = 0.25) -> Iterator[str]:
        yield from self._follow_file(self.scheduler_log_path(), poll_interval)

    @staticmethod
    def _follow_file(path: Path, poll_interval: float) -> Iterator[str]:
        idle_timeout = 30.0
        idle_elapsed = 0.0

        while not path.exists():
            time.sleep(poll_interval)
            idle_elapsed += poll_interval
            if idle_elapsed > idle_timeout:
                return

        with open(path, encoding="utf-8", errors="replace") as fh:
            while True:
                line = fh.readline()
                if line:
                    idle_elapsed = 0.0
                    yield line.rstrip("\n")
                else:
                    time.sleep(poll_interval)
                    idle_elapsed += poll_interval
                    if idle_elapsed > idle_timeout:
                        return

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, run_id: str | None = None) -> list[dict]:
        """Search log files for lines matching *query* (case-insensitive).

        Returns list of dicts: {run_id, line_number, text}.
        """
        results: list[dict] = []
        q = query.lower()

        if run_id:
            paths = [(run_id, self.run_log_path(run_id))]
        else:
            paths = [
                (p.name[:-4], p)  # name is run_id.log
                for p in self.runs_dir.rglob("*.log")
            ]

        for rid, path in paths:
            if not path.exists():
                continue
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for lineno, text in enumerate(fh, 1):
                        if q in text.lower():
                            results.append(
                                {
                                    "run_id": rid,
                                    "line_number": lineno,
                                    "text": text.rstrip("\n"),
                                }
                            )
            except OSError:
                continue

        return results

    # ── Rotation ──────────────────────────────────────────────────────────────

    def rotate_scheduler_log(self) -> None:
        """Rotate scheduler.log if it exceeds MAX_SIZE_MB."""
        path = self.scheduler_log_path()
        if not path.exists():
            return
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb < self.MAX_SIZE_MB:
            return

        # Shift existing rotations
        for i in range(self.MAX_ROTATIONS - 1, 0, -1):
            src = path.parent / f"{path.name}.{i}"
            dst = path.parent / f"{path.name}.{i + 1}"
            if src.exists():
                src.rename(dst)

        rotated = path.parent / f"{path.name}.1"
        path.rename(rotated)

    def clean_old_run_logs(self, keep_count: int = 200) -> int:
        """Delete oldest run log files, keeping the most recent *keep_count*.

        Returns the number of files deleted.
        """
        logs = sorted(self.runs_dir.rglob("*.log"), key=lambda p: p.stat().st_mtime)
        to_delete = logs[: max(0, len(logs) - keep_count)]
        for p in to_delete:
            try:
                p.unlink()
                try:
                    p.parent.rmdir()
                except OSError:
                    pass
            except OSError:
                pass
        return len(to_delete)
