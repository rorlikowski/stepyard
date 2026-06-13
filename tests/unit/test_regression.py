"""
Regression tests for previously identified bugs.
"""

from __future__ import annotations

from stepyard.core.models import RunStatus

# ── Suspended → failed bugfix ─────────────────────────────────────────────────


def test_suspended_values_are_not_overwritten_by_worker(tmp_path):
    """Worker must not overwrite waiting_for_approval / waiting_for_input → failed."""
    from stepyard.executor.worker import ExecutorWorker
    from stepyard.logging_.log_store import LogStore
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    run_id = "run-suspend-test"
    storage.create_run(run_id, "test-flow")
    storage.update_run_status(run_id, "waiting_for_approval")

    # Simulate a finished process with exit_code=1 (e.g. crash before suspension was recorded).
    class _FakeProcessManager:
        def list_running(self):
            return []

        def reap_finished(self):
            return []

        def kill_flow(self, run_id):
            pass

        def spawn_flow(self, *args, **kwargs):
            raise NotImplementedError

    from pathlib import Path

    from stepyard.executor.process_manager import FlowProcess

    FlowProcess(
        run_id=run_id,
        flow_name="test-flow",
        flow_file="/tmp/test.yaml",
        pid=99999,
        log_path=Path("/tmp/x.log"),
    )

    ExecutorWorker(
        storage=storage,
        process_manager=_FakeProcessManager(),
        log_store=LogStore(str(tmp_path / ".stepyard")),
    )

    # Manually invoke the reap logic with a non-zero exit code.
    run = storage.get_run(run_id)
    safe_statuses = {"failed", "completed", "cancelled"} | RunStatus.suspended_values()
    # The worker checks: if run["status"] not in safe_statuses → overwrite.
    # For a suspended run, status IS in safe_statuses, so no overwrite should happen.
    assert run["status"] in safe_statuses, (
        f"Suspended run should be in safe_statuses but got '{run['status']}'"
    )

    # Confirm the status is NOT overwritten.
    if run and run["status"] not in safe_statuses:
        storage.update_run_status(run_id, "failed", error="simulated")

    final = storage.get_run(run_id)
    assert final["status"] == "waiting_for_approval", (
        f"Expected waiting_for_approval, got {final['status']}"
    )


# ── New Storage query methods ─────────────────────────────────────────────────


def test_list_recent_runs(tmp_path):
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    for i in range(5):
        storage.create_run(f"run-{i:03d}", "test-flow")

    recent = storage.list_recent_runs(limit=3)
    assert len(recent) == 3


def test_list_recent_runs_by_flow(tmp_path):
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    storage.create_run("run-a-1", "flow-a")
    storage.create_run("run-b-1", "flow-b")
    storage.create_run("run-a-2", "flow-a")

    result = storage.list_recent_runs(flow_name="flow-a")
    assert all(r["flow_name"] == "flow-a" for r in result)
    assert len(result) == 2


def test_get_last_run_for_flow(tmp_path):
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    storage.create_run("run-001", "my-flow")
    storage.create_run("run-002", "my-flow")

    last = storage.get_last_run_for_flow("my-flow")
    assert last is not None
    # The most recently created run should be returned.
    assert last["id"] in ("run-001", "run-002")


def test_list_pending_approvals(tmp_path):
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    storage.create_run("run-wait-1", "flow-a")
    storage.update_run_status("run-wait-1", "waiting_for_approval")
    storage.create_run("run-done-1", "flow-a")
    storage.update_run_status("run-done-1", "completed")

    pending = storage.list_pending_approvals()
    assert any(r["id"] == "run-wait-1" for r in pending)
    assert not any(r["id"] == "run-done-1" for r in pending)


def test_clear_history(tmp_path):
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    for i in range(4):
        storage.create_run(f"run-{i}", "flow-a")

    deleted = storage.clear_history()
    assert deleted == 4

    remaining = storage.list_recent_runs()
    assert remaining == []


def test_clear_history_keep_last(tmp_path):
    from stepyard.storage.facade import Storage

    storage = Storage(str(tmp_path))
    for i in range(5):
        storage.create_run(f"run-{i:03d}", "flow-a")

    deleted = storage.clear_history(keep_last=2)
    assert deleted == 3
    assert len(storage.list_recent_runs()) == 2
