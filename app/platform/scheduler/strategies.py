"""Pure functions for schedule strategy computation.

No side effects, no async, no DB access — just datetime arithmetic
and cron-expression evaluation.
"""

from __future__ import annotations

from datetime import datetime, time

from croniter import croniter  # type: ignore[import-untyped]

from app.platform.scheduler.registry import ScheduleConfig, ScheduleStrategy


def is_due(
    schedule: ScheduleConfig,
    last_run: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Return True if *schedule* has fired since *last_run*.

    Args:
        schedule: Scheduling parameters.
        last_run: The last time the task was attempted (or None for first run).
        now: Current time; defaults to ``datetime.now()`` in the local timezone.
    """
    if now is None:
        now = datetime.now().astimezone()

    match schedule.strategy:
        case ScheduleStrategy.CRON:
            return _is_cron_due(schedule.expression, last_run, now)
        case ScheduleStrategy.INTERVAL:
            return _is_interval_due(last_run, schedule.interval_seconds, now)
        case ScheduleStrategy.FIXED_TIME:
            return _is_fixed_time_due(schedule.time_of_day, last_run, now)

# ── strategy helpers ──────────────────────────────────────────────


def _is_cron_due(
    expression: str,
    last_run: datetime | None,
    now: datetime,
) -> bool:
    """True when *expression* has fired at least once since *last_run*.

    croniter operates on naive datetimes, so we strip the timezone
    from *last_run* and re-attach it to the computed next-fire time.
    This mirrors the pattern in ``app/modules/safety/scheduler.py``.
    """
    if not expression:
        return False
    if last_run is None:
        return True

    naive_last = last_run.replace(tzinfo=None)
    cron = croniter(expression, naive_last)
    next_fire_naive: datetime = cron.get_next(datetime)
    next_fire = next_fire_naive.replace(tzinfo=last_run.tzinfo)

    result: bool = now >= next_fire
    return result


def _is_interval_due(
    last_run: datetime | None,
    interval_seconds: int,
    now: datetime,
) -> bool:
    """True when *interval_seconds* have elapsed since *last_run*."""
    if last_run is None:
        return True
    return (now - last_run).total_seconds() >= interval_seconds


def _is_fixed_time_due(
    time_of_day: str,
    last_run: datetime | None,
    now: datetime,
) -> bool:
    """True when the daily *time_of_day* (``"HH:MM"``) has passed since *last_run*.

    Handles the common edge case where the target time falls between
    *last_run* and *now* on the same calendar day.
    """
    if not time_of_day:
        return False
    if last_run is None:
        return _time_parts(time_of_day) <= now.time()

    target = _time_parts(time_of_day)

    # Same day: check if target is between last_run and now
    if last_run.date() == now.date():
        return last_run.time() < target <= now.time()

    # Different day: target must have occurred at a boundary
    target_dt = datetime.combine(now.date(), target, tzinfo=now.tzinfo)
    return last_run < target_dt <= now


def _time_parts(time_of_day: str) -> time:
    """Parse ``"HH:MM"`` into a :class:`datetime.time`."""
    h, m = time_of_day.split(":")
    return time(int(h), int(m))
