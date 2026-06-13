"""Custom triggers for the example plugin.

A trigger function can return EITHER:

1. An APScheduler trigger object (``CronTrigger``, ``IntervalTrigger``,
   ``DateTrigger``) - for time-based schedules; or
2. An ``async`` generator that ``yield``s payload dicts - for event-driven
   flows. Each yielded dict becomes ``${{ trigger.payload }}`` in the run.

Triggers only fire while the scheduler daemon is running (`stepyard service start`).
"""

from __future__ import annotations

import asyncio
import os
from datetime import timezone

from apscheduler.triggers.cron import CronTrigger

from stepyard.sdk import trigger


@trigger(name="schedule.weekdays")
def weekdays(at: str = "09:00") -> CronTrigger:
    """Fire on weekday mornings at ``at`` (HH:MM, UTC). Example of a schedule trigger."""
    hour, _, minute = at.partition(":")
    return CronTrigger(
        day_of_week="mon-fri",
        hour=int(hour),
        minute=int(minute or 0),
        timezone=timezone.utc,
    )


@trigger(name="watch.file")
async def watch_file(path: str, interval: int = 5):
    """Fire whenever a file's modification time changes. Example of an event trigger.

    Args:
        path: File to watch.
        interval: Poll interval in seconds.

    Yields a payload with the file path and its new mtime.
    """
    last_mtime: float | None = None
    while True:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None

        if mtime is not None and mtime != last_mtime:
            if last_mtime is not None:  # skip the very first observation
                yield {"path": path, "mtime": mtime}
            last_mtime = mtime

        await asyncio.sleep(interval)


__all__ = ["watch_file", "weekdays"]
