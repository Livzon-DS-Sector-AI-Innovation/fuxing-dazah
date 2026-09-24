# -*- coding: utf-8 -*-
"""统计 09-22 直读 34 条的「申请状态」分布。只读。"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


async def main() -> None:
    from app.modules.safety.service.special_op_direct.bitable_repo import fetch_day_views

    views = await fetch_day_views(TARGET)
    dist: dict[str, int] = {}
    withdrawn = []
    for v in views:
        raw = (v.raw or {}).get("申请状态")
        val = raw if isinstance(raw, str) else str(raw or "<空>")
        dist[val] = dist.get(val, 0) + 1
        if "撤回" in val:
            withdrawn.append((v.record_id, (v.work_description or "")[:20]))
    print("申请状态分布:", dist)
    print("已撤回票:", withdrawn)
    print("total:", len(views), "非撤回:", len(views) - len(withdrawn))


asyncio.run(main())
