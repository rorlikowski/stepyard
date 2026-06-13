"""
Stepyard expression engine.

Provides safe evaluation of ``${{ expr }}`` templates embedded in flow YAML.
The evaluator uses ``simpleeval`` to safely parse and evaluate expressions,
providing a secure subset of Python (no imports, no arbitrary function calls).

Extracted from ``core/flow.py`` to keep the expression engine independently
testable and reusable.

Supported expression forms
--------------------------
* Literals:         ``${{ "hello" }}``, ``${{ 42 }}``, ``${{ true }}``
* Variable lookup:  ``${{ steps.my_step.output }}``
* Subscript:        ``${{ steps.step1.output["key"] }}``
* Comparisons:      ``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``
* Boolean ops:      ``and``, ``or``, ``not``
* String embed:     ``"Result: ${{ steps.step1.output }}"``
"""

from __future__ import annotations

import ast
import re
from functools import lru_cache
from typing import Any

from simpleeval import EvalWithCompoundTypes

# Pattern: ${{ ... }}
EXPR_PATTERN = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


@lru_cache(maxsize=1024)
def _get_ast(expr_str: str) -> ast.expr:
    """Cache the parsed AST to save CPU cycles in loops."""
    return ast.parse(expr_str.strip(), mode="eval").body


def evaluate_expression(expr_str: str, context: dict[str, Any]) -> Any:
    """Parse and safely evaluate a single expression string using simpleeval.

    Uses AST caching to significantly improve performance in loops.
    """
    try:
        node = _get_ast(expr_str)
        evaluator = EvalWithCompoundTypes(names=context)
        return evaluator._eval(node)
    except Exception as exc:
        raise ValueError(f"Failed to evaluate expression '{expr_str}': {exc}") from exc


def resolve_variables(val: Any, context: dict[str, Any]) -> Any:
    """Recursively resolve ``${{ expr }}`` templates in a config structure.

    Handles strings, dicts and lists.  Other types are returned unchanged.
    """
    if isinstance(val, str):
        # Whole-value expression: ${{ expr }} → any type
        full_match = EXPR_PATTERN.fullmatch(val.strip())
        if full_match:
            return evaluate_expression(full_match.group(1), context)

        # Embedded expression: "prefix ${{ expr }} suffix" → string
        def replacer(m: re.Match) -> str:  # type: ignore[type-arg]
            result = evaluate_expression(m.group(1), context)
            return str(result)

        return EXPR_PATTERN.sub(replacer, val)

    if isinstance(val, dict):
        return {k: resolve_variables(v, context) for k, v in val.items()}

    if isinstance(val, list):
        return [resolve_variables(item, context) for item in val]

    return val
