# -*- coding: utf-8 -*-
"""复核 09-22 直读 34 条中的疑似重复票：按 desc+审批编号+时间分组对比。只读。"""
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
    print(f"total={len(views)}")
    for v in sorted(views, key=lambda x: (x.work_description or "", x.record_id)):
        print(
            f"desc={(v.work_description or '')[:30]!r:32} no={v.approval_no!r:14} "
            f"dept={v.department!r:12} loc={(v.location or '')[:16]!r:18} "
            f"start={(v.planned_start_time.isoformat()[5:16] if v.planned_start_time else '?')} "
            f"created={v.created_at.isoformat()[:16]} rt={v.report_type} rid={v.record_id}"
        )


asyncio.run(main())
