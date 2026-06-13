"""
Stepyard core domain models.

Centralises all value objects, enums, and dataclasses that are shared
across the engine, scheduler, and storage layers.  No I/O or side-effects.
"""

from __future__ import annotations

from enum import Enum

# ─── State Enums ──────────────────────────────────────────────────────────────


class RunStatus(str, Enum):
    """Persistent run state machine values.

    Transitions:
        queued → running → waiting_for_approval → completed | failed | cancelled
    """

    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    WAITING_FOR_INPUT = "waiting_for_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        )

    @property
    def is_suspended(self) -> bool:
        """True for statuses that mean the run is paused for human interaction."""
        return self in (RunStatus.WAITING_FOR_APPROVAL, RunStatus.WAITING_FOR_INPUT)

    @property
    def is_active(self) -> bool:
        return self in (
            RunStatus.RUNNING,
            RunStatus.QUEUED,
            RunStatus.WAITING_FOR_APPROVAL,
            RunStatus.WAITING_FOR_INPUT,
        )

    @classmethod
    def suspended_values(cls) -> frozenset[str]:
        """Return suspended status string values for use in SQL/dict comparisons."""
        return frozenset(s.value for s in cls if s.is_suspended)


class StepStatus(str, Enum):
    """Persistent step state machine values.

    Transitions:
        pending → running → retrying → completed | failed | skipped | cancelled
    """

    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
            StepStatus.CANCELLED,
        )


class TriggerType(str, Enum):
    """Known trigger sources."""

    MANUAL = "manual"
    CRON = "cron"
    INTERVAL = "interval"
    STARTUP = "startup"
    REPLAY = "replay"
    WEBHOOK = "webhook"
