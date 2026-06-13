from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from stepyard.sdk.trigger import trigger


@trigger(name="cron")
def cron_trigger(schedule: str | None = None, expression: str | None = None) -> CronTrigger:
    """Executes flows on a traditional cron schedule.

    Args:
        schedule: The cron string (e.g., '0 * * * *').
        expression: Alias for schedule.

    Outputs:
        Returns an APScheduler CronTrigger.
    """
    cron_expression = schedule or expression
    if not cron_expression:
        raise ValueError("cron trigger requires 'schedule' or 'expression'.")
    return CronTrigger.from_crontab(cron_expression, timezone=timezone.utc)


@trigger(name="interval")
def interval_trigger(seconds: int) -> IntervalTrigger:
    """Fires repeatedly at a fixed interval of seconds.

    Args:
        seconds: The interval length in seconds.

    Outputs:
        Returns an APScheduler IntervalTrigger.
    """
    return IntervalTrigger(seconds=seconds, timezone=timezone.utc)


@trigger(name="startup")
def startup_trigger() -> DateTrigger:
    """Executes the flow once immediately when the scheduler starts.

    Outputs:
        Returns an APScheduler DateTrigger.
    """
    return DateTrigger(run_date=datetime.now(timezone.utc))


__all__ = ["cron_trigger", "interval_trigger", "startup_trigger"]
