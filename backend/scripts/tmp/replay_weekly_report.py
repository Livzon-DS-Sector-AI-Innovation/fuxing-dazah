# -*- coding: utf-8 -*-
"""真机补发本周一应发的消防报警周报（上一自然周 9-14~9-20）到安全速递总卡。

成功后写 scheduler_job_runs(fired_date=今天, success)，
防止调度器今天 17:00 到点重复触发。
"""
import asyncio
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main() -> None:
    from sqlalchemy.dialects.postgresql import insert

    from app.core.database import async_session_factory
    from app.modules.safety.models import SchedulerJobRun
    from app.modules.safety.scheduler import _run_fire_alarm_weekly_report

    today = date.today()
    week_end = today - timedelta(days=1)
    print(f"补发周报: week_end={week_end} (自然周 {week_end - timedelta(days=6)}~{week_end})")

    await _run_fire_alarm_weekly_report()

    async with async_session_factory() as session:
        values = {
            "job_name": "消防报警周报",
            "fired_date": today,
            "status": "success",
            "last_attempt_at": datetime.now(UTC),
            "attempt_count": 0,
            "alerted": False,
        }
        stmt = insert(SchedulerJobRun).values(**values).on_conflict_do_update(
            index_elements=["job_name"], set_=values,
        )
        await session.execute(stmt)
        await session.commit()
    print(f"已标记今日({today})调度成功，17:00 不会重复触发")


asyncio.run(main())
