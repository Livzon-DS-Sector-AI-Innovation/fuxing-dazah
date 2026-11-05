"""事件推送入口（V3.0 分期A Ticket 08）：业务钩子 → 事件型任务 → 目标推送。

与定时路径（engine.run_due_tasks）共用任务配置/目标回退链/推送日志/失败
告警；区别在触发方式：业务事件（如成品出库登记快递号）即时调用
``fire_push_event``，不走到期判断。事件卡片由 payload 即时渲染
（EVENT_RENDERERS 注册表，无 DB 依赖）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.models import WarehousePushLog
from app.modules.warehouse.push_center import engine as _engine_mod
from app.modules.warehouse.push_center import registry

# 同包内部复用引擎执行件（发送落库/互斥锁/失败告警；与 reports 复用
# intelligence._material_stock_totals 同款先例）
from app.modules.warehouse.push_center.engine import (  # noqa: SLF001
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_SKIPPED_BUSY,
    STATUS_SKIPPED_DISABLED,
    STATUS_SKIPPED_NO_TARGET,
    PushRunResult,
    _fire_failure,
    _lock_for,
    _send_and_log,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")

# 事件卡片渲染器：payload → 飞书卡片 dict（无 DB 依赖，纯函数）
EventRenderer = Callable[[dict[str, Any]], dict[str, Any]]
EVENT_RENDERERS: dict[str, EventRenderer] = {}


def register_event_renderer(scene: str, renderer: EventRenderer) -> None:
    """注册事件渲染器；重复注册抛错。"""
    if scene in EVENT_RENDERERS:
        raise ValueError(f"事件渲染器重复注册: {scene}")
    EVENT_RENDERERS[scene] = renderer


def get_event_renderer(scene: str) -> EventRenderer | None:
    return EVENT_RENDERERS.get(scene)


def render_express_notify_card(payload: dict[str, Any]) -> dict[str, Any]:
    """快递发货通知卡（品名/批号/数量/客户/快递号/出库日期，窄屏排版）。"""
    from app.modules.warehouse.agent.cards import build_card

    def _text(key: str) -> str:
        value = payload.get(key)
        return str(value).strip() if value is not None else ""

    lines = [
        f"**产品** {_text('product_name') or '-'}"
        f"　**批号** {_text('product_batch_no') or '-'}",
        f"**数量** {_text('quantity') or '-'} {_text('unit')}"
        f"　**客户** {_text('customer') or '-'}",
        f"**快递号** {_text('express_no') or '-'}",
    ]
    if _text("outbound_date"):
        lines.append(f"**出库日期** {_text('outbound_date')}")
    if _text("remark"):
        lines.append(f"**备注** {_text('remark')}")
    return build_card(
        title="📦 发货通知",
        template="green",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("express_notify", render_express_notify_card)


# ── V3.0 分期B：QC 请验放行闭环三个事件场景（设计 §4.1）──


def _payload_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    return str(value).strip() if value is not None else ""


def render_arrival_inspection_card(payload: dict[str, Any]) -> dict[str, Any]:
    """到货请验卡（链路1）：物料/批号/供应商/数量 + 台账记录链接，窄屏排版。"""
    from app.modules.warehouse.agent.cards import build_card

    def _t(key: str) -> str:
        return _payload_text(payload, key) or "-"

    lines = [
        f"**物料** {_t('material_name')}　**批号** {_t('batch_no')}",
        f"**供应商** {_t('supplier')}",
        f"**数量** {_t('quantity')} {_t('unit')}",
    ]
    if _payload_text(payload, "record_url"):
        lines.append(f"[📋 打开台账记录（填写取样/出报）]({_payload_text(payload, 'record_url')})")
    return build_card(
        title="📥 到货请验",
        template="orange",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("arrival_inspection", render_arrival_inspection_card)


def render_qc_progress_alert_card(payload: dict[str, Any]) -> dict[str, Any]:
    """QC 进度超期提醒卡（链路2）：未取样超期 / 未出报超期（加急）条目列表。"""
    from app.modules.warehouse.agent.cards import build_card

    kind_label = {"sample": "⏰ 未取样", "report": "🔥 未出报加急"}
    lines = []
    for item in payload.get("items") or []:
        name = str(item.get("material_name") or "-")
        batch = str(item.get("batch_no") or "-")
        days = item.get("waited_days")
        kind = kind_label.get(str(item.get("kind") or ""), "超期")
        waited = f"{days} 天" if days is not None else "-"
        lines.append(f"- {kind}：**{name}**（批号 {batch}，已等待 {waited}）")
    if not lines:
        lines.append("（本期无超期批号）")
    return build_card(
        title="⏰ QC 进度超期提醒",
        template="red",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("qc_progress_alert", render_qc_progress_alert_card)


def render_release_notify_card(payload: dict[str, Any]) -> dict[str, Any]:
    """放行上架通知卡（链路3）：批号已放行（含条件放行），可上架。"""
    from app.modules.warehouse.agent.cards import build_card

    def _t(key: str) -> str:
        return _payload_text(payload, key) or "-"

    release = _t("release_type")
    extra = "（条件放行，请留意放行条件）" if release == "条件放行" else ""
    lines = [
        f"**物料** {_t('material_name')}　**批号** {_t('batch_no')}",
        f"**QA 放行** {release}{extra}",
        "该批号已放行，可以上架使用。",
    ]
    return build_card(
        title="✅ 已放行可上架",
        template="green",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("release_notify", render_release_notify_card)


# ── V3.0 分期C：入库供应商不一致提醒（设计 §4.3，AI 辅助核对口径）──


def render_supplier_mismatch_alert_card(payload: dict[str, Any]) -> dict[str, Any]:
    """供应商不一致提醒卡：识别供应商与主数据两方对照，请人工核实。"""
    from app.modules.warehouse.agent.cards import build_card

    master = _payload_text(payload, "master_supplier")
    lines = [
        f"**物料** {_payload_text(payload, 'material_name') or '-'}"
        f"　**批号** {_payload_text(payload, 'batch_no') or '-'}",
        f"**识别供应商** {_payload_text(payload, 'supplier') or '-'}",
    ]
    if master:
        lines.append(f"**主数据供应商** {master}")
    # 名录授权物料（2026-09-22 P0 补列；查询失败/未配置时 payload 无此键）
    directory_materials = _payload_text(payload, "directory_materials")
    if directory_materials:
        lines.append(f"**名录授权物料** {directory_materials}")
    lines.append("识别供应商与主数据记录不一致，请人工核实（AI 辅助核对，系统不做判定）。")
    if _payload_text(payload, "record_url"):
        lines.append(
            f"[📋 打开台账记录]({_payload_text(payload, 'record_url')})"
        )
    return build_card(
        title="⚠️ 供应商不一致",
        template="yellow",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("supplier_mismatch_alert", render_supplier_mismatch_alert_card)


# ── 五金库（系统原生仓储域，设计 2026-11-04 §9.5）──


def render_hardware_direct_pickup_card(payload: dict[str, Any]) -> dict[str, Any]:
    """direct 直发领取卡：车间单独需求类到货即领（不走审批，出入双流水留痕）。"""
    from app.modules.warehouse.agent.cards import build_card

    rows = payload.get("rows") or []
    lines = [f"**{r.get('name', '-')}** {r.get('spec') or ''} × {r.get('quantity', '-')} {r.get('unit') or ''}"
             for r in rows[:10]]
    if len(rows) > 10:
        lines.append(f"…共 {len(rows)} 行")
    return build_card(
        title="🔩 五金库到货待领",
        template="blue",
        elements=[{"tag": "markdown", "content": "\n".join([
            f"**直发车间** {payload.get('dept', '-')}",
            f"**供应商** {payload.get('supplier', '-') or '-'}",
            f"**入库单** {payload.get('receipt_no', '-')}",
            "",
            *lines,
            "",
            "车间单独需求类已确认入账（出入双流水留痕），请办事员到五金库领取。",
        ])}],
    )


register_event_renderer("hardware_direct_pickup", render_hardware_direct_pickup_card)


def render_hardware_receipt_rejected_card(payload: dict[str, Any]) -> dict[str, Any]:
    """拒收通知采购：留证原因+供应商，采购负责退换货。"""
    from app.modules.warehouse.agent.cards import build_card

    return build_card(
        title="🚫 五金库入库拒收",
        template="red",
        elements=[{"tag": "markdown", "content": "\n".join([
            f"**入库单** {payload.get('receipt_no', '-')}",
            f"**供应商** {payload.get('supplier_name', '-') or '-'}",
            f"**拒收原因** {payload.get('reason', '-') or '-'}",
            "",
            "请采购跟进退换货（照片证据已留档）。",
        ])}],
    )


register_event_renderer("hardware_receipt_rejected", render_hardware_receipt_rejected_card)


def render_hardware_requisition_rejected_card(payload: dict[str, Any]) -> dict[str, Any]:
    """领用驳回通知申请人（预扣已释放）。"""
    from app.modules.warehouse.agent.cards import build_card

    return build_card(
        title="❌ 领用申请已驳回",
        template="orange",
        elements=[{"tag": "markdown", "content": "\n".join([
            f"**单号** {payload.get('req_no', '-')}",
            f"**申请人** {payload.get('applicant', '-')}",
            f"**驳回原因** {payload.get('reason', '-') or '-'}",
            "",
            "预扣库存已释放，可修改后重新提交。",
        ])}],
    )


register_event_renderer("hardware_requisition_rejected", render_hardware_requisition_rejected_card)


async def fire_push_event(
    db: AsyncSession,
    scene: str,
    payload: dict[str, Any],
    *,
    dry_run: bool | None = None,
) -> list[PushRunResult]:
    """触发一次事件推送：匹配 trigger=event 且启用的任务，渲染 payload 推送目标。

    返回每个匹配任务的执行结果（含 skipped_disabled/skipped_no_target）；
    单任务失败记日志并告警，不影响其他任务。不 commit（调用方上下文统一提交）。
    """
    results: list[PushRunResult] = []
    now = datetime.now(CN_TZ)
    for info in registry.iter_tasks():
        if info.trigger != "event" or info.scene != scene:
            continue
        # 经 engine 模块属性取 store（与定时路径共用同一替换点/缓存失效语义）
        view = _engine_mod.push_store.get_task_view(info.task_name)
        if not view.enabled:
            results.append(PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_DISABLED))
            continue
        lock = _lock_for(view.task_name)
        if lock.locked():
            results.append(PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_BUSY))
            continue
        async with lock:
            results.append(
                await _execute_event(db, view, payload, now, dry_run=dry_run)
            )
    return results


async def _execute_event(
    db: AsyncSession,
    view: Any,
    payload: dict[str, Any],
    now: datetime,
    *,
    dry_run: bool | None,
) -> PushRunResult:
    """执行单事件任务：渲染 → 逐目标发送 → 日志（trigger=event）。"""
    targets = list(view.targets)
    if not targets:
        db.add(
            WarehousePushLog(
                task_name=view.task_name,
                scene=view.scene,
                trigger="event",
                run_at=now,
                slot=None,
                target=None,
                status="skipped",
                error="未配置推送目标（DB 与 env 均为空），已跳过",
            )
        )
        await db.flush()
        return PushRunResult(view.task_name, view.scene, STATUS_SKIPPED_NO_TARGET, None, 1)

    renderer = get_event_renderer(view.scene)
    if renderer is None:
        error = f"未注册事件渲染器: {view.scene}"
        db.add(
            WarehousePushLog(
                task_name=view.task_name,
                scene=view.scene,
                trigger="event",
                run_at=now,
                slot=None,
                target=None,
                status="failed",
                error=error,
            )
        )
        await db.flush()
        _fire_failure(view, error)
        return PushRunResult(view.task_name, view.scene, STATUS_FAILED, None, 1)

    card = renderer(payload)
    log_count, ok_count = await _send_and_log(
        db, view, card, targets, now,
        trigger="event", slot=None, dry_run=dry_run,
    )
    if ok_count < log_count:
        _fire_failure(view, f"事件推送部分目标发送失败（{view.task_name}）")
    return PushRunResult(view.task_name, view.scene, STATUS_EXECUTED, None, log_count)


def render_hardware_urgent_overdue_card(payload: dict[str, Any]) -> dict[str, Any]:
    """紧急领用 24h 未补单提醒（设计 §4.2：仓储部有权暂停该部门后续领用）。"""
    from app.modules.warehouse.agent.cards import build_card

    items = payload.get("items") or []
    lines = [f"- {it.get('req_no', '-')}（{it.get('dept', '-')} / {it.get('applicant', '-')}）" for it in items[:10]]
    if len(items) > 10:
        lines.append(f"…共 {len(items)} 单")
    return build_card(
        title="⏰ 五金库紧急领用超期未补单",
        template="red",
        elements=[{"tag": "markdown", "content": "\n".join([
            f"**{payload.get('count', len(items))} 单**紧急领用超过 24 小时未补审批单，已标记超期：",
            "",
            *lines,
            "",
            "依据制度 5.3.4，仓储部有权暂停该部门后续领用，请尽快补单。",
        ])}],
    )


register_event_renderer("hardware_urgent_overdue", render_hardware_urgent_overdue_card)


def render_hardware_stale_list_card(payload: dict[str, Any]) -> dict[str, Any]:
    """呆滞物资季度清单卡（设计 §2.6：连续 3 个月无 outbound 且有库存）。"""
    from app.modules.warehouse.agent.cards import build_card

    items = payload.get("items") or []
    lines = [
        f"- {it.get('name', '-')}（{it.get('spec') or '-'}）：库存 {it.get('on_hand', 0)}"
        f" {it.get('unit') or ''}，静默 {it.get('silent_days', '—')} 天"
        for it in items[:15]
    ]
    if len(items) > 15:
        lines.append(f"…共 {len(items)} 项")
    return build_card(
        title="📦 五金库呆滞物资清单（季度扫描）",
        template="orange",
        elements=[{"tag": "markdown", "content": "\n".join([
            f"**{payload.get('count', len(items))} 项**物资连续 3 个月无出库且仍有库存：",
            "",
            *lines,
            "",
            "请仓储→生产/财务/使用部门确认处置（调拨/报废走三期）。",
        ])}],
    )


register_event_renderer("hardware_stale_list", render_hardware_stale_list_card)


def render_hardware_env_remind_card(payload: dict[str, Any]) -> dict[str, Any]:
    """温湿度日检每日提醒（17:00 当天未填才推）。"""
    from app.modules.warehouse.agent.cards import build_card

    return build_card(
        title="🌡️ 五金库温湿度日检提醒",
        template="blue",
        elements=[{"tag": "markdown", "content": "\n".join([
            f"今天（{payload.get('date', '-')}）的温湿度日检还未填写。",
            "",
            "请仓管员到 系统 → 仓储管理 → 五金温湿度日检 完成登记"
            "（温度/湿度/异常说明，每日一行）。",
        ])}],
    )


register_event_renderer("hardware_env_remind", render_hardware_env_remind_card)


def render_hardware_digest_card(payload: dict[str, Any]) -> dict[str, Any]:
    """五金库日速递卡（数字全流水聚合；AI 总结仅叙述文本）。"""
    from app.modules.warehouse.agent.cards import build_card

    summary = str(payload.get("ai_summary") or "").strip()
    frequency = str(payload.get("frequency") or "日报")
    auto_count = int(payload.get("auto_accepted_count", 0) or 0)
    lines = [
        f"**{payload.get('date', '-')} 五金库{frequency}**",
        "",
        f"- 入库单：{payload.get('receipts_today', 0)} 张",
        f"- 发料出库：{payload.get('outbound_today', 0)} 笔 / {payload.get('outbound_qty_today', 0)} 件",
        f"- 待发料：{payload.get('to_issue', 0)} 单 ｜ 紧急未补：{payload.get('urgent_overdue', 0)} 单",
        f"- 待确认草稿：{payload.get('draft_backlog', 0)} 张 ｜ 低库存物料：{payload.get('low_stock_count', 0)} 项",
    ]
    if auto_count:
        # M9 放权披露（§9.3）：direct 高置信自动入账单数+复核抽检入口
        lines += [
            f"- ⚙️ 自动入账（direct 高置信）：{auto_count} 张——请到报表·ERP 对账 Tab 抽检复核",
        ]
    if summary:
        lines += ["", f"> {summary}"]
    return build_card(
        title="五金库日速递",
        template="blue",
        elements=[{"tag": "markdown", "content": "\n".join(lines)}],
    )


register_event_renderer("hardware_digest", render_hardware_digest_card)
