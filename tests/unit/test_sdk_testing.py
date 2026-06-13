"""
Tests for stepyard.sdk.testing - the plugin testing harness.
"""

from __future__ import annotations

import pytest

from stepyard.sdk import NodeContext, node
from stepyard.sdk.testing import fake_context, invoke_node, run_node


@node(name="_test.add")
def _add_node(a: int, b: int) -> int:
    return a + b


@node(name="_test.add_ctx")
def _add_node_with_ctx(a: int, b: int, ctx: NodeContext) -> dict:
    return {"sum": a + b, "step_id": ctx.step_id}


@node(name="_test.async_add")
async def _async_add_node(x: int) -> int:
    return x * 2


@node(name="_test.failing")
def _failing_node(msg: str) -> str:
    raise ValueError(msg)


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invoke_node_success():
    result = await invoke_node(_add_node, {"a": 2, "b": 3})
    assert result.status == "success"
    assert result.output == 5


@pytest.mark.asyncio
async def test_invoke_node_injects_context():
    ctx = fake_context(step_id="my-step")
    result = await invoke_node(_add_node_with_ctx, {"a": 1, "b": 2}, ctx=ctx)
    assert result.status == "success"
    assert result.output["step_id"] == "my-step"
    assert result.output["sum"] == 3


@pytest.mark.asyncio
async def test_invoke_async_node():
    result = await invoke_node(_async_add_node, {"x": 7})
    assert result.status == "success"
    assert result.output == 14


@pytest.mark.asyncio
async def test_invoke_node_failure_returns_failed():
    result = await invoke_node(_failing_node, {"msg": "boom"})
    assert result.status == "failed"
    assert "boom" in (result.error or "")


def test_run_node_sync():
    result = run_node(_add_node, {"a": 10, "b": 5})
    assert result.status == "success"
    assert result.output == 15


def test_fake_context_defaults():
    ctx = fake_context()
    assert ctx.run_id == "test-run"
    assert ctx.step_id == "test-step"


def test_fake_context_custom():
    ctx = fake_context(run_id="r-1", step_id="s-1")
    assert ctx.run_id == "r-1"
    assert ctx.step_id == "s-1"
