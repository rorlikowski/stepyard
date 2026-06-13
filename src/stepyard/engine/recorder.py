"""
Stepyard StepRecorder - single responsible class for step-run persistence.

All writes to ``step_runs`` (create / update / fail / skip / suspend) go
through this class so the logic is never duplicated across the engine.

Secret redaction
----------------
The recorder automatically masks the value of any input key whose name
contains a known secret keyword (see :data:`_SECRET_KEY_PATTERNS`).
This prevents API keys and passwords from appearing in the ``step_runs``
table.  To opt individual inputs into redaction from a node, use the
``ctx.mark_secret(key)`` API (future).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from stepyard.core.models import RunStatus
from stepyard.core.ports import RunStorePort

logger = logging.getLogger("stepyard.engine.recorder")

# Keys whose values are redacted before persistence.
_SECRET_KEY_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
)

_REDACTED = "***"


def _redact_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *inputs* with sensitive values replaced by ``***``."""
    redacted: dict[str, Any] = {}
    for key, value in inputs.items():
        if any(pat.search(key) for pat in _SECRET_KEY_PATTERNS):
            redacted[key] = _REDACTED
        else:
            redacted[key] = value
    return redacted


class StepRecorder:
    """Writes step-run state transitions to storage.

    Parameters
    ----------
    store:
        Any object that satisfies :class:`~stepyard.core.ports.RunStorePort`.
        In production this is :class:`~stepyard.storage.facade.Storage`.
    """

    def __init__(self, store: RunStorePort) -> None:
        self._store = store

    # ── Lifecycle transitions ─────────────────────────────────────────────────

    def start(
        self,
        run_id: str,
        step_id: str,
        *,
        status: str = "running",
        attempt: int = 1,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        """Create a new step-run record (or upsert if already exists).

        Sensitive input values (API keys, passwords, tokens) are redacted
        before persistence.
        """
        safe_inputs = _redact_inputs(inputs) if inputs else {}
        self._store.create_step_run(
            run_id,
            step_id,
            status=status,
            attempt=attempt,
            inputs=safe_inputs,
        )

    def complete(
        self,
        run_id: str,
        step_id: str,
        *,
        output: Any = None,
    ) -> None:
        """Mark a step as completed."""
        self._store.update_step_run(run_id, step_id, status="completed", output=output)

    def fail(
        self,
        run_id: str,
        step_id: str,
        *,
        error: str | None = None,
        output: Any = None,
    ) -> None:
        """Mark a step as failed."""
        self._store.update_step_run(run_id, step_id, status="failed", error=error, output=output)

    def skip(self, run_id: str, step_id: str) -> None:
        """Mark a step as skipped."""
        self._store.create_step_run(run_id, step_id, status="skipped")
        self._store.update_step_run(run_id, step_id, status="skipped")

    def suspend(
        self,
        run_id: str,
        step_id: str,
        *,
        resolved_inputs: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
    ) -> None:
        """Persist a suspension checkpoint and update the run status."""
        state = state or {}
        reason = state.get("reason", "unknown")
        logger.info("Step '%s' suspended. Reason: %s", step_id, reason)

        self._store.create_step_run(run_id, step_id, status="pending", inputs=resolved_inputs or {})

        run_status = (
            RunStatus.WAITING_FOR_INPUT.value
            if reason == "input_required"
            else RunStatus.WAITING_FOR_APPROVAL.value
        )
        self._store.update_run_status(run_id, run_status)
        self._store.write_audit_log(
            action="execution_suspended",
            actor="engine",
            target=f"{run_id}/{step_id}",
            details=reason,
        )
