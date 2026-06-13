import shutil
import sys

import pytest

from stepyard.api.service import StepyardService
from stepyard.core.flow import Flow
from stepyard.core.service import Engine
from stepyard.plugin import CapabilityRegistry
from stepyard.sdk.node import node
from stepyard.storage.facade import Storage


@node(name="test.add")
def _test_add(a: int, b: int) -> int:
    return a + b


@pytest.fixture
def temp_storage(tmp_path):
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    storage = Storage(str(project_dir))
    yield storage
    shutil.rmtree(project_dir, ignore_errors=True)


@pytest.fixture
def test_registry():
    registry = CapabilityRegistry()
    registry.register_node("test.add", _test_add, "tests.unit.test_service")
    return registry


@pytest.mark.asyncio
async def test_engine_simple_flow(temp_storage, test_registry):
    # Ensure test nodes are registered by importing test_node

    yaml_content = """
    name: simple-flow
    steps:
      - id: step1
        uses: test.add
        with:
          a: 5
          b: 7
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-simple", flow.model.name)
    await engine.execute_run("run-simple", flow)

    run_db = temp_storage.get_run("run-simple")
    assert run_db["status"] == "completed"

    steps_db = temp_storage.get_step_runs("run-simple")
    assert len(steps_db) == 1
    assert steps_db[0]["step_id"] == "step1"
    assert steps_db[0]["status"] == "completed"
    assert "12" in steps_db[0]["output"]  # 5 + 7 = 12


@pytest.mark.asyncio
async def test_engine_step_dependencies(temp_storage, test_registry):

    yaml_content = """
    name: dependent-flow
    steps:
      - id: step1
        uses: test.add
        with:
          a: 5
          b: 5
      - id: step2
        uses: test.add
        with:
          a: ${{ steps.step1.output }}
          b: 10
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-dep", flow.model.name)
    await engine.execute_run("run-dep", flow)

    run_db = temp_storage.get_run("run-dep")
    assert run_db["status"] == "completed"

    steps_db = temp_storage.get_step_runs("run-dep")
    assert len(steps_db) == 2
    assert steps_db[1]["step_id"] == "step2"
    assert "20" in steps_db[1]["output"]  # (5+5) + 10 = 20


@pytest.mark.asyncio
async def test_engine_exposes_trigger_run_id(temp_storage):
    yaml_content = """
    name: trigger-context-flow
    steps:
      - id: echo_run_id
        uses: shell.run
        with:
          command: "echo '${{ trigger.run_id }}'"
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage)

    temp_storage.create_run("run-trigger-context", flow.model.name, trigger_type="manual")
    await engine.execute_run("run-trigger-context", flow)

    run_db = temp_storage.get_run("run-trigger-context")
    assert run_db["status"] == "completed"

    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-trigger-context")}
    assert "run-trigger-context" in steps_db["echo_run_id"]["output"]


@pytest.mark.asyncio
async def test_engine_conditional_if(temp_storage, test_registry):

    yaml_content = """
    name: cond-flow
    steps:
      - id: step1
        uses: test.add
        with:
          a: 1
          b: 1
      - id: step2
        uses: test.add
        with:
          a: 2
          b: 2
        if: ${{ steps.step1.output == 3 }}
      - id: step3
        uses: test.add
        with:
          a: 3
          b: 3
        if: ${{ steps.step1.output == 2 }}
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-cond", flow.model.name)
    await engine.execute_run("run-cond", flow)

    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-cond")}
    assert steps_db["step1"]["status"] == "completed"
    assert steps_db["step2"]["status"] == "skipped"
    assert steps_db["step3"]["status"] == "completed"


@pytest.mark.asyncio
async def test_engine_retry_on_failure(temp_storage, test_registry):

    # test.add fails if validation fails, e.g. passing a string
    yaml_content = """
    name: retry-flow
    steps:
      - id: step1
        uses: test.add
        with:
          a: "invalid"
          b: 5
        retry:
          attempts: 2
          initial_delay: 0.1
          backoff_factor: 1.5
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-retry", flow.model.name)
    await engine.execute_run("run-retry", flow)

    steps_db = temp_storage.get_step_runs("run-retry")
    assert len(steps_db) == 1
    assert steps_db[0]["attempt"] == 2
    assert steps_db[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_engine_continue_on_error(temp_storage, test_registry):

    yaml_content = """
    name: continue-flow
    steps:
      - id: step1
        uses: test.add
        with:
          a: "invalid"
          b: 5
        continue_on_error: true
      - id: step2
        uses: test.add
        with:
          a: 1
          b: 1
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-continue", flow.model.name)
    await engine.execute_run("run-continue", flow)

    run_db = temp_storage.get_run("run-continue")
    # Because continue_on_error was true, the run completed successfully
    assert run_db["status"] == "completed"

    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-continue")}
    assert steps_db["step1"]["status"] == "failed"
    assert steps_db["step2"]["status"] == "completed"


@pytest.mark.asyncio
async def test_engine_next_jumps_forward(temp_storage, test_registry):
    yaml_content = """
    name: jump-forward-flow
    steps:
      - id: step1
        uses: test.add
        next: step3
        with:
          a: 1
          b: 1
      - id: step2
        uses: test.add
        with:
          a: 100
          b: 100
      - id: step3
        uses: test.add
        with:
          a: ${{ steps.step1.output }}
          b: 3
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-jump-forward", flow.model.name)
    await engine.execute_run("run-jump-forward", flow)

    run_db = temp_storage.get_run("run-jump-forward")
    assert run_db["status"] == "completed"

    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-jump-forward")}
    assert steps_db["step1"]["status"] == "completed"
    assert "step2" not in steps_db
    assert steps_db["step3"]["status"] == "completed"
    assert "5" in steps_db["step3"]["output"]


@pytest.mark.asyncio
async def test_engine_next_allows_backwards_jump_with_latest_context(temp_storage, test_registry):
    yaml_content = """
    name: jump-back-flow
    steps:
      - id: loop
        uses: test.add
        max_visits: 3
        next: ${{ 'loop' if visits.loop < 3 else 'end' }}
        with:
          a: ${{ visits.loop }}
          b: 0
      - id: after
        uses: test.add
        with:
          a: 100
          b: 100
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-jump-back", flow.model.name)
    await engine.execute_run("run-jump-back", flow)

    run_db = temp_storage.get_run("run-jump-back")
    assert run_db["status"] == "completed"

    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-jump-back")}
    assert steps_db["loop"]["output"] == "1"
    assert steps_db["loop#2"]["output"] == "2"
    assert steps_db["loop#3"]["output"] == "3"
    assert "after" not in steps_db


@pytest.mark.asyncio
async def test_engine_next_stops_when_max_visits_is_exceeded(temp_storage, test_registry):
    yaml_content = """
    name: guarded-jump-flow
    steps:
      - id: loop
        uses: test.add
        max_visits: 2
        next: loop
        with:
          a: ${{ visits.loop }}
          b: 0
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage, registry=test_registry)

    temp_storage.create_run("run-jump-guard", flow.model.name)
    await engine.execute_run("run-jump-guard", flow)

    run_db = temp_storage.get_run("run-jump-guard")
    assert run_db["status"] == "failed"
    assert "exceeded max_visits=2" in run_db["error"]

    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-jump-guard")}
    assert steps_db["loop"]["status"] == "completed"
    assert steps_db["loop#2"]["status"] == "completed"
    assert "loop#3" not in steps_db


@pytest.mark.asyncio
async def test_engine_runtime_human_input_suspends_each_revisited_step(temp_storage, monkeypatch):
    monkeypatch.setenv("STEPYARD_RUNTIME_HUMAN_INPUT", "1")
    yaml_content = """
    name: runtime-input-loop
    steps:
      - id: ask
        uses: human.input
        max_visits: 2
        next: send
        with:
          prompt: Message
      - id: send
        uses: shell.run
        max_visits: 2
        next: "${{ 'ask' if visits.send < 2 else 'end' }}"
        with:
          command: "echo '${{ steps.ask.output }}'"
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage)

    temp_storage.create_run("run-runtime-input", flow.model.name)
    await engine.execute_run("run-runtime-input", flow)

    run_db = temp_storage.get_run("run-runtime-input")
    assert run_db["status"] == "waiting_for_input"
    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-runtime-input")}
    assert steps_db["ask"]["status"] == "pending"

    temp_storage.update_step_run("run-runtime-input", "ask", status="completed", output="first")
    temp_storage.update_run_status("run-runtime-input", "running")
    await engine.execute_run("run-runtime-input", flow)

    run_db = temp_storage.get_run("run-runtime-input")
    assert run_db["status"] == "waiting_for_input"
    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-runtime-input")}
    assert steps_db["send"]["status"] == "completed"
    assert steps_db["ask#2"]["status"] == "pending"

    temp_storage.update_step_run("run-runtime-input", "ask#2", status="completed", output="second")
    temp_storage.update_run_status("run-runtime-input", "running")
    await engine.execute_run("run-runtime-input", flow)

    run_db = temp_storage.get_run("run-runtime-input")
    assert run_db["status"] == "completed"
    steps_db = {s["step_id"]: s for s in temp_storage.get_step_runs("run-runtime-input")}
    assert "first" in steps_db["send"]["output"]
    assert "second" in steps_db["send#2"]["output"]


@pytest.mark.asyncio
async def test_engine_manual_approval(temp_storage):

    yaml_content = """
    name: approval-flow
    steps:
      - id: step1
        uses: test.add
        with:
          a: 5
          b: 5
        approval: true
    """
    flow = Flow.from_yaml(yaml_content)
    engine = Engine(temp_storage)

    temp_storage.create_run("run-approve", flow.model.name)
    await engine.execute_run("run-approve", flow)

    run_db = temp_storage.get_run("run-approve")
    # Run should halt on step1 and wait for approval
    assert run_db["status"] == "waiting_for_approval"

    steps_db = temp_storage.get_step_runs("run-approve")
    assert steps_db[0]["status"] == "pending"


def test_service_scheduler_helper_paths_and_command(tmp_path):
    svc = StepyardService(str(tmp_path))

    assert svc._scheduler_pid_path() == str(tmp_path / ".stepyard" / "scheduler.pid")
    assert svc._scheduler_command("/python") == [
        "/python",
        "-m",
        "stepyard.scheduler",
        "--project-dir",
        str(tmp_path),
    ]
    assert svc._scheduler_command()[0] == sys.executable
    assert svc._systemd_service_path().name == "stepyard.service"
    assert svc._launchd_plist_path().name == "com.stepyard.scheduler.plist"
