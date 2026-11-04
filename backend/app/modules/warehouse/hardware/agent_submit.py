"""五金库 agent 确认提交（scene=hardware_receipt 的 submit 回调真身）。

确认卡点「确认入账」→ 本模块把 hardware_receipts 草稿 accept（库存唯一
增点：批次/双流水/direct 领取卡推送全在 service.accept_receipt 内），
再读回核对 → draft submitted。双签口径（制度 5.2.2）：
- 仓管员 = 卡片确认人（confirm.handle_action 的 operator_open_id，存
  draft.updated 追记不可得——以草稿发起人兜底，卡片确认人落审计）；
- 使用部门经办 = 草稿发起人（图片上传者）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.agent.pipeline.draft_flow import DraftFlowError
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.hardware import service as hw_service
from app.modules.warehouse.hardware.models import HardwareReceipt

logger = logging.getLogger(__name__)


async def submit_hardware_receipt(
    db: AsyncSession, draft: Any
) -> str | None:
    """confirmed → 入库单 accepted → draft submitted（读回核对）。"""
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    receipt_id = str(aligned.get("receipt_id") or "")
    if not receipt_id:
        raise DraftFlowError("草稿缺少入库单引用（receipt_id），请重新发起识别")
    import uuid as _uuid

    receipt = await db.get(HardwareReceipt, _uuid.UUID(receipt_id))
    if receipt is None:
        raise DraftFlowError("入库单不存在（可能已被处理删除），请重新发起识别")
    if receipt.status != "draft":
        # 幂等：已入账/拒收的单不再重复处理，草稿直接闭环
        await agent_repository.set_agent_draft_status(db, draft, "submitted")
        return f"入库单 {receipt.receipt_no} 已是 {receipt.status} 状态，无需重复处理"

    # 草稿模型只有发起人 open_id；确认人经卡片审计留痕，此处双签兜底同源
    creator_open_id = (draft.created_by_open_id or "unknown")
    operator_open_id = creator_open_id

    await hw_service.accept_receipt(
        db,
        receipt.id,
        inspected_by_warehouse=operator_open_id,
        inspected_by_dept=creator_open_id,
        user=None,
    )
    await db.flush()

    # 读回核对
    await db.refresh(receipt)
    if receipt.status != "accepted":
        raise DraftFlowError(
            f"入账读回核对失败：{receipt.receipt_no} 状态 {receipt.status}"
        )
    await agent_repository.set_agent_draft_status(db, draft, "submitted")
    logger.info(
        "五金入库 agent 提交完成: draft=%s receipt=%s",
        draft.draft_no, receipt.receipt_no,
    )
    return (
        f"入库单 {receipt.receipt_no} 已入账"
        f"（{receipt.mode}，批次与流水已生成）"
    )
