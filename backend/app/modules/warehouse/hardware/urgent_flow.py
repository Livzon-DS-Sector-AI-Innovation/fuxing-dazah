"""五金库紧急领用（先发后补，制度 5.3.4）卡片与仓管卡动作。

链路：对话/前端建 urgent 单（pending 预扣）→ `send_urgent_cards` 双卡
（申请人临时单据卡 + 仓管通知目标带按钮卡）→ 仓管点「发料出库/作废」→
`handle_keeper_action`（鉴权 fail-closed：操作人须属通知目标）FIFO 实扣
或释放预扣，并私发申请人结果卡。24h 补办跟进见 scheduled 巡检与
approval_ingest 补办自动匹配。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.time import APP_TZ
from app.modules.warehouse.feishu.notification import (
    send_card_to_target,
    send_card_to_user,
)
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareRequisition,
    HardwareRequisitionItem,
)

logger = logging.getLogger(__name__)

# 仓管卡按钮场景值（gateway card.action.trigger 按 scene 分发）
URGENT_ISSUE_SCENE = "hardware_urgent_issue"
URGENT_CANCEL_SCENE = "hardware_urgent_cancel"

PATCH_HINT = (
    "请在仓管发料后 **24 小时内** 在飞书提交「福兴电子领/退料单审批」"
    "（选领料、同物资同数量）完成补办；逾期未补办仓储部有权暂停本部门领用。"
)


def get_urgent_notify_targets() -> list[str]:
    """仓管通知目标（env 逗号分隔 open_id/chat_id；默认许康福）。"""
    raw = get_settings().HARDWARE_URGENT_NOTIFY_TARGETS or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


def _fmt(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    return dt.astimezone(APP_TZ).strftime("%m-%d %H:%M")


async def _items_lines(db: AsyncSession, req: HardwareRequisition) -> str:
    """明细行（发料前=need_qty，发料后=issued_qty）。"""
    rows = (
        await db.execute(
            select(HardwareRequisitionItem, HardwareMaterial)
            .join(HardwareMaterial, HardwareMaterial.id == HardwareRequisitionItem.material_id)
            .where(HardwareRequisitionItem.requisition_id == req.id)
        )
    ).all()
    return "\n".join(
        f"· {m.name} {m.spec or ''} x{it.issued_qty if it.issued_qty is not None else it.need_qty:g} {m.unit}"
        for it, m in rows
    ) or "（无明细）"


def _card(title: str, template: str, content: str,
          buttons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    elements: list[dict[str, Any]] = [{"tag": "markdown", "content": content}]
    if buttons:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "column_set",
            "flex_mode": "bisect",
            "columns": [
                {"tag": "column", "width": "weighted", "weight": 1, "elements": [btn]}
                for btn in buttons
            ],
        })
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "body": {"elements": elements},
    }


def _button(label: str, scene: str, requisition_id: UUID, btype: str = "default") -> dict[str, Any]:
    value = {"scene": scene, "requisition_id": str(requisition_id)}
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": btype,
        "value": value,
        "behaviors": [{"type": "callback", "value": value}],
    }


def _head_lines(req: HardwareRequisition, items_md: str) -> str:
    return (
        f"**单号**：{req.req_no}\n"
        f"**部门**：{req.dept_name}\n"
        f"**申请人**：{req.applicant}\n"
        f"**用途**：{req.purpose or '（未填）'}\n\n"
        f"**物资明细**\n{items_md}"
    )


def build_temp_doc_card(req: HardwareRequisition, items_md: str) -> dict[str, Any]:
    """申请人临时领料单据卡（领料凭证 + 24h 补办指引）。"""
    return _card(
        "🧾 五金库紧急领用·临时单据",
        "orange",
        f"{_head_lines(req, items_md)}\n\n---\n请凭本单据到五金库找仓管员领料。{PATCH_HINT}",
    )


def build_keeper_card(req: HardwareRequisition, items_md: str) -> dict[str, Any]:
    """仓管通知卡（带发料出库/作废按钮）。"""
    return _card(
        "🔴 五金库紧急领用·待发料",
        "red",
        (
            f"{_head_lines(req, items_md)}\n\n"
            "请核对物资后点「发料出库」（FIFO 实扣并开始 24h 补办计时）；"
            "误发起/无货点「作废」释放预扣。"
        ),
        buttons=[
            _button("✅ 发料出库", URGENT_ISSUE_SCENE, req.id, btype="primary"),
            _button("❌ 作废", URGENT_CANCEL_SCENE, req.id),
        ],
    )


def build_issued_card(req: HardwareRequisition, items_md: str) -> dict[str, Any]:
    """申请人出库确认卡（含补办截止时间）。"""
    return _card(
        "✅ 紧急领用已出库",
        "green",
        (
            f"你的紧急领用单 **{req.req_no}** 已发料出库：\n\n{items_md}\n\n"
            f"**补办截止**：{_fmt(req.urgent_patch_deadline)}（发料后 24 小时）\n\n{PATCH_HINT}"
        ),
    )


def build_cancelled_card(req: HardwareRequisition) -> dict[str, Any]:
    """申请人作废通知卡。"""
    return _card(
        "⚠️ 紧急领用已作废",
        "grey",
        (
            f"你的紧急领用单 **{req.req_no}** 已被仓管作废（预扣已释放）。"
            "如仍需领料请重新发起，或走正常领料审批。"
        ),
    )


def build_patch_reminder_card(req: HardwareRequisition, remain_hours: float) -> dict[str, Any]:
    """补办催办卡（T-12h/T-2h，巡检任务私发申请人）。"""
    remain = (
        f"{remain_hours:g} 小时" if remain_hours >= 1 else f"{remain_hours * 60:g} 分钟"
    )
    return _card(
        "⏰ 紧急领用补办提醒",
        "orange",
        (
            f"你的紧急领用单 **{req.req_no}** 距补办截止仅剩 **{remain}**。\n\n{PATCH_HINT}"
        ),
    )


async def send_patch_reminder(
    req: HardwareRequisition, *, deadline: datetime, now: datetime
) -> bool:
    """私发申请人催办卡（best-effort；缺 open_id 返回 False 由调用方记标签防重试刷屏）。"""
    if not req.applicant_open_id:
        logger.warning("[紧急领用] 申请人缺 open_id，催办卡未发: %s", req.req_no)
        return False
    remain = (deadline - now).total_seconds() / 3600
    try:
        await send_card_to_user(req.applicant_open_id, build_patch_reminder_card(req, remain))
        return True
    except Exception:  # noqa: BLE001 — 催办失败不影响巡检主流程
        logger.warning("[紧急领用] 催办卡发送失败: %s", req.req_no, exc_info=True)
        return False


async def send_urgent_cards(db: AsyncSession, req: HardwareRequisition) -> dict[str, int]:
    """建单后双卡：申请人临时单据卡（私发）+ 仓管通知目标各一张（best-effort）。"""
    items_md = await _items_lines(db, req)
    sent = {"applicant": 0, "keeper": 0}
    if req.applicant_open_id:
        try:
            await send_card_to_user(req.applicant_open_id, build_temp_doc_card(req, items_md))
            sent["applicant"] = 1
        except Exception:  # noqa: BLE001 — 卡片失败不影响建单主流程
            logger.warning("[紧急领用] 临时单据卡发送失败: %s", req.req_no, exc_info=True)
    for target in get_urgent_notify_targets():
        try:
            await send_card_to_target(target, build_keeper_card(req, items_md))
            sent["keeper"] += 1
        except Exception:  # noqa: BLE001
            logger.warning(
                "[紧急领用] 仓管卡发送失败: %s target=%s", req.req_no, target[:20], exc_info=True
            )
    return sent


async def _notify_applicant(req: HardwareRequisition, card: dict[str, Any]) -> None:
    if not req.applicant_open_id:
        return
    try:
        await send_card_to_user(req.applicant_open_id, card)
    except Exception:  # noqa: BLE001
        logger.warning("[紧急领用] 申请人结果卡发送失败: %s", req.req_no, exc_info=True)


async def _has_issue_permission(db: AsyncSession, open_id: str) -> bool:
    """open_id → identity 用户 → 是否持发料权限（fail-closed：查不到即无）。"""
    from app.platform.identity.models import User as IdentityUser
    from app.platform.permission.deps import get_user_permissions

    user_id = await db.scalar(
        select(IdentityUser.id).where(
            IdentityUser.feishu_open_id == open_id, IdentityUser.is_deleted.is_(False)
        )
    )
    if user_id is None:
        return False
    try:
        perms = await get_user_permissions(str(user_id), db)
    except Exception:  # noqa: BLE001 — 权限查询失败按无权处理（fail-closed）
        logger.warning("[紧急领用] 权限查询失败按无权: %s", open_id[:20], exc_info=True)
        return False
    return "warehouse:hardware:requisition:issue" in set(perms or ())


async def handle_keeper_action(
    db: AsyncSession,
    requisition_id: UUID | str,
    action: str,
    *,
    operator_open_id: str,
) -> tuple[bool, str]:
    """仓管卡按钮动作（gateway card.action.trigger 分发入口）。

    鉴权 fail-closed（spec 2026-11-19）：操作人属通知目标，**或**持发料权限
    （open_id→identity→permission 反查；查不到即拒）。发料=FIFO 实扣+24h 计时；
    作废=释放预扣；均为幂等守卫（状态机拦截）。不 commit（调用方会话统一提交）。
    """
    if operator_open_id not in get_urgent_notify_targets() and not await _has_issue_permission(
        db, operator_open_id
    ):
        logger.warning(
            "[紧急领用] 非授权人点击仓管卡: operator=%s req=%s",
            operator_open_id[:20], requisition_id,
        )
        return False, "仅仓管员（通知目标或持发料权限）可操作该卡片"
    try:
        rid = UUID(str(requisition_id))
    except ValueError:
        return False, "单据参数无效"
    req = await db.get(HardwareRequisition, rid)
    if req is None or req.is_deleted:
        return False, "单据不存在（可能已被处理）"

    if action == "issue":
        if req.req_type != "urgent":
            return False, "非紧急单不可走该通道"
        if req.status not in ("pending", "approved"):
            return False, f"单据状态 {req.status} 不可发料"
        try:
            await hw_service.issue_requisition(
                db,
                req.id,
                issued_by="仓管员·紧急领用卡",
                received_by=req.applicant or "领用人",
            )
        except hw_service.HardwareError as exc:
            return False, f"发料失败：{exc}"
        items_md = await _items_lines(db, req)
        await _notify_applicant(req, build_issued_card(req, items_md))
        return True, f"已发料出库 {req.req_no}；补办截止 {_fmt(req.urgent_patch_deadline)}"

    if action == "cancel":
        if req.status not in ("draft", "pending"):
            return False, f"单据状态 {req.status} 不可作废"
        await hw_service.cancel_requisition(db, req.id)
        await _notify_applicant(req, build_cancelled_card(req))
        return True, f"已作废 {req.req_no}，预扣已释放"

    return False, f"未知操作 {action}"
