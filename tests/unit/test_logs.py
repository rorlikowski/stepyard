from __future__ import annotations

from pathlib import Path

from stepyard.api.service import StepyardService
from stepyard.cli.commands.logs import _follow_all_runs
from stepyard.logging_.log_store import LogStore


def _write_run_log(store: LogStore, run_id: str, flow_name: str, count: int) -> Path:
    path = store.run_log_path(run_id, flow_name)
    path.write_text("\n".join(f"line {idx}" for idx in range(count)) + "\n", encoding="utf-8")
    return path


def test_log_store_returns_full_run_log_by_default(tmp_path):
    store = LogStore(tmp_path)
    _write_run_log(store, "run-001", "long-flow", 350)

    lines = store.tail("run-001")

    assert len(lines) == 350
    assert lines[0] == "line 0"
    assert lines[-1] == "line 349"


def test_log_store_lines_argument_tails_run_log(tmp_path):
    store = LogStore(tmp_path)
    _write_run_log(store, "run-001", "long-flow", 350)

    lines = store.tail("run-001", 7)

    assert lines == [f"line {idx}" for idx in range(343, 350)]


def test_service_returns_full_run_log_by_default(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    svc = StepyardService(str(project_dir))
    _write_run_log(svc._log_store, "run-001", "long-flow", 301)

    lines = svc.get_log_lines("run-001")

    assert len(lines) == 301
    assert lines[0] == "line 0"


def test_follow_all_runs_has_no_default_limit(monkeypatch):
    executed: dict[str, object] = {}

    class FakeResult:
        def mappings(self):
            return self

        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            executed["query"] = str(query)
            executed["params"] = params
            return FakeResult()

    class FakeStorage:
        def get_connection(self):
            return FakeConnection()

    class FakeService:
        storage = FakeStorage()

    _follow_all_runs(FakeService())

    assert "LIMIT" not in str(executed["query"])
    assert executed["params"] == {}


def test_follow_all_runs_applies_explicit_limit(monkeypatch):
    executed: dict[str, object] = {}

    class FakeResult:
        def mappings(self):
            return self

        def fetchall(self):
            return []

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            executed["query"] = str(query)
            executed["params"] = params
            return FakeResult()

    class FakeStorage:
        def get_connection(self):
            return FakeConnection()

    class FakeService:
        storage = FakeStorage()

    _follow_all_runs(FakeService(), limit=25)

    assert "LIMIT :limit" in str(executed["query"])
    assert executed["params"] == {"limit": 25}
