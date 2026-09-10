"""每周小结 + 趋势分析（周五 15:30）。

流程：落本周快照（kind=weekly）→ 与上一份快照环比 → 部门/物料/预警变化 → AI 小结。
发送到群聊由 env SAFETY_CHEMICAL_INVENTORY_WEEKLY_CHAT_ID 控制（未配置则仅落快照/日志，不发送）。
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit.context import ai_audit_scope
from app.modules.safety.chemical_inventory.snapshots import (
    KIND_WEEKLY,
    prev_snapshot_date,
    snapshot_rows_for_date,
    take_snapshot,
)
from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import ChemicalInventorySnapshot

logger = logging.getLogger(__name__)


def _key(r: Any) -> str:
    return f"{r.department}|{r.storage_location or ''}|{r.material_name}"


async def build_weekly_report(db: AsyncSession, snapshot_date: date) -> dict[str, Any]:
    """环比上一份快照，产出部门/物料/预警变化 + Top 增减。"""
    cur_count = await take_snapshot(db, snapshot_date, kind=KIND_WEEKLY)
    prev_date = await prev_snapshot_date(db, snapshot_date, kind=KIND_WEEKLY)
    if prev_date is None:
        return {"snapshot_date": snapshot_date.isoformat(), "records": cur_count, "first": True}

    prev_rows = {
        _key(r): r for r in await snapshot_rows_for_date(db, prev_date, kind=KIND_WEEKLY)
    }
    cur_rows = await snapshot_rows_for_date(db, snapshot_date, kind=KIND_WEEKLY)

    dept_delta: dict[str, Decimal] = {}
    material_delta: list[tuple[str, str, Decimal]] = []
    new_materials: list[tuple[str, str]] = []
    for r in cur_rows:
        key = _key(r)
        prev = prev_rows.get(key)
        prev_total = prev.total_quantity_t if (prev and prev.total_quantity_t is not None) else Decimal("0")
        cur_total = r.total_quantity_t or Decimal("0")
        delta = cur_total - prev_total
        dept_delta[r.department] = dept_delta.get(r.department, Decimal("0")) + delta
        if delta != 0:
            material_delta.append((r.department, r.material_name, delta))
        if key not in prev_rows:
            new_materials.append((r.department, r.material_name))

    material_delta.sort(key=lambda x: x[2])
    warn_now = sum(1 for r in cur_rows if r.risk_flag == "warn")
    warn_prev = sum(1 for r in prev_rows.values() if r.risk_flag == "warn")

    return {
        "snapshot_date": snapshot_date.isoformat(),
        "prev_date": prev_date.isoformat(),
        "records": cur_count,
        "first": False,
        "dept_delta": {k: float(v) for k, v in sorted(dept_delta.items(), key=lambda x: -x[1])},
        "top_increase": [{"department": d, "material": m, "delta": float(v)} for d, m, v in material_delta[-10:][::-1]],
        "top_decrease": [{"department": d, "material": m, "delta": float(v)} for d, m, v in material_delta[:10]],
        "new_materials": new_materials[:20],
        "warn_now": warn_now,
        "warn_prev": warn_prev,
    }


async def generate_ai_summary(report: dict[str, Any]) -> str:
    """AI 生成一段趋势小结文字。"""
    if not os.getenv("SAFETY_AI_TEXT_API_KEY"):
        return ""
    try:
        import json as _json

        from app.modules.safety.service.config import create_ai_service

        ai = create_ai_service("text")
        ctx = _json.dumps(report, ensure_ascii=False)
        try:
            with ai_audit_scope(scenario="chemical_inventory_weekly_report", channel="system"):
                return cast(str, await ai.chat(
                    messages=[
                        {"role": "system", "content": "你是危化品库存分析助手，根据周环比数据用简洁中文总结存量变化趋势与风险关注点。必须以部门名/物料名+数量给出至少 2 条具体变化（如'XX部门新增XX物料 N 吨'），150 字内，不输出空话。示例：'提取一部新增甲醇 5 吨，总库存上升至 12 吨；仓储二部乙腈减少 3 吨。'"},
                        {"role": "user", "content": f"周环比数据：{ctx}"},
                    ],
                    response_format="",
                    temperature=0.3,
                ))
        finally:
            await ai.close()
    except Exception:  # noqa: BLE001
        logger.exception("周报 AI 小结生成失败")
        return ""


def _format_report(report: dict[str, Any], ai_summary: str) -> str:
    """周报 Markdown。"""
    lines = [f"📅 {report.get('snapshot_date')}"]
    if report.get("first"):
        lines.append("首次快照，暂无环比；下周起输出趋势。")
        return "\n".join(lines)
    lines.append(f"环比 {report.get('prev_date')}：")
    lines.append("")
    lines.append("**部门总量变化（T）**")
    for dept, v in report.get("dept_delta", {}).items():
        sign = "+" if v >= 0 else ""
        lines.append(f"· {dept}: {sign}{v}")
    lines.append("")
    lines.append(f"**预警**：{report.get('warn_prev')} → {report.get('warn_now')}")
    if report.get("top_increase"):
        lines.append("")
        lines.append("**涨幅 Top**")
        for it in report["top_increase"]:
            lines.append(f"· {it['material']}（{it['department']}）：+{it['delta']} T")
    if report.get("top_decrease"):
        lines.append("")
        lines.append("**降幅 Top**")
        for it in report["top_decrease"]:
            lines.append(f"· {it['material']}（{it['department']}）：{it['delta']} T")
    if report.get("new_materials"):
        lines.append("")
        lines.append("**新增物料**")
        for dept, mat in report["new_materials"]:
            lines.append(f"· {mat}（{dept}）")
    if ai_summary:
        lines.append("")
        lines.append(f"**趋势小结**：{ai_summary}")
    return "\n".join(lines)


async def run_weekly_job(chat_id: str | None = None) -> dict[str, Any]:
    """周五 15:30：落快照 + 环比 + AI 小结；仅当配置了群聊才发送。

    chat_id 由调度器配置传入；为 None 时回退环境变量。
    """
    from app.core.database import async_session_factory

    today = (datetime.now(UTC) + timedelta(hours=8)).date()  # 北京时间今天
    async with async_session_factory() as db:
        report = await build_weekly_report(db, today)
        ai_summary = await generate_ai_summary(report)
        report["ai_summary"] = ai_summary
        await db.commit()

    content = _format_report(report, ai_summary)
    # 发送目标唯一来源：调度器配置（DB 播种/覆写），不再回退 env
    effective_chat_id = chat_id
    if effective_chat_id:
        await send_group_card(chat_id=effective_chat_id, title="危化品库存周报", content=content, header_template="blue")
    else:
        logger.info("周报未发送（未配置群聊）：%s", content)
    return report
