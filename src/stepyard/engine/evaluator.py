"""
Stepyard ConditionEvaluator - shared boolean/loop condition logic.

Centralises the coercion rules for ``if``, ``while``, and loop resolution so
that the exact same logic is used in the engine and in the ``system.if``
built-in node (eliminating the duplication noted in the architecture audit).
"""

from __future__ import annotations

import ast
import logging
from typing import Any

from stepyard.core.expressions import resolve_variables

logger = logging.getLogger("stepyard.engine.evaluator")

# Falsy string values used by the ``while`` condition and ``system.if``.
_FALSY_STRINGS: frozenset[str] = frozenset({"false", "0", "no", "none", ""})


def coerce_bool(value: Any) -> bool:
    """Coerce an arbitrary value to bool using Stepyard's truthiness rules.

    String values of ``"false"``, ``"0"``, ``"no"``, ``"none"``, and ``""``
    are treated as falsy regardless of Python's default ``bool()`` behaviour.
    All other truthy-by-Python values are truthy.
    """
    if isinstance(value, str) and value.lower() in _FALSY_STRINGS:
        return False
    return bool(value)


class ConditionEvaluator:
    """Evaluates ``if``, ``while``, and ``loop`` expressions for a step."""

    # ── if-condition ─────────────────────────────────────────────────────────

    @staticmethod
    def evaluate_if(
        step: Any,
        context: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Evaluate the ``if`` condition of *step*.

        Returns
        -------
        (skip, error_message)
            *skip* is ``True`` when the condition evaluated to falsy (step
            should be skipped).  *error_message* is non-None when evaluation
            itself raised an exception.
        """
        try:
            result = resolve_variables(step.if_cond, context)
            return (not coerce_bool(result), None)
        except Exception as exc:
            msg = f"Error evaluating 'if' condition of step '{step.id}': {exc}"
            logger.error(msg)
            return False, msg

    # ── loop resolution ───────────────────────────────────────────────────────

    @staticmethod
    def resolve_loop(
        step: Any,
        context: dict[str, Any],
    ) -> tuple[list[Any], bool, bool, str | None]:
        """Resolve the ``loop`` or ``while`` configuration of *step*.

        Returns
        -------
        (items, is_loop, is_while, error_message)
        """
        loop_spec = getattr(step, "loop", None)
        while_cond = getattr(step, "while_cond", None)

        if loop_spec is not None:
            try:
                resolved = resolve_variables(loop_spec, context)
                if isinstance(resolved, str):
                    try:
                        resolved = ast.literal_eval(resolved)
                    except (ValueError, SyntaxError):
                        if "," in resolved:
                            resolved = [x.strip() for x in resolved.split(",")]
                if not isinstance(resolved, (list, tuple)):
                    resolved = [resolved]
                return list(resolved), True, False, None
            except Exception as exc:
                msg = f"Error evaluating 'loop' for step '{step.id}': {exc}"
                logger.error(msg)
                return [], True, False, msg

        if while_cond is not None:
            return [None], False, True, None

        return [None], False, False, None

    # ── while-condition per iteration ─────────────────────────────────────────

    @staticmethod
    def check_while(
        step: Any,
        context: dict[str, Any],
        last_output: Any = None,
    ) -> tuple[bool, str | None]:
        """Evaluate the ``while`` condition for the next iteration.

        Returns
        -------
        (should_stop, error_message)
        """
        try:
            result = resolve_variables(step.while_cond, context)
            return (not coerce_bool(result), None)
        except Exception as exc:
            msg = f"Error evaluating 'while' condition of step '{step.id}': {exc}"
            logger.error(msg)
            return True, msg
