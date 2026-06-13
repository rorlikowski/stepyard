import pytest

from stepyard.plugin import CapabilityRegistry, NodeInvocationService
from stepyard.sdk.node import NodeContext, node


# Define some test nodes
@node(name="test.add")
def node_add(a: int, b: int) -> int:
    return a + b


@node(name="test.sleep")
def node_sleep(seconds: float):
    import time

    time.sleep(seconds)
    return "done"


@node(name="test.log")
def node_log(msg: str, ctx: NodeContext):
    ctx.log.info(f"Subprocess printed: {msg}")
    print("Normal print on stdout")
    return "printed"


@pytest.mark.asyncio
async def test_node_runner_success():
    registry = CapabilityRegistry()
    registry.register_node("test.add", node_add, "tests.unit.test_node")
    res = await NodeInvocationService(registry, ".").invoke(
        node_name="test.add",
        inputs={"a": 10, "b": 15},
        run_id="test-run",
        step_id="test-step",
        node_ctx=NodeContext(run_id="test-run", step_id="test-step"),
    )
    assert res.status == "success"
    assert res.output == 25


@pytest.mark.asyncio
async def test_node_runner_validation_error():
    # Pass string instead of int
    registry = CapabilityRegistry()
    registry.register_node("test.add", node_add, "tests.unit.test_node")
    res = await NodeInvocationService(registry, ".").invoke(
        node_name="test.add",
        inputs={"a": "not-an-int", "b": 15},
        run_id="test-run",
        step_id="test-step",
        node_ctx=NodeContext(run_id="test-run", step_id="test-step"),
    )
    assert res.status == "failed"
    # Should fail during Pydantic validation
    assert "validation" in res.error.lower() or "input" in res.error.lower()


@pytest.mark.asyncio
async def test_node_runner_timeout():
    registry = CapabilityRegistry()
    registry.register_node("test.sleep", node_sleep, "tests.unit.test_node")
    res = await NodeInvocationService(registry, ".").invoke(
        node_name="test.sleep",
        inputs={"seconds": 0.01},
        run_id="test-run",
        step_id="test-step",
        node_ctx=NodeContext(run_id="test-run", step_id="test-step"),
    )
    assert res.status == "success"
    assert res.output == "done"


@pytest.mark.asyncio
async def test_node_runner_logs_and_stdout():
    registry = CapabilityRegistry()
    registry.register_node("test.log", node_log, "tests.unit.test_node")
    res = await NodeInvocationService(registry, ".").invoke(
        node_name="test.log",
        inputs={"msg": "Hello World"},
        run_id="test-run",
        step_id="test-step",
        node_ctx=NodeContext(run_id="test-run", step_id="test-step"),
    )
    assert res.status == "success"
    assert res.output == "printed"
