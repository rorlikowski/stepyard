from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from stepyard.sdk.node import NodeContext, NodeResult


@runtime_checkable
class StepExecutionHook(Protocol):
    """Protocol for hooks that run before and after step execution."""

    async def before_execute(
        self, context: NodeContext, step: Any, inputs: dict[str, Any]
    ) -> NodeResult | None:
        return None

    async def after_execute(
        self, context: NodeContext, step: Any, result: NodeResult
    ) -> NodeResult:
        return result
