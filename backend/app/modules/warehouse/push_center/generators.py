"""推送内容生成器：scene -> 飞书卡片 dict（JSON 2.0）。

生成器协议：``async (db, now_cn) -> card dict``；事件型生成器（快递通知）
由事件入口另行传 payload 调用（Ticket 08 接入，届时扩展协议）。
内容只复用既有聚合（spec 决策）：晨报/周报/月报纯模板数据卡；
清单卡附 LLM 解读（白名单+降级模板，宁夏模式，复用 intelligence 的
LLM 客户端与降级口径）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.cards import build_card
from app.modules.warehouse.agent.tools.query import query_report
from app.modules.warehouse.intelligence import (
    _llm_summarize,  # noqa: SLF001 — 同包内部复用（宁夏模式同款）
)
from app.modules.warehouse.models import WarehouseMovement, WarehouseStock
from app.modules.warehouse.morning_report import generate_morning_report
from app.modules.warehouse.reports import get_monthly_report

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

PushGenerator = Callable[[AsyncSession, datetime], Awaitable[dict[str, Any]]]

# scene -> 生成器（模块导入时注册；测试可整体替换）
GENERATORS: dict[str, PushGenerator] = {}


def register_push_generator(scene: str, generator: PushGenerator) -> None:
    """注册内容生成器；重复注册抛错（防启动期静默覆盖）。"""
    if scene in GENERATORS:
        raise ValueError(f"推送内容生成器重复注册: {scene}")
    GENERATORS[scene] = generator


def get_push_generator(scene: str) -> PushGenerator | None:
    """取生成器；未注册返回 None（引擎记失败日志并告警）。"""
    return GENERATORS.get(scene)


def _md(text: str) -> dict[str, Any]:
    return {"tag": "markdown", "content": text}


def fmt_qty(value: Any) -> str:
    """数量展示：去尾零（12.0 -> 12，340.50 -> 340.5）。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


async def _generate_morning(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """晨报卡：复用既有聚合同日幂等落库，纯模板数据卡（窄屏排版）。"""
    content = await generate_morning_report(db, now_cn.date())
    yesterday = content["yesterday"]
    alerts = content["alerts"]
    elements: list[dict[str, Any]] = [
        _md(
            f"**昨日入库** {yesterday['inbound_count']} 笔 / {fmt_qty(yesterday['inbound_qty'])}"
            f"　**出库** {yesterday['outbound_count']} 笔 / {fmt_qty(yesterday['outbound_qty'])}"
        ),
        _md(
            f"**未处理异常** {alerts['open_total']} 项"
            f"　**待处理补货建议** {content['pending_suggestions']} 项"
        ),
    ]

    low = content["low_stock_top5"]
    if low:
        lines = "\n".join(
            f"{i}. {item['material_name']}（库存 {fmt_qty(item['total_quantity'])} / 安全 {fmt_qty(item['safety_stock'])}）"
            for i, item in enumerate(low, start=1)
        )
        elements.append(_md(f"**低库存 Top{len(low)}**\n{lines}"))

    expiring = content["expiring_top5"]
    if expiring:
        lines = "\n".join(
            f"{i}. {item['material_name']} 批 {item['batch_no'] or '-'}（剩 {item['days_left']} 天，{fmt_qty(item['quantity'])}）"
            for i, item in enumerate(expiring, start=1)
        )
        elements.append(_md(f"**临期 Top{len(expiring)}**\n{lines}"))

    return build_card(
        title=f"仓储晨报 · {content['brief_date']}",
        template="blue",
        elements=elements,
    )


async def _generate_weekly(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """周库存报表卡：近 7 天出入库聚合 + 当前库存概况（本地库，纯模板）。"""
    window_start = datetime.combine(
        now_cn.date() - timedelta(days=7), dtime(0, 0), tzinfo=CN_TZ
    )
    window_end = datetime.combine(now_cn.date(), dtime(0, 0), tzinfo=CN_TZ)

    movements = list(
        (
            await db.execute(
                select(WarehouseMovement).where(
                    WarehouseMovement.is_deleted == False,  # noqa: E712
                    WarehouseMovement.occurred_at >= window_start,
                    WarehouseMovement.occurred_at < window_end,
                )
            )
        ).scalars().all()
    )
    inbound = [m for m in movements if m.direction == "inbound"]
    outbound = [m for m in movements if m.direction == "outbound"]
    inbound_qty = sum(float(m.quantity) for m in inbound)
    outbound_qty = sum(float(m.quantity) for m in outbound)

    stocks = list(
        (
            await db.execute(
                select(WarehouseStock).where(
                    WarehouseStock.is_deleted == False,  # noqa: E712
                    WarehouseStock.quantity > 0,
                )
            )
        ).scalars().all()
    )
    material_count = len({s.material_id for s in stocks})
    total_qty = sum(float(s.quantity) for s in stocks)
    quarantined = sum(1 for s in stocks if s.status == "quarantine")
    frozen = sum(1 for s in stocks if s.status == "frozen")

    # 呆滞/不合格计数（Base 台账口径，与清单推送同源；拉取失败置 0 不阻断周报）
    dead_total = unqualified_total = 0
    try:
        dead_total = int((await query_report("dead")).get("total") or 0)
        unqualified_total = int((await query_report("unqualified")).get("total") or 0)
    except Exception:  # noqa: BLE001 — Base 拉取失败不阻断周报
        logger.warning("周报呆滞/不合格计数拉取失败，置 0", exc_info=True)

    elements: list[dict[str, Any]] = [
        _md(
            f"**近 7 天入库** {len(inbound)} 笔 / {fmt_qty(inbound_qty)}"
            f"　**出库** {len(outbound)} 笔 / {fmt_qty(outbound_qty)}"
        ),
        _md(
            f"**库存概况** {material_count} 种物料 / {len(stocks)} 个批次"
            f" / 总量 {fmt_qty(total_qty)}"
            + (f"　**隔离 {quarantined} 批**" if quarantined else "")
            + (f"　**冻结 {frozen} 批**" if frozen else "")
        ),
        _md(
            f"**呆滞批次** {dead_total} 条"
            f"　**不合格物料** {unqualified_total} 条"
        ),
    ]
    return build_card(
        title=f"周库存报表 · {window_start.date().strftime('%m-%d')} ~ {window_end.date().strftime('%m-%d')}",
        template="blue",
        elements=elements,
    )


async def _generate_monthly(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """月报推送卡：复用既有月报聚合（上月口径），纯模板摘要。"""
    year, month = (now_cn.year, now_cn.month - 1) if now_cn.month > 1 else (now_cn.year - 1, 12)
    report = await get_monthly_report(db, year, month)
    summary = report["summary"]

    top = sorted(report["items"], key=lambda x: x["outbound_qty"], reverse=True)[:3]
    elements: list[dict[str, Any]] = [
        _md(
            f"**入库** {summary['inbound_count']} 笔 / {fmt_qty(summary['inbound_qty'])}"
            f"　**出库** {summary['outbound_count']} 笔 / {fmt_qty(summary['outbound_qty'])}"
            f"　**涉及物料** {len(report['items'])} 种"
        )
    ]
    if top:
        lines = "\n".join(
            f"{i}. {item['material_name']}（出库 {fmt_qty(item['outbound_qty'])} {item['unit'] or ''}）"
            for i, item in enumerate(top, start=1)
        )
        elements.append(_md(f"**出库 Top{len(top)}**\n{lines}"))
    else:
        elements.append(_md("本月无出入库记录"))

    return build_card(
        title=f"仓储月报 · {year}-{month:02d}",
        template="blue",
        elements=elements,
    )


def _stale_fallback_text(dead_total: int, unqualified_total: int) -> str:
    return (
        f"呆滞批次 {dead_total} 条、不合格物料 {unqualified_total} 条待处理，请尽快跟进。"
    )


async def _generate_stale_lists(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """超6月呆滞与不合格清单卡：复用 Agent 查询工具的清单聚合，附 LLM 解读。"""
    dead = await query_report("dead")
    unqualified = await query_report("unqualified")
    dead_total = int(dead.get("total") or 0)
    unqualified_total = int(unqualified.get("total") or 0)
    dead_records = dead.get("records") or []
    unqualified_records = unqualified.get("records") or []

    elements: list[dict[str, Any]] = []
    if dead_total == 0 and unqualified_total == 0:
        elements.append(_md("呆滞批次 0 条；不合格物料 0 条 — 无待处理项"))
        return build_card(
            title=f"呆滞与不合格清单 · {now_cn.date().isoformat()}",
            template="green",
            elements=elements,
        )

    if dead_records:
        lines = "\n".join(
            f"{i}. {r.get('物料名称', '-')} 批 {r.get('物料批号', '-')}"
            f"（{r.get('呆料产生数量（入库数量）', '-')}）"
            for i, r in enumerate(dead_records[:3], start=1)
        )
        elements.append(_md(f"**呆滞批次 {dead_total} 条**\n{lines}"))
    else:
        elements.append(_md(f"**呆滞批次 {dead_total} 条**"))

    if unqualified_records:
        lines = "\n".join(
            f"{i}. {r.get('物料名称', '-')}（{r.get('不合格项目') or '不合格'}）"
            for i, r in enumerate(unqualified_records[:3], start=1)
        )
        elements.append(_md(f"**不合格物料 {unqualified_total} 条**\n{lines}"))
    else:
        elements.append(_md(f"**不合格物料 {unqualified_total} 条**"))

    dead_desc = "；".join(
        f"{r.get('物料名称', '-')}({r.get('呆料产生数量（入库数量）', '-')})"
        for r in dead_records[:3]
    )
    unqualified_desc = "；".join(
        f"{r.get('物料名称', '-')}" for r in unqualified_records[:3]
    )
    try:
        raw = await _llm_summarize(
            f"以下是仓储呆滞与不合格清单统计：呆滞批次 {dead_total} 条"
            f"（示例：{dead_desc or '无'}）；不合格物料 {unqualified_total} 条"
            f"（示例：{unqualified_desc or '无'}）。"
            f"请用不超过 80 字的中文概括当前风险并给出一句话处理建议。"
        )
        summary_text = raw.strip()[:300]
    except Exception:  # noqa: BLE001 — LLM 故障降级为规则文案，永不抛出（宁夏模式）
        logger.warning("清单推送 LLM 解读失败，降级模板文案")
        summary_text = _stale_fallback_text(dead_total, unqualified_total)

    elements.append(_md(f"**解读**\n{summary_text}"))
    return build_card(
        title=f"呆滞与不合格清单 · {now_cn.date().isoformat()}",
        template="orange",
        elements=elements,
    )


register_push_generator("morning_report", _generate_morning)
register_push_generator("weekly_stock_report", _generate_weekly)
register_push_generator("monthly_report_push", _generate_monthly)
register_push_generator("stale_lists", _generate_stale_lists)
