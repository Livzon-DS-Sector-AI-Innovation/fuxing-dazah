# -*- coding: utf-8 -*-
"""① 新规则等级回写「日报风险等级（AI）」列；② 速递总卡双格子：

- 「special_op」原位恢复旧规则版（V3.6 关键词清空后按当前数据重建，含 AI 增强；
  今晨原版内容已被上次覆盖且无处可恢复，此为同口径重建）
- 「special_op_v36」新增格子放最新新规则版（不覆盖原格子；CELL_ORDER 已加槽位）

回写沿用管道口径：撤回票自动跳过（列值保留不动），串行 0.5s 间隔。
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

TARGET = date(2026, 9, 22)


async def build_cell(views, title: str):
    """按 daily.run 同口径构建一个速递格子（含 AI 增强）。"""
    from app.modules.safety.service.special_operation_daily_report import (
        AIAnalyst,
        ReportBuilder,
    )

    effective = [v for v in views if not v.is_excluded]
    excluded_count = len(views) - len(effective)
    high = [v for v in effective if v.daily_risk_level == "high"]
    medium = [v for v in effective if v.daily_risk_level == "medium"]
    low = [v for v in effective if v.daily_risk_level == "low"]
    stats = {
        "total": len(views), "effective_total": len(effective),
        "high": len(high), "medium": len(medium), "low": len(low),
        "excluded": excluded_count,
    }

    ai = None
    if high:
        ai = await AIAnalyst(session=None).analyze(
            report_date=TARGET, mode="today", reports=effective, stats=stats,
        )
    markdown = ReportBuilder.build(
        TARGET, "today", effective, stats, ai_analysis=ai,
    )
    zone = (ReportBuilder._build_zone_summary(high, medium, "今日") or "")[:80]

    from app.modules.safety.feishu.daily_digest import DigestCell

    cell = DigestCell(
        tag_color="blue", tag_text="特殊作业", title=title,
        stats=(
            f"今日计划 **{len(effective)}** 项 ｜ "
            f"🔴 高风险 **{len(high)}** · 🟡 中 {len(medium)}"
            f" · 🟢 低 {len(low)}"
        ),
        zone=zone, detail=markdown,
    )
    return cell, stats


async def main() -> None:
    import time

    from app.modules.safety.feishu.daily_digest import upsert_daily_digest
    from app.modules.safety.service import special_operation_daily_report as eng
    from app.modules.safety.service.special_op_direct.bitable_repo import (
        fetch_day_views,
        writeback_risk_levels,
    )

    t0 = time.monotonic()

    # ── ① 回写「日报风险等级（AI）」列（新规则等级） ──
    views_new = await fetch_day_views(TARGET)
    wb = await writeback_risk_levels(views_new)
    print(
        f"[{time.monotonic() - t0:6.1f}s] 回写列: attempted={wb.attempted} "
        f"written={wb.written} skipped={wb.skipped} failed={len(wb.failed)}"
    )
    if wb.failed:
        print("  回写失败 record_ids:", wb.failed[:10])

    # ── ②a 新增格子：新规则版 ──
    cell_new, st_new = await build_cell(views_new, "特殊作业日报（新规则重算）")
    print(
        f"[{time.monotonic() - t0:6.1f}s] 新规则格子构建完成: "
        f"有效={st_new['effective_total']} 高={st_new['high']} "
        f"中={st_new['medium']} 低={st_new['low']} 排除={st_new['excluded']}"
    )

    # ── ②b 原格子：清空 V3.6 关键词后按旧规则重建 ──
    saved_zone = eng.HOT_WORK_HIGH_RISK_ZONE_KEYWORDS[:]
    saved_line = eng.CORROSIVE_LINE_KEYWORDS
    saved_sub = eng.CORROSIVE_SUBSTANCES
    try:
        eng.HOT_WORK_HIGH_RISK_ZONE_KEYWORDS.clear()
        eng.CORROSIVE_LINE_KEYWORDS = ()
        eng.CORROSIVE_SUBSTANCES = ()
        views_old = await fetch_day_views(TARGET)
    finally:
        eng.HOT_WORK_HIGH_RISK_ZONE_KEYWORDS[:] = saved_zone
        eng.CORROSIVE_LINE_KEYWORDS = saved_line
        eng.CORROSIVE_SUBSTANCES = saved_sub
    cell_old, st_old = await build_cell(views_old, "特殊作业日报")
    print(
        f"[{time.monotonic() - t0:6.1f}s] 旧规则格子构建完成: "
        f"有效={st_old['effective_total']} 高={st_old['high']} "
        f"中={st_old['medium']} 低={st_old['low']} 排除={st_old['excluded']}"
    )

    # ── ③ 上卡：先恢复原格子，再追加新格子 ──
    ok_old = await upsert_daily_digest(TARGET, "special_op", cell_old)
    print(f"[{time.monotonic() - t0:6.1f}s] 原格子(special_op)上卡: {ok_old}")
    ok_new = await upsert_daily_digest(TARGET, "special_op_v36", cell_new)
    print(f"[{time.monotonic() - t0:6.1f}s] 新格子(special_op_v36)上卡: {ok_new}")

    # ── ④ 回读验证 ──
    import json

    from app.core.redis import get_redis

    store = await get_redis()
    key = f"safety:daily_digest:{TARGET.isoformat()}"
    print("=== 回读验证 ===")
    print("格子 keys:", sorted(await store.hkeys(key)))
    for field in ("special_op", "special_op_v36"):
        raw = await store.hget(key, field)
        if raw is None:
            print(f"[{field}] 缺失!")
            continue
        cell = json.loads(raw)
        print(f"[{field}] title={cell.get('title')} | stats={cell.get('stats')}")
        print(f"[{field}] zone={cell.get('zone', '')[:60]}")
        print(f"[{field}] detail 长度={len(cell.get('detail', ''))}")
    msg_id = await store.get(f"safety:daily_digest:card:{TARGET.isoformat()}")
    print("总卡 message_id:", msg_id)


asyncio.run(main())
