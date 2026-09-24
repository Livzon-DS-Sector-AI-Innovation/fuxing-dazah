# -*- coding: utf-8 -*-
"""检查今日直读记录中是否有涉及「水热矿化」的作业（决定是否需要重刷今日日报）。"""
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
    hits = [
        v for v in views
        if "水热矿化" in (v.location or "") + (v.work_description or "")
    ]
    print("今日总条数:", len(views), "| 涉「水热矿化」:", len(hits))
    for v in hits:
        print(f"- {v.department} | {v.operation_type} | {v.location} :: "
              f"{(v.work_description or '')[:50]} | 现判定={v.daily_risk_level}")


asyncio.run(main())
