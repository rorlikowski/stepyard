from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar, overload

from pydantic import create_model

from stepyard.sdk._stamps import stamp_node

F = TypeVar("F", bound=Callable[..., Any])


class NodeStatus(str, Enum):
    """Outcome of a single node execution.

    Subclasses :class:`str` so existing comparisons against the legacy string
    values (``result.status == "success"``) keep working and the value
    serialises transparently to JSON across the subprocess boundary.
    """

    SUCCESS = "success"
    FAILED = "failed"
    SUSPENDED = "suspended"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.value


class NodeContext:
    def __init__(self, run_id: str, step_id: str, logger: Any = None):
        self.run_id = run_id
        self.step_id = step_id
        self.log = logger or logging.getLogger(f"stepyard.run.{run_id}.{step_id}")
        self.metrics: dict[str, Any] = {}

    def report_progress(self, current: float, total: float) -> None:
        self.log.info(
            f"Progress: {current}/{total}", extra={"progress": {"current": current, "total": total}}
        )


@dataclass
class NodeResult:
    """Structured result returned by a node execution."""

    status: NodeStatus
    output: Any = None
    error: str | None = None
    traceback: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] | None = None
    stderr: str = ""

    def __post_init__(self) -> None:
        # Accept the legacy string form (e.g. ``status="success"``) and the
        # raw value coming back from the subprocess JSON channel, always
        # normalising to a :class:`NodeStatus` member.
        self.status = NodeStatus(self.status)

    @property
    def succeeded(self) -> bool:
        return self.status is NodeStatus.SUCCESS


@overload
def node(func: F, /) -> F: ...


@overload
def node(
    name_or_func: None = None,
    name: str | None = None,
    **metadata: Any,
) -> Callable[[F], F]: ...


@overload
def node(
    name_or_func: str,
    name: str | None = None,
    **metadata: Any,
) -> Callable[[F], F]: ...


def node(
    name_or_func: Any = None,
    name: str | None = None,
    **metadata: Any,
) -> Any:
    """Decorator that marks a function as a Stepyard node.

    Registration is intentionally metadata-only. PluginHost discovers nodes
    from entry point objects instead of process-wide global registries.
    """
    if callable(name_or_func):
        func = name_or_func
        inferred_name = name or func.__name__
        return _make_node(func, inferred_name, metadata)

    def decorator(func: F) -> F:
        inferred_name = name or name_or_func or func.__name__
        return _make_node(func, inferred_name, metadata)

    return decorator


def _make_node(
    func: F,
    name: str,
    metadata: dict[str, Any] | None = None,
) -> F:
    sig = inspect.signature(func)
    annotations = inspect.get_annotations(func, eval_str=True)
    fields: dict[str, tuple[Any, Any]] = {}
    for param_name, param in sig.parameters.items():
        if param_name in ("ctx", "context"):
            continue
        annotation = annotations.get(param_name, Any)
        default = param.default if param.default != inspect.Parameter.empty else ...
        fields[param_name] = (annotation, default)

    input_model = create_model(
        f"Input_{name.replace('.', '_')}",
        __base__=None,
        **fields,  # type: ignore[call-overload]
    )
    input_model.model_rebuild()
    return stamp_node(func, name, dict(metadata or {}), input_model)
