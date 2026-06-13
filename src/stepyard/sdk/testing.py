"""
stepyard.sdk.testing - lightweight testing harness for Stepyard plugins.

Plugin authors can test their nodes and triggers in **5 lines** without
spinning up a full Stepyard project::

    from stepyard.sdk.testing import invoke_node, fake_context

    async def test_my_node():
        ctx = fake_context(run_id="test", step_id="my_step")
        result = await invoke_node(my_node_func, {"url": "https://example.com"}, ctx=ctx)
        assert result.status == "success"
        assert result.output["status_code"] == 200

The harness uses the same validation + context-injection logic as the
production engine so tests faithfully represent real runtime behaviour.
"""

from __future__ import annotations

import asyncio
from typing import Any

from stepyard.plugins.execution import invoke_node as _invoke_node
from stepyard.sdk.node import NodeContext, NodeResult


def fake_context(
    *,
    run_id: str = "test-run",
    step_id: str = "test-step",
    **extra: Any,
) -> NodeContext:
    """Return a minimal :class:`~stepyard.sdk.node.NodeContext` for testing.

    Parameters
    ----------
    run_id, step_id:
        Identifiers that will appear in logs.  Defaults are fine for most tests.
    **extra:
        Any extra keyword arguments are forwarded to :class:`NodeContext`.
    """
    return NodeContext(run_id=run_id, step_id=step_id, **extra)


async def invoke_node(
    func: Any,
    inputs: dict[str, Any],
    *,
    ctx: NodeContext | None = None,
) -> NodeResult:
    """Invoke *func* with *inputs* using the full production validation path.

    This is the recommended way to write unit tests for node functions.
    It applies Pydantic validation, injects context, and handles both sync
    and async node implementations.

    Parameters
    ----------
    func:
        The node function decorated with ``@node``.
    inputs:
        Raw input dict (as it would arrive from a flow YAML ``with:`` block).
    ctx:
        Optional context.  A default :func:`fake_context` is used when omitted.

    Returns
    -------
    NodeResult
        The result of the invocation.

    Example
    -------
    ::

        from stepyard.sdk import node
        from stepyard.sdk.testing import invoke_node

        @node(name="greet")
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        async def test_greet():
            result = await invoke_node(greet, {"name": "World"})
            assert result.status == "success"
            assert result.output == "Hello, World!"
    """
    if ctx is None:
        ctx = fake_context()
    return await _invoke_node(func, inputs, ctx)


def run_node(
    func: Any,
    inputs: dict[str, Any],
    *,
    ctx: NodeContext | None = None,
) -> NodeResult:
    """Synchronous wrapper around :func:`invoke_node` for use in sync tests.

    Uses ``asyncio.run()`` under the hood.
    """
    return asyncio.run(invoke_node(func, inputs, ctx=ctx))


async def collect_trigger(trigger_fn: Any, *, n: int = 3, **kwargs: Any) -> list[Any]:
    """Collect up to *n* events from an async-generator trigger.

    Useful for testing trigger functions::

        async def test_webhook_trigger():
            events = await collect_trigger(my_webhook_trigger, n=1)
            assert events[0]["method"] == "POST"

    Parameters
    ----------
    trigger_fn:
        The trigger function (decorated with ``@trigger``).  Must return an
        async generator.
    n:
        Maximum number of events to collect.
    **kwargs:
        Configuration arguments forwarded to *trigger_fn*.
    """
    events: list[Any] = []
    gen = trigger_fn(**kwargs)
    try:
        async for event in gen:
            events.append(event)
            if len(events) >= n:
                break
    except (StopAsyncIteration, GeneratorExit):
        pass
    return events
