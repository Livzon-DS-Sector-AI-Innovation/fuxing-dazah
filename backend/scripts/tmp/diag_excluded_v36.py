# -*- coding: utf-8 -*-
"""诊断：今日直读 views 中 is_excluded=True 的记录来源。"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


async def main() -> None:
    from app.modules.safety.service.special_op_direct.bitable_repo import (
        fetch_day_views,
    )

    views = await fetch_day_views(TARGET)
    print("总条数:", len(views))
    for v in views:
        if v.is_excluded:
            print("---- 被排除 ----")
            print("record_id:", v.record_id)
            print("部门:", v.department, "| 地点:", v.location)
            print("内容:", (v.work_description or "")[:60])
            print("exclusion_reason:", v.exclusion_reason)
            print("daily_risk_level:", v.daily_risk_level)
    excluded = [v for v in views if v.is_excluded]
    print("排除总数:", len(excluded))


asyncio.run(main())
