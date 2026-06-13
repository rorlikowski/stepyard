import logging
import os
from typing import Any

from stepyard.sdk.hooks import StepExecutionHook
from stepyard.sdk.node import NodeContext, NodeResult, NodeStatus
from stepyard_builtin.system import human_input_env_key

logger = logging.getLogger("stepyard.builtin_hooks")


def _has_precollected_human_input(step_id: str) -> bool:
    logical_step_id = step_id.split("#", 1)[0]
    return any(
        os.environ.get(human_input_env_key(candidate)) is not None
        for candidate in (step_id, logical_step_id)
    )


class ApprovalHook(StepExecutionHook):
    """Suspends execution if a step explicitly requires approval."""

    async def before_execute(
        self, context: NodeContext, step: Any, inputs: dict[str, Any]
    ) -> NodeResult | None:
        if getattr(step, "approval", False):
            logger.info("Step '%s' requires operator approval.", context.step_id)
            return NodeResult(
                status=NodeStatus.SUSPENDED,
                state={"reason": "approval_required", "inputs": inputs},
            )
        return None

    async def after_execute(
        self, context: NodeContext, step: Any, result: NodeResult
    ) -> NodeResult:
        return result


class HumanInputHook(StepExecutionHook):
    """Suspends runtime human input so the parent process can collect it."""

    async def before_execute(
        self, context: NodeContext, step: Any, inputs: dict[str, Any]
    ) -> NodeResult | None:
        if getattr(step, "uses", None) != "human.input":
            return None
        if os.environ.get("STEPYARD_RUNTIME_HUMAN_INPUT") != "1":
            return None
        if _has_precollected_human_input(context.step_id):
            return None

        logger.info("Step '%s' requires operator input.", context.step_id)
        return NodeResult(
            status=NodeStatus.SUSPENDED,
            state={
                "reason": "input_required",
                "inputs": inputs,
            },
        )

    async def after_execute(
        self, context: NodeContext, step: Any, result: NodeResult
    ) -> NodeResult:
        return result


hooks = [ApprovalHook(), HumanInputHook()]

__all__ = ["ApprovalHook", "HumanInputHook", "hooks"]
