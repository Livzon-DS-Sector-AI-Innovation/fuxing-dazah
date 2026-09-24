# -*- coding: utf-8 -*-
"""调查 09-22 特殊作业日报条数差异（8点日报 34 vs 表格 31）。只读，不推送、不回写。

1) 现在直读今天（北京时间日窗口）的全部记录，逐条列出关键字段；
2) 读安全速递总卡里 8 点投递的 special_op 格子快照（stats + markdown 全文），
   对比两份明细找出差异记录。
"""
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


async def main() -> None:
    from app.modules.safety.service.special_op_direct import config
    from app.modules.safety.service.special_op_direct.bitable_repo import fetch_day_views

    print("直读总开关 direct_enabled:", config.direct_enabled())
    print("旧同步任务闸门 legacy_sync_job_active:", config.legacy_sync_job_active())

    views = await fetch_day_views(TARGET)
    print(f"\n=== 现在直读 {TARGET} 窗口: {len(views)} 条 ===")
    excluded = 0
    for v in sorted(views, key=lambda x: (x.created_at, x.record_id)):
        if v.is_excluded:
            excluded += 1
        flag = "EXCL" if v.is_excluded else "    "
        print(
            f"{flag} rid={v.record_id} created={v.created_at.isoformat()} "
            f"start={(v.planned_start_time.isoformat() if v.planned_start_time else '?')} "
            f"type={v.operation_type}/{v.operation_level} rt={v.report_type} "
            f"risk={v.daily_risk_level} excl_reason={v.exclusion_reason or '-'} "
            f"desc={(v.work_description or '')[:50]}"
        )
    print(f"合计 total={len(views)} excluded={excluded} effective={len(views) - excluded}")

    from app.core.redis import get_redis

    store = await get_redis()
    raw = await store.hget(f"safety:daily_digest:{TARGET.isoformat()}", "special_op")
    if raw is None:
        print("\n速递总卡无 special_op 格子；已有格子：", await store.hkeys(
            f"safety:daily_digest:{TARGET.isoformat()}"
        ))
        return
    cell = json.loads(raw)
    print("\n=== 8点日报投递的速递总卡 special_op 格子 ===")
    print("title:", cell.get("title"))
    print("stats:", cell.get("stats"))
    print("zone:", cell.get("zone"))
    print("--- detail（markdown 全文） ---")
    print(cell.get("detail", ""))


asyncio.run(main())
