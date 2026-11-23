"""五金库紧急领料加急通知（2026-11-20 改版）。

紧急领料不再有独立「先发后补」流程：申请人在「福兴电子领/退料单审批」表单
选「是否紧急=是」+ 填「紧急原因」（前端申领同构），审批单据本身即闭环手续。
紧急单与普通单同走审批链，唯一差异=仓管可审批前发料（先发后批，
service.issue_requisition 门：pending+urgent 放行）。

本模块只剩一件事：紧急单建单（pending 预扣）后把「紧急」显性化给仓管——
私发加急卡（通知目标 env 配置），提示可提前发料。审批通过自动发料走既有链。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.warehouse.feishu.notification import send_card_to_target
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareRequisition,
    HardwareRequisitionItem,
)

logger = logging.getLogger(__name__)


def get_urgent_notify_targets() -> list[str]:
    """仓管通知目标（env 逗号分隔 open_id/chat_id；默认许康福）。"""
    raw = get_settings().HARDWARE_URGENT_NOTIFY_TARGETS or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


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


def build_urgent_notice_card(req: HardwareRequisition, items_md: str) -> dict[str, Any]:
    """仓管加急卡：紧急领料已建单预扣，可审批前发料（先发后批）。"""
    content = (
        f"**单号**：{req.req_no}\n"
        f"**部门**：{req.dept_name}\n"
        f"**申请人**：{req.applicant}\n"
        f"**紧急原因**：{req.urgent_reason or req.purpose or '（未填）'}\n\n"
        f"**物资明细**\n{items_md}\n\n---\n"
        "已建单预扣，审批加急中。**紧急单可在审批通过前发料**："
        "五金库领用中心行内「发料」即可（先发后批，审批通过自动对账闭环）；"
        "普通单仍须等审批通过。"
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🔴 紧急领料·待发料"},
            "template": "red",
        },
        "body": {"elements": [{"tag": "markdown", "content": content}]},
    }


async def send_urgent_notice(db: AsyncSession, req: HardwareRequisition) -> int:
    """建单后向仓管通知目标私发加急卡（best-effort，返回送达数）。"""
    if req.req_type != "urgent":
        return 0
    items_md = await _items_lines(db, req)
    sent = 0
    for target in get_urgent_notify_targets():
        try:
            await send_card_to_target(target, build_urgent_notice_card(req, items_md))
            sent += 1
        except Exception:  # noqa: BLE001 — 通知失败不影响建单主流程
            logger.warning(
                "[紧急领料] 加急卡发送失败: %s target=%s", req.req_no, target[:20], exc_info=True
            )
    return sent
