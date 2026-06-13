"""
Stepyard typed error hierarchy.

Every error raised by the runtime inherits from StepyardError so callers
can reliably distinguish Stepyard failures from unexpected exceptions.

Error classes:

    ConfigurationError  - bad flow spec, missing connection or secret
    ValidationError     - input/output schema mismatch
    PluginError         - plugin loading or registration failure
    NodeExecutionError  - node invocation failed (wraps node-level errors)
    TransientError      - temporary network / rate-limit issue  (safe to retry)
    CancelledError      - deliberate cancellation by operator
    StepyardRuntimeError - node subprocess crash or internal Stepyard fault
    FlowNotFoundError   - flow YAML file could not be located
"""

from __future__ import annotations


class StepyardError(Exception):
    """Base class for all Stepyard errors."""

    #: Human-readable error class tag used in logs and storage.
    error_class: str = "unknown"

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause

    def __str__(self) -> str:  # noqa: D105
        base = super().__str__()
        if self.__cause__:
            return f"{base}: {self.__cause__}"
        return base


# ─── Concrete error classes ────────────────────────────────────────────────────


class ConfigurationError(StepyardError):
    """Flow spec is invalid, or a required connection / secret is absent."""

    error_class = "configuration"


class ValidationError(StepyardError):
    """Input or output schema mismatch.

    Raised when Pydantic validation of node inputs fails so that callers can
    distinguish validation failures (permanent - fix the flow) from transient
    failures (retry).

    Attributes
    ----------
    field_path:
        Dot-separated path to the invalid field, e.g. ``"with.url"``.
    invalid_value:
        The value that failed validation (may be None).
    """

    error_class = "validation"

    def __init__(
        self,
        message: str,
        *,
        field_path: str | None = None,
        invalid_value: object = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.field_path = field_path
        self.invalid_value = invalid_value


class PluginError(StepyardError):
    """Plugin loading, registration, or discovery failure.

    Raised when a plugin entry point cannot be imported, when two plugins
    register the same capability name, or when a required plugin is missing.

    Attributes
    ----------
    plugin_name:
        The entry point name or package name of the offending plugin.
    """

    error_class = "plugin"

    def __init__(
        self,
        message: str,
        *,
        plugin_name: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.plugin_name = plugin_name


class NodeExecutionError(StepyardError):
    """A node invocation failed.

    Wraps the raw error returned by a node so that upper layers can handle
    node failures uniformly without pattern-matching on arbitrary exception types.

    Attributes
    ----------
    node_name:
        The ``uses`` value from the flow step, e.g. ``"http.request"``.
    step_id:
        The step ID where the failure occurred.
    """

    error_class = "node_execution"

    def __init__(
        self,
        message: str,
        *,
        node_name: str | None = None,
        step_id: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        self.node_name = node_name
        self.step_id = step_id


class TransientError(StepyardError):
    """Temporary failure that is safe to retry (network, rate-limit, …)."""

    error_class = "transient"

    def __init__(
        self,
        message: str,
        *,
        cause: BaseException | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, cause=cause)
        #: Optional hint for how many seconds to wait before retrying.
        self.retry_after = retry_after


class CancelledError(StepyardError):
    """Run or step was deliberately cancelled by an operator."""

    error_class = "cancelled"


class StepyardRuntimeError(StepyardError):
    """Node subprocess crash or internal Stepyard failure.

    Named ``StepyardRuntimeError`` to avoid shadowing the built-in
    ``RuntimeError``.
    """

    error_class = "runtime"


# Keep the old name as an alias for backward compatibility.
RuntimeError = StepyardRuntimeError  # noqa: A001


class FlowNotFoundError(ConfigurationError):
    """The requested flow YAML file could not be located."""

    def __init__(self, flow_name: str) -> None:
        super().__init__(f"Flow '{flow_name}' not found in any registered project.")
        self.flow_name = flow_name
