"""
Stepyard shared node invocation core.

Both the in-process invoker (``plugins/invoker.py``) and the subprocess
executor (``core/node_executor.py``) use the same Pydantic validation +
ctx-injection + sync/async dispatch logic.  This module is the single
source of truth for that logic.
"""

from __future__ import annotations

import asyncio
import inspect
import traceback
from typing import Any

from stepyard.sdk.node import NodeContext, NodeResult, NodeStatus


def prepare_and_call(
    func: Any,
    inputs: dict[str, Any],
    ctx: NodeContext,
) -> Any:
    """Validate *inputs*, inject *ctx*, and call *func* synchronously.

    Returns the raw return value (not necessarily a ``NodeResult``).
    Raises on validation or invocation errors.
    """
    validated_inputs = _validate_inputs(func, inputs)
    validated_inputs = _inject_ctx(func, validated_inputs, ctx)
    return func(**validated_inputs)


async def prepare_and_call_async(
    func: Any,
    inputs: dict[str, Any],
    ctx: NodeContext,
) -> Any:
    """Validate *inputs*, inject *ctx*, and call *func* (sync or async).

    Returns the raw return value.  Raises on validation or invocation errors.
    """
    validated_inputs = _validate_inputs(func, inputs)
    validated_inputs = _inject_ctx(func, validated_inputs, ctx)

    if asyncio.iscoroutinefunction(func):
        return await func(**validated_inputs)
    return func(**validated_inputs)


async def invoke_node(
    func: Any,
    inputs: dict[str, Any],
    ctx: NodeContext,
) -> NodeResult:
    """Full invocation: validate → inject ctx → call → wrap result.

    This is the function used by both in-process and subprocess paths so
    that the runtime behaviour is exactly the same.
    """
    try:
        raw = await prepare_and_call_async(func, inputs, ctx)
        if isinstance(raw, NodeResult):
            return raw
        return NodeResult(status=NodeStatus.SUCCESS, output=raw)
    except Exception as exc:
        return NodeResult(
            status=NodeStatus.FAILED,
            error=str(exc),
            traceback=traceback.format_exc(),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _validate_inputs(func: Any, inputs: dict[str, Any]) -> dict[str, Any]:
    """Run Pydantic validation if the node has an input model."""
    input_model = getattr(func, "__stepyard_input_model__", None)
    if input_model is not None:
        validated = input_model.model_validate(inputs)
        return dict(validated.model_dump())
    return dict(inputs)


def _inject_ctx(func: Any, inputs: dict[str, Any], ctx: NodeContext) -> dict[str, Any]:
    """Inject *ctx* into *inputs* if the function signature expects it."""
    sig = inspect.signature(func)
    if any(p in sig.parameters for p in ("ctx", "context")):
        param_name = "ctx" if "ctx" in sig.parameters else "context"
        inputs = dict(inputs)
        inputs[param_name] = ctx
    return inputs
