import os
import shutil

import pytest

from stepyard.storage.facade import Storage


@pytest.fixture
def temp_storage(tmp_path):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    storage = Storage(str(project_dir))
    yield storage
    # Cleanup temp directory
    shutil.rmtree(project_dir, ignore_errors=True)


def test_init_db(temp_storage):
    assert os.path.exists(temp_storage.db_path)


def test_runs_state_machine(temp_storage):
    # Create run
    run = temp_storage.create_run("run-001", "backup-check")
    assert run["id"] == "run-001"
    assert run["status"] == "queued"

    # Start run
    temp_storage.update_run_status("run-001", "running")
    r = temp_storage.get_run("run-001")
    assert r["status"] == "running"
    assert r["start_time"] is not None

    # Complete run
    temp_storage.update_run_status("run-001", "completed")
    r = temp_storage.get_run("run-001")
    assert r["status"] == "completed"
    assert r["end_time"] is not None
    assert r["error"] is None


def test_step_runs(temp_storage):
    temp_storage.create_run("run-002", "backup-check")
    temp_storage.create_step_run(
        "run-002", "step1", status="running", inputs={"path": "/var/backups"}
    )

    steps = temp_storage.get_step_runs("run-002")
    assert len(steps) == 1
    assert steps[0]["step_id"] == "step1"
    assert steps[0]["status"] == "running"

    temp_storage.update_step_run("run-002", "step1", status="completed", output={"files": 5})
    steps = temp_storage.get_step_runs("run-002")
    assert steps[0]["status"] == "completed"
    assert "files" in steps[0]["output"]


def test_flow_schedules_active(temp_storage):
    # Active by default if not present in DB
    assert temp_storage.is_flow_active("test-flow") is True

    # Set as deactivated
    temp_storage.set_flow_active("test-flow", False)
    assert temp_storage.is_flow_active("test-flow") is False

    # Set as active again
    temp_storage.set_flow_active("test-flow", True)
    assert temp_storage.is_flow_active("test-flow") is True
