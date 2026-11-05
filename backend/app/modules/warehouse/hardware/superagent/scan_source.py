"""HardwareAlertScanSource —— 五金库预警 cron 门控扫描源（kind=hardware_alert_scan）。

照 R1 FireAlarmScanSource 模式（cron 门控 due_fire_times → 扫描 → drafts →
读位由 ingest 同事务承接）。每轮（默认每小时）产出：

- **五类事件**（§9.2，external_id 幂等=同事件二次触发不重复）：
  - low_stock:<material_id>:<YYYY-MM-DD>——available<safety_stock（按日键：
    当日恢复再击穿不重复，跨日再击穿=新事件）
  - urgent_unpatched:<req_id>——紧急 24h 未补单（overdue_unpatched 状态幂等闸）
  - draft_backlog:<YYYY-MM-DD>——OCR/手动草稿积压超阈值（config 可配默认 5）
  - issue_timeout:<req_id>——approved 超 48h 未发料
  - stale:<YYYY-Qn>——呆滞到期（仅季度首月前 7 天算一次，M5 扫描口径复算）
- **两个定时触发**：
  - daily_digest:<YYYY-MM-DD>——日速递（每日一轮，数字由执行器 SQL 聚合）
  - plan_draft:<YYYY-MM>——25 日后首轮触发 M5 计划草案（月键幂等；与 25 日
    CRON 任务同 service 幂等并存，SUPERAGENT_ENABLED=false 时功能不受损）

payload 全部结构化（数字=SQL 聚合，永不来自 LLM）；规则引擎只按
``payload.event_type`` 分流（rule.py），零文本判定。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.platform.scheduler import ScheduleConfig
from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import (
    DEFAULT_MAX_CATCHUP_SECONDS,
    PollResult,
    Source,
    TriggerDraft,
    due_fire_times,
)

logger = logging.getLogger(__name__)

#: 五金库预警源实例名（agent_sources.name；规则 source 过滤依据）
HARDWARE_ALERT_SOURCE_NAME = "warehouse.hardware_alert_scan"

#: 草稿积压默认阈值（config.draft_backlog_threshold 可覆写）
DEFAULT_DRAFT_BACKLOG_THRESHOLD = 5

#: 审批通过未发料超时阈值（小时）
ISSUE_TIMEOUT_HOURS = 48

ZERO = Decimal("0")
_TZ_SH = ZoneInfo("Asia/Shanghai")


def _stale_quarter_key(now: datetime) -> str | None:
    """呆滞触发窗：季度首月（1/4/7/10）前 7 天内返回季度键 'YYYY-Qn'。"""
    if now.month not in (1, 4, 7, 10) or now.day > 7:
        return None
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def _next_month_key(now: datetime) -> str:
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year:04d}-{month:02d}"


def _draft(
    event_type: str, external_id: str, payload: dict[str, Any]
) -> TriggerDraft:
    body = {"event_type": event_type, "external_id": external_id, **payload}
    return TriggerDraft(
        external_id=external_id,
        thread_key=f"hw:{event_type}:{external_id.split(':', 1)[1] if ':' in external_id else external_id}",
        actor={"id": external_id, "type": "system_scan"},
        human=False,
        addressed=False,
        payload=body,
    )


async def build_alert_drafts(
    session: Any, *, now: datetime, cfg: dict[str, Any]
) -> list[TriggerDraft]:
    """扫描五金库当前状态 → 五类事件 + digest/plan 定时 drafts。"""
    from app.modules.warehouse.hardware import planning as pl
    from app.modules.warehouse.hardware.models import (
        HardwareMaterial,
        HardwareReceipt,
        HardwareReceiptItem,
        HardwareRequisition,
        HardwareRequisitionItem,
    )

    drafts: list[TriggerDraft] = []
    today = now.strftime("%Y-%m-%d")

    # ── ① 安全库存击穿：available < safety_stock（active stocked）──
    on_hand = (
        select(
            HardwareReceiptItem.material_id.label("material_id"),
            func.sum(HardwareReceiptItem.remaining_quantity).label("qty"),
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
            HardwareRequisitionItem.material_id.label("material_id"),
            func.sum(HardwareRequisitionItem.need_qty).label("qty"),
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
    low_rows = (
        await session.execute(
            select(
                HardwareMaterial,
                func.coalesce(on_hand.c.qty, ZERO),
                func.coalesce(reserved.c.qty, ZERO),
            )
            .outerjoin(on_hand, on_hand.c.material_id == HardwareMaterial.id)
            .outerjoin(reserved, reserved.c.material_id == HardwareMaterial.id)
            .where(
                HardwareMaterial.is_deleted.is_(False),
                HardwareMaterial.active.is_(True),
                HardwareMaterial.managed_class == "stocked",
            )
        )
    ).all()
    for material, on, res in low_rows:
        available = (on or ZERO) - (res or ZERO)
        if available < material.safety_stock:
            drafts.append(_draft(
                "low_stock",
                f"low_stock:{material.id}:{today}",
                {
                    "material_id": str(material.id),
                    "code": material.code,
                    "name": material.name,
                    "spec": material.spec,
                    "unit": material.unit,
                    "on_hand": float(on or ZERO),
                    "reserved": float(res or ZERO),
                    "available": float(available),
                    "safety_stock": float(material.safety_stock),
                },
            ))

    # ── ② 紧急 24h 未补单（状态即幂等闸）──
    overdue = (
        await session.execute(
            select(HardwareRequisition).where(
                HardwareRequisition.status == "overdue_unpatched",
                HardwareRequisition.is_deleted.is_(False),
            ).limit(20)
        )
    ).scalars().all()
    for req in overdue:
        drafts.append(_draft(
            "urgent_unpatched",
            f"urgent_unpatched:{req.id}",
            {
                "req_no": req.req_no, "dept": req.dept_name, "applicant": req.applicant,
                "deadline": req.urgent_patch_deadline.isoformat() if req.urgent_patch_deadline else None,
            },
        ))

    # ── ③ 草稿积压（draft 单数 > 阈值，按日键）──
    threshold = int(cfg.get("draft_backlog_threshold", DEFAULT_DRAFT_BACKLOG_THRESHOLD))
    backlog = await session.scalar(
        select(func.count()).select_from(HardwareReceipt).where(
            HardwareReceipt.status == "draft",
            HardwareReceipt.is_deleted.is_(False),
        )
    )
    if (backlog or 0) > threshold:
        drafts.append(_draft(
            "draft_backlog",
            f"draft_backlog:{today}",
            {"count": int(backlog or 0), "threshold": threshold},
        ))

    # ── ④ 审批通过未发料超时（approved > 48h）──
    timeout_cut = now - timedelta(hours=ISSUE_TIMEOUT_HOURS)
    timeout_rows = (
        await session.execute(
            select(HardwareRequisition).where(
                HardwareRequisition.status == "approved",
                HardwareRequisition.approved_at.isnot(None),
                HardwareRequisition.approved_at < timeout_cut,
                HardwareRequisition.is_deleted.is_(False),
            ).limit(20)
        )
    ).scalars().all()
    for req in timeout_rows:
        drafts.append(_draft(
            "issue_timeout",
            f"issue_timeout:{req.id}",
            {
                "req_no": req.req_no, "dept": req.dept_name, "applicant": req.applicant,
                "approved_at": req.approved_at.isoformat() if req.approved_at else None,
                "hours": round((now - req.approved_at).total_seconds() / 3600, 1) if req.approved_at else None,
            },
        ))

    # ── ⑤ 呆滞到期（季度首月前 7 天一次；M5 扫描口径复算）──
    quarter_key = _stale_quarter_key(now)
    if quarter_key is not None:
        stale = await pl.scan_stale_materials(session, now=now)
        if stale:
            drafts.append(_draft(
                "stale",
                f"stale:{quarter_key}",
                {"count": len(stale), "items": stale[:10], "quarter": quarter_key},
            ))

    # ── 定时触发：日速递（每日一轮，执行器聚数字）──
    drafts.append(_draft("daily_digest", f"daily_digest:{today}", {"date": today}))

    # ── 定时触发：25 日后首轮计划草案（月键幂等）──
    if now.day >= 25:
        plan_month = _next_month_key(now)
        drafts.append(_draft("plan_draft", f"plan_draft:{plan_month}", {"plan_month": plan_month}))

    return drafts


class HardwareAlertScanSource(Source):
    """五金库预警 cron 门控扫描源（warehouse 侧定义，SourceRegistry 注册制挂入）。"""

    kind = "hardware_alert_scan"

    async def poll(
        self,
        session: Any,
        source_row: AgentSource,
        cursors: dict[str, Any],
    ) -> PollResult:
        cfg = source_row.config or {}
        schedule = ScheduleConfig(**(cfg.get("schedule") or {
            "strategy": "interval", "interval_seconds": 3600,
        }))
        tz = ZoneInfo(schedule.timezone)
        now = datetime.now(tz)
        max_catchup = int(cfg.get("max_catchup_seconds", DEFAULT_MAX_CATCHUP_SECONDS))

        last_raw = cursors.get("last_tick")
        if isinstance(last_raw, dict):
            last_raw = last_raw.get("value")
        if not last_raw:
            return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
        last = datetime.fromisoformat(str(last_raw))

        fires = due_fire_times(schedule, last, now, max_catchup_seconds=max_catchup)
        if not fires:
            if (now - last).total_seconds() > max_catchup:
                return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
            return PollResult()

        drafts = await build_alert_drafts(session, now=now, cfg=cfg)
        logger.info(
            "hardware_alert_scan 一轮：%d drafts（读位推进至 %s）",
            len(drafts), fires[-1].isoformat(),
        )
        return PollResult(drafts=drafts, cursor_updates={"last_tick": fires[-1].isoformat()})
