from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from stepyard.sdk._stamps import stamp_input_collector

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class InputRequest:
    step_id: str
    env_key: str
    prompt: str
    default: str = ""
    required: bool = True
    secret: bool = False
    choices: list[str] | None = None


InputCollector = Callable[
    [str, Any, dict[str, Any], dict[str, Any]], InputRequest | list[InputRequest] | None
]


def input_collector(node_name: str) -> Callable[[F], F]:
    """Decorator that marks a function as an input collector for a node."""

    def decorator(func: F) -> F:
        return stamp_input_collector(func, node_name)

    return decorator
