from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import create_model

from stepyard.sdk._stamps import stamp_trigger

F = TypeVar("F", bound=Callable[..., Any])


def trigger(name: str) -> Callable[[F], F]:
    """Decorator that marks a function as a Stepyard trigger."""

    def decorator(func: F) -> F:
        sig = inspect.signature(func)
        fields: dict[str, tuple[Any, Any]] = {}
        for param_name, param in sig.parameters.items():
            annotation = param.annotation if param.annotation != inspect.Parameter.empty else Any
            default = param.default if param.default != inspect.Parameter.empty else ...
            fields[param_name] = (annotation, default)

        input_model = create_model(
            f"Input_{name.replace('.', '_')}",
            __base__=None,
            **fields,  # type: ignore[call-overload]
        )
        return stamp_trigger(func, name, input_model)

    return decorator
