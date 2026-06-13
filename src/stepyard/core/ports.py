"""
Stepyard port (interface) definitions.

These Protocol classes define the *contracts* that concrete implementations
must satisfy.  The engine, scheduler, and CLI depend only on these protocols,
not on the concrete classes (Dependency Inversion Principle).

Usage example::

    from stepyard.core.ports import RunStorePort, NodeInvokerPort

    class Engine:
        def __init__(self, store: RunStorePort, invoker: NodeInvokerPort) -> None:
            ...
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunStorePort(Protocol):
    """Minimal storage interface used by the engine.

    The concrete ``Storage`` class satisfies this protocol.  Any test double
    or alternative back-end only needs to implement these methods.
    """

    def get_run(self, run_id: str) -> dict[str, Any] | None: ...
    def create_run(
        self,
        run_id: str,
        flow_name: str,
        *,
        trigger_type: str | None = None,
        trigger_payload: Any = None,
    ) -> dict[str, Any]: ...
    def update_run_status(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
    ) -> None: ...
    def get_step_runs(self, run_id: str) -> list[dict[str, Any]]: ...
    def create_step_run(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str = "running",
        attempt: int = 1,
        inputs: dict[str, Any] | None = None,
    ) -> None: ...
    def update_step_run(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str | None = None,
        output: Any = None,
        error: str | None = None,
    ) -> None: ...
    def write_audit_log(
        self,
        action: str,
        actor: str,
        *,
        target: str | None = None,
        details: str | None = None,
    ) -> None: ...


@runtime_checkable
class NodeInvokerPort(Protocol):
    """Protocol for invoking a named node capability."""

    async def invoke(
        self,
        node_name: str,
        inputs: dict[str, Any],
        run_id: str,
        step_id: str,
        node_ctx: Any,
    ) -> Any: ...


@runtime_checkable
class CapabilitySourcePort(Protocol):
    """Read-only view of the capability registry needed by the engine."""

    @property
    def hooks(self) -> list[Any]: ...

    def get_node(self, name: str) -> Any | None: ...
    def get_trigger(self, name: str) -> Any | None: ...
