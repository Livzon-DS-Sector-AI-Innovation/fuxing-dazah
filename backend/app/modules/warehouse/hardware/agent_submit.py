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
from app.modules.warehouse.hardware import urgent_flow
from app.modules.warehouse.hardware.models import HardwareReceipt
from app.modules.warehouse.hardware.schemas import (
    RequisitionCreate,
    RequisitionItemIn,
)

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


async def submit_hardware_urgent(db: AsyncSession, draft: Any) -> str | None:
    """scene=hardware_urgent 确认回调（制度 5.3.4 先发后补）。

    confirmed → 建 urgent 领料单 + 提交（pending 预扣，不走审批通道）→
    双卡（申请人临时单据卡 + 仓管通知目标带发料按钮卡）→ draft submitted。
    缺料（available 不足）抛 DraftFlowError：确认门置 failed 并提示，
    建出的单留在 draft 状态（未预扣，无副作用）。
    """
    aligned = draft.aligned if isinstance(draft.aligned, dict) else {}
    rows = aligned.get("items") or []
    if not rows:
        raise DraftFlowError("草稿缺少物资明细（items），请重新发起紧急领用")

    # 物资匹配（名称+规格=平台唯一键，与审批摄取同口径）
    matched: list[tuple[Any, float]] = []
    for r in rows:
        material = await hw_service.find_material_by_name_spec(
            db, str(r.get("name") or ""), str(r.get("spec") or "")
        )
        if material is None:
            raise DraftFlowError(
                f"物资不匹配：{r.get('name')} | {r.get('spec')}（以五金库目录名称+规格精确核对）"
            )
        matched.append((material, float(r.get("qty") or 0)))

    req = await hw_service.create_requisition(
        db,
        RequisitionCreate(
            dept_name=str(aligned.get("dept") or "未匹配部门"),
            applicant=str(aligned.get("applicant") or "未知申请人"),
            applicant_open_id=str(aligned.get("applicant_open_id") or "") or None,
            purpose=str(aligned.get("purpose") or "紧急领用（生产抢修）"),
            req_type="urgent",
            remark="紧急领用（对话确认门发起，先发后补）",
            items=[
                RequisitionItemIn(material_id=str(m.id), need_qty=str(q))  # type: ignore[arg-type]
                for m, q in matched
                if q > 0
            ],
        ),
    )
    try:
        await hw_service.submit_requisition(db, req.id)  # 预扣 + 超卖校验
    except hw_service.HardwareError as exc:
        req.status = "draft"  # 留痕不预扣
        req.remark = f"{req.remark or ''}；提交失败（缺料）：{exc}"
        await db.flush()
        raise DraftFlowError(f"紧急领用未受理（缺料）：{exc}") from exc

    sent = await urgent_flow.send_urgent_cards(db, req)
    await agent_repository.set_agent_draft_status(db, draft, "submitted")
    logger.info(
        "紧急领用 agent 提交完成: draft=%s req=%s cards=%s",
        draft.draft_no, req.req_no, sent,
    )
    return (
        f"紧急领用单 {req.req_no} 已建立（预扣生效），"
        f"已通知申请人({sent['applicant']})与仓管({sent['keeper']})，等待仓管发料出库"
    )
