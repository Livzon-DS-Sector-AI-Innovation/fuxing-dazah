"""五金库三执行器（二期 M6，§9.2 确定性函数先行）。

- hardware_urge：催办卡（低库存/紧急未补/草稿积压/超时未发料/呆滞）——
  enqueue_outbox feishu_card（chat_id 行内权威：WAREHOUSE_HARDWARE_ALERT_CHAT_ID
  → WAREHOUSE_TEST_CHAT_ID 回退；空配置静默跳过不报错）；
- hardware_digest_push：日/周报速递格——结构化数字全部 SQL 聚合（**数字
  永不由 LLM 生成**红线），AI 总结文本走 hardware_digest_summary 场景；
  推送走 push_center（scene=hardware_digest，发测试群）；
- hardware_plan_draft：调 M5 generate_monthly_plan（幂等；SUPERAGENT_ENABLED
  =false 时 25 日 CRON 任务为主通道，功能不受损）。

放权红线（§9.3）：三执行器零动账（只读聚合+推送+草案）；SUPERAGENT_ENABLED
总开关 + per-source enabled 白名单沿用底座闸。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.platform.superagent.executors import Report

logger = logging.getLogger(__name__)

_TZ_SH = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(_TZ_SH)


def _urge_chat_id() -> str:
    """催办目标群：专用配置优先，测试群兜底；空=静默跳过。"""
    return (
        os.environ.get("WAREHOUSE_HARDWARE_ALERT_CHAT_ID", "").strip()
        or os.environ.get("WAREHOUSE_TEST_CHAT_ID", "").strip()
    )


async def _origin_payload(session: Any, task_dict: dict[str, Any]) -> dict[str, Any]:
    """origin Trigger payload（权威快照；mandate 只带身份键）——R1 同款。"""
    from app.platform.superagent.models import AgentTask, AgentTrigger

    task = await session.get(AgentTask, uuid.UUID(str(task_dict["id"])))
    trigger = (
        await session.get(AgentTrigger, task.origin_trigger_id)
        if task is not None and task.origin_trigger_id is not None
        else None
    )
    return dict(trigger.payload or {}) if trigger is not None else {}


def _build_urge_body(payload: dict[str, Any]) -> dict[str, str]:
    """催办卡文案（数字全部来自 payload=Source SQL 聚合）。"""
    et = str(payload.get("event_type") or "")
    title_map = {
        "low_stock": "🔴 五金库安全库存击穿",
        "urgent_unpatched": "⏰ 五金库紧急领用超期未补单",
        "draft_backlog": "📥 五金库入库草稿积压",
        "issue_timeout": "🚚 五金库审批通过未发料超时",
        "stale": "📦 五金库呆滞物资到期",
    }
    lines: list[str] = []
    if et == "low_stock":
        lines = [
            f"**{payload.get('name', '-')}**（{payload.get('spec') or '-'}）"
            f"可用量 {payload.get('available')} 低于安全库存 {payload.get('safety_stock')}",
            "",
            f"- 在手 {payload.get('on_hand')} ｜ 预扣 {payload.get('reserved')}",
            f"- 编码：{payload.get('code') or '待回填'}",
            "",
            "请评估补货（月度计划公式会自动纳入，紧急可走申购）。",
        ]
    elif et == "urgent_unpatched":
        lines = [
            f"单号 **{payload.get('req_no', '-')}**（{payload.get('dept', '-')} / {payload.get('applicant', '-')}）",
            "",
            f"- 补单截止：{payload.get('deadline') or '—'}",
            "",
            "依据制度 5.3.4，仓储部有权暂停该部门后续领用，请尽快补审批单。",
        ]
    elif et == "draft_backlog":
        lines = [
            f"待确认入库草稿 **{payload.get('count')}** 张（阈值 {payload.get('threshold')}）。",
            "",
            "请仓管员到出入库工作台·入库台逐单核对确认入账。",
        ]
    elif et == "issue_timeout":
        lines = [
            f"单号 **{payload.get('req_no', '-')}**（{payload.get('dept', '-')} / {payload.get('applicant', '-')}）",
            "",
            f"- 审批通过：{payload.get('approved_at') or '—'}（已 {payload.get('hours')} 小时）",
            "",
            "请仓管员尽快发料（FIFO 建议在发料台）。",
        ]
    elif et == "stale":
        items = payload.get("items") or []
        detail = "\n".join(
            f"- {it.get('name', '-')}：库存 {it.get('on_hand')}，静默 {it.get('silent_days')} 天"
            for it in items[:8]
        )
        lines = [
            f"本季度呆滞物资 **{payload.get('count')}** 项（连续 3 个月无出库且仍有库存）：",
            "",
            detail,
            "",
            "请仓储→生产/财务/使用部门确认处置。",
        ]
    return {"title": title_map.get(et, "五金库预警"), "content": "\n".join(lines)}


async def hardware_urge(task_dict: dict[str, Any], inputs: list[dict[str, Any]]) -> Report:
    """催办卡执行器：payload→卡→outbox（chat_id 行内权威；空配置跳过）。"""
    from app.core.database import async_session_factory
    from app.platform.superagent.effects import enqueue_outbox_message

    task_id = uuid.UUID(str(task_dict["id"]))
    async with async_session_factory() as session:
        payload = await _origin_payload(session, task_dict)
        event_type = str(payload.get("event_type") or "")
        external_id = str(payload.get("external_id") or task_dict["id"])
        if not event_type:
            await session.commit()
            return Report(kind="failed", end_task=True, note="origin payload 缺 event_type")

        chat_id = _urge_chat_id()
        if not chat_id:
            await session.commit()
            return Report(
                kind="ready", end_task=True,
                note="催办群未配置（WAREHOUSE_HARDWARE_ALERT_CHAT_ID/WAREHOUSE_TEST_CHAT_ID），跳过发送",
                output={"event_type": event_type, "skipped": True},
            )
        await enqueue_outbox_message(
            session,
            conversation=f"hw_urge:{external_id}",
            channel={"type": "feishu_card", "chat_id": chat_id},
            purpose="hardware_urge",
            task_id=task_id,
            body=_build_urge_body(payload),
        )
        await session.commit()
    logger.info("hardware_urge 已入队: %s", external_id)
    return Report(kind="ready", end_task=True, output={"event_type": event_type})


async def fetch_digest_numbers(
    session: Any, *, now: datetime | None = None, days: int = 1
) -> dict[str, Any]:
    """日/周速递结构化数字（全部 SQL 聚合；数字永不由 LLM 生成）。

    days=1 日报 / days=7 周报（任务书「日/周报速递格」）。
    """
    from datetime import timedelta as _td

    from app.modules.warehouse.hardware.models import (
        HardwareMaterial,
        HardwareReceipt,
        HardwareReceiptItem,
        HardwareRequisition,
        HardwareRequisitionItem,
    )

    now = now or _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - _td(days=days - 1)

    receipts_today = await session.scalar(
        select(func.count()).select_from(HardwareReceipt).where(
            HardwareReceipt.accepted_at.isnot(None),
            HardwareReceipt.accepted_at >= day_start,
            HardwareReceipt.is_deleted.is_(False),
        )
    )
    from app.modules.warehouse.hardware.models import HardwareMovement

    outbound_today = await session.scalar(
        select(func.count()).select_from(HardwareMovement).where(
            HardwareMovement.direction == "outbound",
            HardwareMovement.business_type.in_(("req_issue", "urgent_issue")),
            HardwareMovement.occurred_at >= day_start,
            HardwareMovement.is_deleted.is_(False),
        )
    )
    outbound_qty_today = await session.scalar(
        select(func.coalesce(func.sum(HardwareMovement.quantity), 0)).where(
            HardwareMovement.direction == "outbound",
            HardwareMovement.business_type.in_(("req_issue", "urgent_issue")),
            HardwareMovement.occurred_at >= day_start,
            HardwareMovement.is_deleted.is_(False),
        )
    )
    to_issue = await session.scalar(
        select(func.count()).select_from(HardwareRequisition).where(
            HardwareRequisition.status == "approved",
            HardwareRequisition.is_deleted.is_(False),
        )
    )
    urgent_overdue = await session.scalar(
        select(func.count()).select_from(HardwareRequisition).where(
            HardwareRequisition.status == "overdue_unpatched",
            HardwareRequisition.is_deleted.is_(False),
        )
    )
    draft_backlog = await session.scalar(
        select(func.count()).select_from(HardwareReceipt).where(
            HardwareReceipt.status == "draft",
            HardwareReceipt.is_deleted.is_(False),
        )
    )
    # 低库存数（available < safety）
    on_hand = (
        select(
            HardwareReceiptItem.material_id.label("m"),
            func.sum(HardwareReceiptItem.remaining_quantity).label("q"),
        )
        .select_from(HardwareReceiptItem)
        .join(HardwareReceipt, HardwareReceipt.id == HardwareReceiptItem.receipt_id)
        .where(
            HardwareReceipt.status == "accepted",
            HardwareReceipt.is_deleted.is_(False),
            HardwareReceiptItem.is_deleted.is_(False),
            HardwareReceiptItem.remaining_quantity.isnot(None),
        )
        .group_by(HardwareReceiptItem.material_id)
        .subquery()
    )
    reserved = (
        select(
            HardwareRequisitionItem.material_id.label("m"),
            func.sum(HardwareRequisitionItem.need_qty).label("q"),
        )
        .select_from(HardwareRequisitionItem)
        .join(HardwareRequisition, HardwareRequisition.id == HardwareRequisitionItem.requisition_id)
        .where(
            HardwareRequisition.status.in_(("pending", "approved")),
            HardwareRequisition.is_deleted.is_(False),
            HardwareRequisitionItem.is_deleted.is_(False),
        )
        .group_by(HardwareRequisitionItem.material_id)
        .subquery()
    )
    low_count = await session.scalar(
        select(func.count()).select_from(
            select(HardwareMaterial.id)
            .outerjoin(on_hand, on_hand.c.m == HardwareMaterial.id)
            .outerjoin(reserved, reserved.c.m == HardwareMaterial.id)
            .where(
                HardwareMaterial.is_deleted.is_(False),
                HardwareMaterial.active.is_(True),
                HardwareMaterial.managed_class == "stocked",
                (func.coalesce(on_hand.c.q, 0) - func.coalesce(reserved.c.q, 0))
                < HardwareMaterial.safety_stock,
            )
            .subquery()
        )
    )
    # M9 自动入账披露（本周 auto_accepted 单数；§9.3 放权观察口径）
    auto_accepted_count = await session.scalar(
        select(func.count()).select_from(HardwareReceipt).where(
            HardwareReceipt.auto_accepted.is_(True),
            HardwareReceipt.accepted_at >= day_start,
            HardwareReceipt.is_deleted.is_(False),
        )
    )
    return {
        "date": now.strftime("%Y-%m-%d"),
        "days": days,
        "receipts_today": int(receipts_today or 0),
        "outbound_today": int(outbound_today or 0),
        "outbound_qty_today": float(outbound_qty_today or 0),
        "to_issue": int(to_issue or 0),
        "urgent_overdue": int(urgent_overdue or 0),
        "draft_backlog": int(draft_backlog or 0),
        "low_stock_count": int(low_count or 0),
        "auto_accepted_count": int(auto_accepted_count or 0),
    }


async def _digest_ai_summary(numbers: dict[str, Any]) -> str | None:
    """AI 总结文本（hardware_digest_summary 场景；失败/停用返回 None 不阻塞）。"""
    from app.modules.warehouse.ai_audit.context import warehouse_audit_scope

    prompt = (
        "你是五金仓库管理助理。以下是今日运营数字（系统流水聚合，不可更改）。"
        "请用 40-80 字总结今日动态与最需要关注的 1-2 件事，不要罗列全部数字。\n\n"
        + "\n".join(f"- {k}: {v}" for k, v in numbers.items())
    )
    try:
        from app.modules.warehouse.agent.llm_client import get_llm_client

        async with warehouse_audit_scope(
            "hardware_digest_summary", resource="digest_summary", channel="system",
        ):
            client = get_llm_client()
            content = await client.chat_with_tools(
                [{"role": "user", "content": prompt}],
                tools=None, temperature=0.3, max_tokens=512,
            )
        text = _assistant_text(content)
        return (text or "").strip()[:500] or None
    except Exception:  # noqa: BLE001
        logger.warning("速递 AI 总结失败（跳过，数字卡照发）")
        return None


def _assistant_text(message: Any) -> str | None:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "\n".join(p for p in parts if p) or None
    return None


async def hardware_digest_push(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]]
) -> Report:
    """日速递执行器：SQL 数字 + AI 总结（可选）→ push_center 推送卡。"""
    from app.core.database import async_session_factory
    from app.modules.warehouse.push_center.events import fire_push_event

    async with async_session_factory() as session:
        payload = await _origin_payload(session, task_dict)
        event_type = str(payload.get("event_type") or "daily_digest")
        days = 7 if event_type == "weekly_digest" else 1
        numbers = await fetch_digest_numbers(session, days=days)
        summary = await _digest_ai_summary(numbers)
        try:
            await fire_push_event(
                session, "hardware_digest", {
                    **numbers,
                    "frequency": "周报" if days == 7 else "日报",
                    "ai_summary": summary,
                },
            )
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
            logger.exception("hardware_digest 推送失败")
            return Report(kind="blocked", note="digest push 失败（见日志）")
    logger.info("hardware_digest_push 已推送: %s", numbers["date"])
    return Report(kind="ready", end_task=True, output=numbers)


async def hardware_plan_draft(
    task_dict: dict[str, Any], inputs: list[dict[str, Any]]
) -> Report:
    """计划草案执行器：调 M5 service（幂等；与 25 日 CRON 任务同一入口）。"""
    from app.core.database import async_session_factory
    from app.modules.warehouse.hardware import planning as pl

    async with async_session_factory() as session:
        payload = await _origin_payload(session, task_dict)
        plan_month = str(payload.get("plan_month") or pl.next_month())
        plan = await pl.generate_monthly_plan(session, plan_month)
        await session.commit()
    logger.info("hardware_plan_draft 草案就绪: %s（annotated=%s）", plan.plan_month, plan.annotated)
    return Report(
        kind="ready", end_task=True,
        output={"plan_month": plan.plan_month, "annotated": plan.annotated},
    )
