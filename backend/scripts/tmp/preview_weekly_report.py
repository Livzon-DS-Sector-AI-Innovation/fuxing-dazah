# -*- coding: utf-8 -*-
"""生成上周自然周（2026-09-14 ~ 2026-09-20）消防报警周报预览。

push=False：只生成 markdown，不推飞书群（对话预览用）。
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


async def main() -> None:
    from app.core.database import async_session_factory
    from app.modules.safety.service.fire_alarm.service import FireAlarmService

    async with async_session_factory() as session:
        service = FireAlarmService(session)
        result = await service.generate_weekly_report(
            week_end=date(2026, 9, 20), push=False, channel="system",
        )
        await session.commit()
        print("=== META ===")
        print("week_start:", result.week_start)
        print("week_end:", result.target_date)
        print("total:", result.total)
        print("push_results:", result.push_results)
        print("=== MARKDOWN ===")
        print(result.markdown_report)


asyncio.run(main())
