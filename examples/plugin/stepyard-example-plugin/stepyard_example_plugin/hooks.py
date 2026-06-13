"""A custom hook for the example plugin.

Hooks wrap every step. ``before_execute`` may short-circuit a step by returning
a :class:`NodeResult` (this is exactly how the built-in approval/human-input
hooks pause a run); returning ``None`` lets the step run normally.
``after_execute`` can inspect or rewrite the result.

The entry point must point at a hook INSTANCE (see ``timing_hook`` below),
not the class.
"""

from __future__ import annotations

import time
from typing import Any

from stepyard.sdk import NodeContext, NodeResult, StepExecutionHook


class TimingHook(StepExecutionHook):
    """Logs how long each step takes and warns about slow steps."""

    def __init__(self, slow_threshold_s: float = 5.0) -> None:
        self.slow_threshold_s = slow_threshold_s
        self._started: dict[str, float] = {}

    async def before_execute(
        self, context: NodeContext, step: Any, inputs: dict[str, Any]
    ) -> NodeResult | None:
        self._started[context.step_id] = time.monotonic()
        return None  # don't interfere - let the step run

    async def after_execute(
        self, context: NodeContext, step: Any, result: NodeResult
    ) -> NodeResult:
        started = self._started.pop(context.step_id, None)
        if started is not None:
            elapsed = time.monotonic() - started
            context.log.info("Step '%s' took %.2fs", context.step_id, elapsed)
            if elapsed > self.slow_threshold_s:
                context.log.warning(
                    "Step '%s' is slow (%.2fs > %.2fs threshold)",
                    context.step_id,
                    elapsed,
                    self.slow_threshold_s,
                )
        return result


# Register THIS instance in pyproject.toml under [project.entry-points."stepyard.hooks"].
timing_hook = TimingHook()

__all__ = ["TimingHook", "timing_hook"]
