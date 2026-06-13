"""Flow graph navigation for step-to-step transitions."""

from __future__ import annotations

from typing import Any

from stepyard.core.expressions import resolve_variables

END_TARGETS = {"end", "__end__", "$end", "stop", "done"}
NEXT_TARGETS = {"", "next", "continue"}


class FlowNavigationError(ValueError):
    """Raised when a flow transition cannot be resolved safely."""


class FlowNavigator:
    """Resolves the next top-level step in a flow.

    The navigator owns graph semantics (`next`, end targets, visit limits).
    The executor owns node execution and persistence.
    """

    def __init__(self, steps: list[Any]) -> None:
        self.steps = list(steps)
        self.index_by_id = {step.id: idx for idx, step in enumerate(self.steps)}
        self.index_by_lower_id = {step.id.lower(): idx for idx, step in enumerate(self.steps)}

    def execution_id(self, step_id: str, visit_count: int) -> str:
        if visit_count <= 1:
            return step_id
        return f"{step_id}#{visit_count}"

    def validate_visit_limit(self, step: Any, visit_count: int, default_limit: int | None) -> None:
        limit = getattr(step, "max_visits", None)
        if limit is None:
            limit = default_limit
        if limit and visit_count > limit:
            raise FlowNavigationError(
                f"Step '{step.id}' exceeded max_visits={limit}. "
                "Set a higher max_visits value, or 0 for an intentional unbounded loop."
            )

    def next_index(self, current_index: int, step: Any, context: dict[str, Any]) -> int | None:
        target = self.resolve_target(step, context)
        if target is None:
            next_index = current_index + 1
            return next_index if next_index < len(self.steps) else None

        normalized = target.lower()
        if normalized in END_TARGETS:
            return None
        if target in self.index_by_id:
            return self.index_by_id[target]
        if normalized not in self.index_by_lower_id:
            raise FlowNavigationError(f"Step '{step.id}' points to unknown next step '{target}'.")
        return self.index_by_lower_id[normalized]

    def resolve_target(self, step: Any, context: dict[str, Any]) -> str | None:
        next_spec = getattr(step, "next_step", None)
        if next_spec is None:
            return None

        resolved = resolve_variables(next_spec, context)
        if isinstance(resolved, dict):
            resolved = resolved.get("target") or resolved.get("step") or resolved.get("id")
        if resolved is None:
            return None

        target = str(resolved).strip()
        if target.lower() in NEXT_TARGETS:
            return None
        return target
