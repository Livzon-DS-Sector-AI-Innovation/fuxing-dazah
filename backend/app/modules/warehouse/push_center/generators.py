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
from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.cards import build_card
from app.modules.warehouse.agent.tools.query import query_report
from app.modules.warehouse.finished_data import (
    SOURCE_RETURNS,
    SOURCE_UNQUALIFIED,
    fetch_daily_sales,
    fetch_day_movements,
    fetch_finished_outbound_rows,
    fetch_month_finished_io,
    fetch_pending_dispositions,
    fetch_quality_distribution,
    month_bounds,
    recent_window_start,
    summarize_invoice_states,
    summarize_shipments,
)
from app.modules.warehouse.intelligence import (
    _llm_summarize,  # noqa: SLF001 — 同包内部复用（宁夏模式同款）
)
from app.modules.warehouse.models import WarehouseMovement, WarehouseStock
from app.modules.warehouse.morning_report import generate_morning_report
from app.modules.warehouse.reports import (
    get_annual_report,
    get_monthly_report,
    get_usage_compare,
)
from app.modules.warehouse.usage_data import fetch_picking_rows, summarize_dept_usage

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
    """月报推送卡：复用既有月报聚合（上月口径）+ 成品段（P0 补齐），纯模板摘要。"""
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

    # 成品段（2026-09-22 P0 补齐，总文档成品③「每月出入库信息推送」）：
    # Base 直读成品入库/出库台账月度合计，失败降级标注不阻断月报
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    try:
        io = await fetch_month_finished_io(
            WarehouseBitableAdapter(), year=year, month=month
        )
        finished_line = (
            f"**成品** 入库 {io.inbound_count} 笔 / {fmt_qty(io.inbound_qty)}"
            f"　出库 {io.outbound_count} 笔 / {fmt_qty(io.outbound_qty)}"
        )
    except Exception:  # noqa: BLE001 — 成品拉取失败不影响原辅料月报
        logger.exception("月报成品段 Base 拉取失败，降级标注")
        finished_line = "**成品**：台账暂不可读（拉取失败）"
    elements.append(_md(finished_line))

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


# ── V3.0 分期D：成品侧每日推送（§4.5 成品③ / §4.8 ④⑥；Base 直读 2B）──


def _fmt_product_lines(totals: list[tuple[str, float]], limit: int) -> str:
    return "\n".join(
        f"{i}. {name}（{fmt_qty(qty)}）" for i, (name, qty) in enumerate(totals[:limit], start=1)
    )


async def _generate_finished_daily_summary(
    db: AsyncSession, now_cn: datetime
) -> dict[str, Any]:
    """成品每日汇总卡（§4.5 成品③）：昨日出入库 + 近 90 天质量状态分布。

    数据源 finished_receipt / finished_outbound（Base 直读，无本地镜像）；
    拉取失败降级计数为 0 并标注（不阻断推送泵其他任务）。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    adapter = WarehouseBitableAdapter()
    yesterday = now_cn.date() - timedelta(days=1)
    try:
        movements = await fetch_day_movements(adapter, day=yesterday)
        quality = await fetch_quality_distribution(
            adapter, since=recent_window_start(now_cn)
        )
    except Exception:  # noqa: BLE001 — Base 拉取失败降级出卡，推送失败由引擎兜底
        logger.exception("成品日汇总 Base 拉取失败，降级出卡")
        return build_card(
            title=f"成品每日汇总 · {yesterday.isoformat()}",
            template="yellow",
            elements=[_md("成品台账暂不可读（Base 拉取失败），请稍后重试或检查连接配置。")],
        )

    pending = quality.get("待处理")
    quarantined = quality.get("待检")
    returned = quality.get("退货")
    elements: list[dict[str, Any]] = [
        _md(
            f"**昨日入库** {movements.inbound_count} 笔 / {fmt_qty(movements.inbound_qty)}"
            f"　**出库** {movements.outbound_count} 笔 / {fmt_qty(movements.outbound_qty)}"
        ),
    ]
    if movements.inbound_by_product:
        elements.append(
            _md(f"**入库品名 Top{min(5, len(movements.inbound_by_product))}**\n"
                f"{_fmt_product_lines(movements.inbound_by_product, 5)}")
        )
    if movements.outbound_by_product:
        elements.append(
            _md(f"**出库品名 Top{min(5, len(movements.outbound_by_product))}**\n"
                f"{_fmt_product_lines(movements.outbound_by_product, 5)}")
        )
    quality_line = f"**近 90 天入库质量状态** 合格 {quality.get('合格')} 批"
    extras = []
    if quarantined:
        extras.append(f"待检 {quarantined}")
    if pending:
        extras.append(f"**待处理 {pending}**")
    if returned:
        extras.append(f"退货 {returned}")
    if extras:
        quality_line += "，" + "，".join(extras)
    elements.append(_md(quality_line))
    return build_card(
        title=f"成品每日汇总 · {yesterday.isoformat()}",
        template="orange" if (pending or quarantined) else "blue",
        elements=elements,
    )


async def _generate_invoice_four_state(
    db: AsyncSession, now_cn: datetime
) -> dict[str, Any]:
    """开票四态卡（§4.8⑥）：当月四态合计 + 发货未开票明细（客户+品规+数量）。

    数据源「每日销售汇总」行级（出库量 vs 开票数量逐行判定，按销售日期
    归月）；未开票未发货不推（无行动价值）。纯数据卡（grilling 决策 11）。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    adapter = WarehouseBitableAdapter()
    try:
        rows = await fetch_daily_sales(adapter)
    except Exception:  # noqa: BLE001 — Base 拉取失败降级出卡
        logger.exception("开票四态 Base 拉取失败，降级出卡")
        return build_card(
            title=f"开票四态 · {now_cn.date().isoformat()}",
            template="yellow",
            elements=[_md("销售台账暂不可读（Base 拉取失败），请稍后重试或检查连接配置。")],
        )

    month_start, month_end = month_bounds(now_cn.year, now_cn.month)
    summary = summarize_invoice_states(rows, month_start=month_start, month_end=month_end)
    elements: list[dict[str, Any]] = [
        _md(
            f"**本月（按销售日期）**\n"
            f"✅ 已开票已发货 {summary.invoiced_shipped_count} 笔 / {fmt_qty(summary.invoiced_shipped_qty)}\n"
            f"⏳ 发货未开票 {summary.shipped_uninvoiced_count} 笔 / {fmt_qty(summary.shipped_uninvoiced_qty)}\n"
            f"📄 开票未发货 {summary.invoiced_unshipped_count} 笔 / {fmt_qty(summary.invoiced_unshipped_qty)}"
        ),
    ]
    detail = summary.unbilled_detail[:10]
    if detail:
        lines = "\n".join(
            f"{i}. {row.customer or '-'}｜{row.product_name or '-'}｜"
            f"{fmt_qty(row.shipped_qty)}（{row.sales_date.isoformat() if row.sales_date else '-'}）"
            for i, row in enumerate(detail, start=1)
        )
        more = (
            f"\n…等共 {summary.shipped_uninvoiced_count} 笔"
            if summary.shipped_uninvoiced_count > len(detail) else ""
        )
        elements.append(_md(f"**发货未开票明细（催开票）**\n{lines}{more}"))
    elif summary.shipped_uninvoiced_count == 0:
        elements.append(_md("当月暂无发货未开票项"))
    return build_card(
        title=f"开票四态 · {now_cn.date().isoformat()}",
        template="orange" if summary.shipped_uninvoiced_count else "green",
        elements=elements,
    )


register_push_generator("finished_daily_summary", _generate_finished_daily_summary)
register_push_generator("invoice_four_state", _generate_invoice_four_state)


async def _generate_finished_disposition_lists(
    db: AsyncSession, now_cn: datetime
) -> dict[str, Any]:
    """成品退货/不合格/待处理清单卡（§4.8④）：三类聚合纯数据卡。

    推送成功后由后置钩子挂处理方案确认门（confirm_integrations，回写
    处理确认日期=@today）；入库台账质量状态=待处理仅展示不入门（QC 职权）。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    adapter = WarehouseBitableAdapter()
    try:
        pending = await fetch_pending_dispositions(adapter)
        quality = await fetch_quality_distribution(
            adapter, since=recent_window_start(now_cn)
        )
    except Exception:  # noqa: BLE001 — Base 拉取失败降级出卡
        logger.exception("成品待处理清单 Base 拉取失败，降级出卡")
        return build_card(
            title=f"成品待处理清单 · {now_cn.date().isoformat()}",
            template="yellow",
            elements=[_md("成品台账暂不可读（Base 拉取失败），请稍后重试或检查连接配置。")],
        )

    returns_rows = [r for r in pending if r.source == SOURCE_RETURNS]
    unqualified_rows = [r for r in pending if r.source == SOURCE_UNQUALIFIED]
    pending_receipt = quality.get("待处理", 0)
    if not pending and pending_receipt == 0:
        return build_card(
            title=f"成品待处理清单 · {now_cn.date().isoformat()}",
            template="green",
            elements=[_md("退货 0 条；不合格 0 条；待处理入库批次 0 批 — 无待处理项")],
        )

    def _rows_block(rows: list[Any], label: str) -> str:
        lines = "\n".join(
            f"{i}. {r.product_name or '-'}（{r.spec or '-'}）批 {r.batch_no or '-'}｜"
            f"{fmt_qty(r.qty)}{r.unit or ''}｜{r.reason or '-'}"
            for i, r in enumerate(rows[:3], start=1)
        )
        more = f"\n…等共 {len(rows)} 条" if len(rows) > 3 else ""
        return f"**成品{label} {len(rows)} 条**\n{lines}{more}"

    elements: list[dict[str, Any]] = []
    if returns_rows:
        elements.append(_md(_rows_block(returns_rows, "退货")))
    else:
        elements.append(_md("**成品退货 0 条**"))
    if unqualified_rows:
        elements.append(_md(_rows_block(unqualified_rows, "不合格")))
    else:
        elements.append(_md("**成品不合格 0 条**"))
    elements.append(_md(f"**待处理入库批次** {pending_receipt} 批（近 90 天，质量状态=待处理）"))
    return build_card(
        title=f"成品待处理清单 · {now_cn.date().isoformat()}",
        template="red" if pending else "orange",
        elements=elements,
    )


register_push_generator("finished_disposition_lists", _generate_finished_disposition_lists)


async def _generate_annual_report(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """年报推送卡（§4.5）：上年度原辅料出入库聚合 + 成品年度出货 + LLM 解读。

    每年 1 月 1 日触发（yearly 调度），推 now.year-1 年度；成品部分 Base 直读
    finished_outbound（用途=销售口径）按品名聚合，拉取失败降级标注不阻断。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    year = now_cn.year - 1
    annual = await get_annual_report(db, year)
    summary = annual["summary"]

    finished_by_product: dict[str, float] = {}
    finished_error = False
    try:
        for row in await fetch_finished_outbound_rows(WarehouseBitableAdapter()):
            if row.purpose != "销售" or row.outbound_date is None:
                continue
            if row.outbound_date.year != year:
                continue
            name = row.product_name or "未填产品"
            finished_by_product[name] = finished_by_product.get(name, 0.0) + (row.qty or 0.0)
    except Exception:  # noqa: BLE001 — 成品拉取失败不影响原辅料部分
        logger.exception("年报成品部分 Base 拉取失败，降级标注")
        finished_error = True
    finished_top = sorted(finished_by_product.items(), key=lambda kv: kv[1], reverse=True)[:5]

    elements: list[dict[str, Any]] = [
        _md(
            f"**原辅料 {year} 年度**\n"
            f"入库 {summary['inbound_count']} 笔 / {fmt_qty(summary['inbound_qty'])}　"
            f"出库 {summary['outbound_count']} 笔 / {fmt_qty(summary['outbound_qty'])}　"
            f"涉及物料 {len(annual['items'])} 种"
        ),
    ]
    top = annual["items"][:5]
    if top:
        lines = "\n".join(
            f"{i}. {item['material_name']}（出库 {fmt_qty(item['outbound_qty'])} {item['unit'] or ''}）"
            for i, item in enumerate(top, start=1)
        )
        elements.append(_md(f"**原辅料出库 Top{len(top)}**\n{lines}"))
    finished_line = (
        "\n".join(
            f"{i}. {name}（{fmt_qty(qty)}）" for i, (name, qty) in enumerate(finished_top, start=1)
        )
        if finished_top else "本年度无销售出货记录"
    )
    if finished_error:
        finished_line = "成品台账暂不可读（拉取失败）"
    elements.append(_md(f"**成品销售出货 Top{len(finished_top) or 0}**\n{finished_line}"))

    month_peak = max(annual["months"], key=lambda m: m["outbound_qty"]) if annual["months"] else None
    try:
        raw = await _llm_summarize(
            f"以下是 {year} 年仓储年报摘要：原辅料入库 {summary['inbound_count']} 笔"
            f"/{summary['inbound_qty']:.0f}，出库 {summary['outbound_count']} 笔"
            f"/{summary['outbound_qty']:.0f}，出库最高月份为"
            f"{month_peak['month'] if month_peak else '-'} 月；"
            f"出库前五物料：{'、'.join(i['material_name'] for i in top) or '无'}。"
            f"请用不超过 100 字的中文概括该年度库存运行特点并给出一句话建议。"
        )
        summary_text = raw.strip()[:300]
    except Exception:  # noqa: BLE001 — LLM 故障降级模板（宁夏模式）
        logger.warning("年报 LLM 解读失败，降级模板文案")
        summary_text = (
            f"{year} 年原辅料出库 {fmt_qty(summary['outbound_qty'])}；"
            f"详见 Web 报表中心年报页。"
        )
    elements.append(_md(f"**年度解读**\n{summary_text}"))
    return build_card(
        title=f"仓储年报 · {year}",
        template="blue",
        elements=elements,
    )


register_push_generator("annual_report", _generate_annual_report)


async def _generate_usage_compare(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """月度「实际 vs 预期」用量对比卡（§4.4⑥）：偏差 Top10 + LLM 合理化建议。

    每月 1 日触发推上月；实际=本地 movement 出库聚合，预期=material_master
    「月度预期用量」列（人工填基准）。LLM 失败降级模板文案。
    """
    year, month = (now_cn.year, now_cn.month - 1) if now_cn.month > 1 else (now_cn.year - 1, 12)
    try:
        compare = await get_usage_compare(db, year, month)
    except Exception:  # noqa: BLE001 — Base 拉取失败降级出卡
        logger.exception("用量对比 Base 拉取失败，降级出卡")
        return build_card(
            title=f"物料用量对比 · {year}-{month:02d}",
            template="yellow",
            elements=[_md("物料主数据暂不可读（Base 拉取失败），请稍后重试或检查连接配置。")],
        )

    items = compare["items"]
    elements: list[dict[str, Any]] = [
        _md(
            f"**{year}-{month:02d} 实际 vs 预期**：对比物料 {compare['total']} 种"
            + (f"　**未设基准有用量 {compare['no_baseline_with_usage']} 种**"
               if compare["no_baseline_with_usage"] else "")
        ),
    ]
    deviated = [r for r in items if r["deviation"] is not None][:10]
    if deviated:
        lines = "\n".join(
            f"{i}. {r['material_name']}：实际 {fmt_qty(r['actual_qty'])}"
            f" / 预期 {fmt_qty(r['expected_qty'])}（偏差 {r['deviation'] * 100:.0f}%）"
            for i, r in enumerate(deviated, start=1)
        )
        elements.append(_md(f"**偏差 Top{len(deviated)}**\n{lines}"))
    else:
        elements.append(_md("本月无可对比数据（请先在物料主数据维护「月度预期用量」基准）"))

    try:
        desc = "；".join(
            f"{r['material_name']}偏差{r['deviation'] * 100:.0f}%" for r in deviated[:3]
        )
        raw = await _llm_summarize(
            f"以下是 {year}-{month:02d} 物料用量与预期基准对比：{desc or '无可对比数据'}。"
            f"请用不超过 80 字的中文概括用量异常并给出一句话合理化建议。"
        )
        summary_text = raw.strip()[:300]
    except Exception:  # noqa: BLE001 — LLM 故障降级（宁夏模式）
        logger.warning("用量对比 LLM 解读失败，降级模板文案")
        summary_text = "请关注偏差较大物料的领用合理性；基准维护请在物料主数据「月度预期用量」列填写。"
    elements.append(_md(f"**解读与建议**\n{summary_text}"))
    return build_card(
        title=f"物料用量对比 · {year}-{month:02d}",
        template="orange" if deviated else "blue",
        elements=elements,
    )


register_push_generator("material_usage_compare", _generate_usage_compare)


def _month_bounds_dates(now_cn: datetime, offset_months: int) -> tuple[date, date]:
    """相对 now 前 offset_months 个月的自然月 [start, end) date 边界（复用 finished_data.month_bounds）。"""
    year, month = now_cn.year, now_cn.month - offset_months
    while month <= 0:
        month += 12
        year -= 1
    return month_bounds(year, month)


async def _generate_shipment_analysis(db: AsyncSession, now_cn: datetime) -> dict[str, Any]:
    """发货去向月度分析卡（§4.8⑤）：上月客户排名/环比/品名分布 + LLM 解读。

    数据源 finished_outbound（用途=销售口径）；品名分布取 Top1 客户；
    LLM 失败降级模板文案。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    start, end = _month_bounds_dates(now_cn, 1)
    try:
        rows = await fetch_finished_outbound_rows(WarehouseBitableAdapter())
    except Exception:  # noqa: BLE001 — Base 拉取失败降级出卡
        logger.exception("发货分析 Base 拉取失败，降级出卡")
        return build_card(
            title=f"发货去向分析 · {start.strftime('%Y-%m')}",
            template="yellow",
            elements=[_md("成品台账暂不可读（Base 拉取失败），请稍后重试或检查连接配置。")],
        )

    current = summarize_shipments(rows, start=start, end=end)
    prev_start, prev_end = _month_bounds_dates(now_cn, 2)
    previous = {
        c.customer: c.total_qty
        for c in summarize_shipments(rows, start=prev_start, end=prev_end)
    }

    elements: list[dict[str, Any]] = [
        _md(f"**{start.strftime('%Y-%m')} 销售发货客户数** {len(current)}"),
    ]
    if not current:
        elements.append(_md("上月无销售发货记录（首期或当月无数据，无环比对比）"))
    else:
        top = current[:5]
        lines = []
        for i, c in enumerate(top, start=1):
            prev_qty = previous.get(c.customer)
            delta = (
                f"环比 {(c.total_qty - prev_qty) / prev_qty * 100:+.0f}%"
                if prev_qty
                else "环比 新客户/上月无数据"
            )
            lines.append(
                f"{i}. {c.customer}：{fmt_qty(c.total_qty)}（{c.order_count} 笔，{delta}）"
            )
        elements.append(_md(f"**客户排名 Top{len(top)}**\n" + "\n".join(lines)))
        lead = top[0]
        if lead.product_totals:
            product_lines = "\n".join(
                f"- {name}（{fmt_qty(qty)}）" for name, qty in lead.product_totals[:5]
            )
            elements.append(_md(f"**{lead.customer} 品名分布**\n{product_lines}"))

    try:
        desc = "；".join(
            f"{c.customer}{fmt_qty(c.total_qty)}" for c in current[:3]
        )
        raw = await _llm_summarize(
            f"以下是 {start.strftime('%Y-%m')} 成品销售发货分析："
            f"{desc or '无发货记录'}。请用不超过 80 字的中文概括发货结构并给出一句话建议。"
        )
        summary_text = raw.strip()[:300]
    except Exception:  # noqa: BLE001 — LLM 故障降级（宁夏模式）
        logger.warning("发货分析 LLM 解读失败，降级模板文案")
        summary_text = "请关注客户集中度与发货波动；明细见成品出库台账。"
    elements.append(_md(f"**解读**\n{summary_text}"))
    return build_card(
        title=f"发货去向分析 · {start.strftime('%Y-%m')}",
        template="blue",
        elements=elements,
    )


register_push_generator("shipment_analysis", _generate_shipment_analysis)


async def _generate_workshop_weekly_usage(
    db: AsyncSession, now_cn: datetime
) -> dict[str, Any]:
    """车间周用量卡（§4.4⑤ 简化版）：按领用部门聚合近 7 天领料（Base 直读）。

    Base 拉取失败降级为本地近 7 天出库总量卡并告警；纯数据卡（grilling
    决策 11：车间周用量不接 LLM）。
    """
    from app.modules.warehouse.bitable_adapter import WarehouseBitableAdapter

    start = (now_cn - timedelta(days=7)).date()
    try:
        rows = await fetch_picking_rows(WarehouseBitableAdapter())
        usages = summarize_dept_usage(rows, start=start, end=now_cn.date())
    except Exception:  # noqa: BLE001 — Base 失败降级本地口径（数量口径不同，须标注）
        logger.exception("车间周用量 Base 拉取失败，降级本地出库口径")
        window_start = datetime.combine(start, dtime(0, 0), tzinfo=CN_TZ)
        movements = list(
            (
                await db.execute(
                    select(WarehouseMovement).where(
                        WarehouseMovement.is_deleted == False,  # noqa: E712
                        WarehouseMovement.direction == "outbound",
                        WarehouseMovement.occurred_at >= window_start,
                    )
                )
            ).scalars().all()
        )
        qty = sum(float(m.quantity) for m in movements)
        return build_card(
            title=f"车间周用量 · {start.isoformat()} ~ {now_cn.date().isoformat()}",
            template="yellow",
            elements=[
                _md("领料台账暂不可读，以下为**本地流水口径**（仅参考）："),
                _md(f"**近 7 天本地出库** {len(movements)} 笔 / {fmt_qty(qty)}"),
            ],
        )

    elements: list[dict[str, Any]] = [
        _md(f"**近 7 天领料** {sum(u.order_count for u in usages)} 笔"
            f" / {len(usages)} 个部门"),
    ]
    if not usages:
        elements.append(_md("窗口期内无领料记录"))
    for dept in usages[:8]:
        materials = "、".join(
            f"{name} {fmt_qty(qty)}" for name, qty in dept.top_materials
        )
        elements.append(
            _md(f"**{dept.department}** {dept.order_count} 笔 / {fmt_qty(dept.total_qty)}"
                + (f"\n{materials}" if materials else ""))
        )
    return build_card(
        title=f"车间周用量 · {start.isoformat()} ~ {now_cn.date().isoformat()}",
        template="blue",
        elements=elements,
    )


register_push_generator("workshop_weekly_usage", _generate_workshop_weekly_usage)
