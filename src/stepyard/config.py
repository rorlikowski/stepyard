"""
Stepyard runtime configuration.

All tuneable constants live here.  Each value can be overridden through an
environment variable so that deployments don't need to patch source code.

Usage::

    from stepyard.config import settings

    settings.max_concurrent_flows   # int
    settings.executor_tick_interval  # float
    settings.scheduler_tick_interval  # float
    settings.max_step_visits          # int
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class StepyardSettings:
    """Immutable settings resolved once at import time."""

    #: Maximum number of flow subprocesses that may run concurrently.
    max_concurrent_flows: int

    #: How often the executor worker polls the queue (seconds).
    executor_tick_interval: float

    #: How long the scheduler daemon sleeps between housekeeping loops (seconds).
    scheduler_tick_interval: float

    #: Default upper limit on per-step visit counts.
    max_step_visits: int

    @classmethod
    def from_env(cls) -> StepyardSettings:
        return cls(
            max_concurrent_flows=int(os.environ.get("STEPYARD_MAX_CONCURRENT_FLOWS", "4")),
            executor_tick_interval=float(os.environ.get("STEPYARD_EXECUTOR_TICK", "2")),
            scheduler_tick_interval=float(os.environ.get("STEPYARD_SCHEDULER_TICK", "5")),
            max_step_visits=int(os.environ.get("STEPYARD_MAX_STEP_VISITS", "1000")),
        )


#: Module-level singleton - import and use directly.
settings = StepyardSettings.from_env()
