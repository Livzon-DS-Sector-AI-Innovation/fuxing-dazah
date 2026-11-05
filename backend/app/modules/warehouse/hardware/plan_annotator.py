"""五金库月度采购计划 AI 用量注释（二期 M5，设计 §9.1 L4 决策辅助）。

输入=计划行近 3 个月月度用量序列（SQL 聚合，数字不经 LLM 之手），
输出=每行一句建议文本落 ``ai_note`` **建议态字段**——人审核采纳，
不自动改 purchase_qty（红线：AI 永不改数量）。

场景 ``hardware_plan_annotation``（scenario_registry 注册 + 迁移播种）；
停用/失败由 planning.annotate_plan_items 兜底（ai_note 留空不阻塞草案）。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.ai_audit.context import warehouse_audit_scope
from app.modules.warehouse.hardware.models import (
    HardwareMovement,
    HardwarePurchasePlan,
    HardwarePurchasePlanItem,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

PLAN_ANNOTATE_PROMPT = """你是五金仓库的采购助理。下面是月度采购计划草案中各物料的用量数据
（近 3 个月每月出库量，由系统流水聚合，数字不可更改）。请对每个物料给出一句
10-40 字的采购建议注释，指出消耗趋势（升/降/平稳）或异常波动（如有），供仓管员
审核计划时参考。严格输出 JSON（不要任何解释文字或代码块包裹）：

{"notes": [{"name": "物资名称（原样）", "note": "建议注释"}]}

数据：
{rows}"""


async def _monthly_usage_series(
    db: AsyncSession, material_ids: list[UUID], *, months: int = 3, now: datetime | None = None
) -> dict[UUID, list[float]]:
    """近 N 月逐月用量（自然月聚合；SQL 聚合，数字不经 LLM）。

    月表达式用 literal_column 内联（绑定参数形式的 to_char 格式串会使
    GROUP BY 与 SELECT 占位符不一致 → GroupingError，2026-11-05 实测）。
    """
    from sqlalchemy import literal_column

    now = now or datetime.now(CN_TZ)
    start = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    # 回退到 N 月前月初
    for _ in range(months - 1):
        start = start.replace(
            year=start.year - 1 if start.month == 1 else start.year,
            month=12 if start.month == 1 else start.month - 1,
        )
    month_expr = literal_column(
        "to_char(warehouse.hardware_movements.occurred_at, 'YYYY-MM')"
    )
    rows = (
        await db.execute(
            select(
                HardwareMovement.material_id,
                month_expr.label("month"),
                func.sum(HardwareMovement.quantity),
            )
            .where(
                HardwareMovement.material_id.in_(material_ids),
                HardwareMovement.direction == "outbound",
                HardwareMovement.business_type.in_(("req_issue", "urgent_issue")),
                HardwareMovement.occurred_at >= start,
                HardwareMovement.occurred_at <= now,
                HardwareMovement.is_deleted.is_(False),
            )
            .group_by(HardwareMovement.material_id, month_expr)
        )
    ).all()
    series: dict[UUID, list[tuple[str, float]]] = {mid: [] for mid in material_ids}
    for mid, month, qty in rows:
        series.setdefault(mid, []).append((str(month), float(qty or Decimal("0"))))
    # 排序成时间序列
    return {
        mid: [q for _, q in sorted(vals)] for mid, vals in series.items()
    }


def _assistant_text(message: Any) -> str | None:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "\n".join(p for p in parts if p) or None
    return None


async def annotate_items(db: AsyncSession, plan: HardwarePurchasePlan) -> int:
    """对计划行生成 ai_note（建议态）。返回注释行数；失败上抛由调用方兜底。"""
    from app.modules.warehouse.agent.llm_client import get_llm_client

    items = (
        await db.execute(
            select(HardwarePurchasePlanItem).where(
                HardwarePurchasePlanItem.purchase_plan_id == plan.id,
                HardwarePurchasePlanItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    # 只注释有采购意义的行（有用量或有采购量），减少无效 token
    targets = [
        i for i in items
        if (i.monthly_usage or 0) > 0 or (i.purchase_qty or 0) > 0
    ]
    if not targets:
        return 0

    series = await _monthly_usage_series(db, [i.material_id for i in targets])
    rows_text = "\n".join(
        f"- {i.name}：近3月用量={series.get(i.material_id) or []}，"
        f"本月建议采购={float(i.purchase_qty)}"
        for i in targets
    )

    async with warehouse_audit_scope(
        "hardware_plan_annotation",
        resource="plan_annotate",
        channel="system",
    ):
        client = get_llm_client()
        content = await client.chat_with_tools(
            [{"role": "user", "content": PLAN_ANNOTATE_PROMPT.format(rows=rows_text)}],
            tools=None,
            temperature=0.2,
            max_tokens=4096,
        )
    text = _assistant_text(content)
    notes = _parse_notes(text)

    matched = 0
    by_name = {i.name: i for i in targets}
    for entry in notes:
        item = by_name.get(str(entry.get("name") or ""))
        note = str(entry.get("note") or "").strip()[:500]
        if item is not None and note:
            item.ai_note = note
            matched += 1
    await db.flush()
    logger.info("五金计划 AI 注释完成: plan=%s 行=%d/%d", plan.plan_month, matched, len(targets))
    return matched


def _parse_notes(text: str | None) -> list[dict[str, Any]]:
    """宽松解析 JSON（剥代码块围栏；失败返回空列表）。"""
    if not text:
        return []
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("计划注释 JSON 解析失败（忽略，ai_note 留空）")
        return []
    notes = payload.get("notes") if isinstance(payload, dict) else None
    return [n for n in notes if isinstance(n, dict)] if isinstance(notes, list) else []
