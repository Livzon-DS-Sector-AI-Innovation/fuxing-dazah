"""五金库退料流程服务（2026-11-26：从已发料领料单发起退料，走审批）。

状态机（与 approval_channel 区分新老链路；channel 为空=老登记/飞书自建链路，
行为不变）：

    draft（平台发起的草稿，提交即发起审批）
      → submit → pending（待审批：飞书「五金库退料-平台」分支审批单发给所选
        审批人；未配置分支=manual，审批人在平台点通过）
      → approve → approved（待验收：审批人同意——飞书回流或平台「通过」）
      → accept → accepted（仓管验收回加，物料回库存；复用 stocktake.accept_return）
    pending/approved 可驳回 → rejected；draft/pending 可撤回 → cancelled。
    老链路（channel 为空）：draft=待签收验收 → accepted/rejected 不变。

额度校验（货对板）：退量 ≤ Σ实发量 − 已退量（draft+pending+approved+accepted
归集），create 与 submit 双卡点；实现从 approval_ingest._validate_return_rows
提炼为公共函数，摄取链路与平台链路同口径。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware import service as hw
from app.modules.warehouse.hardware.models import (
    HardwareMaterial,
    HardwareRequisition,
    HardwareRequisitionItem,
    HardwareReturn,
)

logger = logging.getLogger(__name__)

CN_TZ = ZoneInfo("Asia/Shanghai")
ZERO = Decimal("0")

RETURN_MANAGE_PERM = "warehouse:hardware:return:manage"
# 额度归集口径：占额度的在途/已回加态（老 draft 与新 pending/approved 都占）
_RESERVING_STATUSES = ("draft", "pending", "approved", "accepted")


def _now() -> datetime:
    return datetime.now(CN_TZ)


def can_user_approve_return(ret: HardwareReturn, *, user: Any, perms: set[str]) -> bool:
    """平台「通过 / 驳回」资格：持「退料管理」权限，或被选为该单审批人。"""
    if RETURN_MANAGE_PERM in perms:
        return True
    if user is None or not ret.approver_user_id:
        return False
    return str(getattr(user, "feishu_user_id", "") or "") == str(ret.approver_user_id)


# ── 额度校验（公共口径；摄取与平台链路共用）──


async def collect_requisition_quota(
    db: AsyncSession, requisition: HardwareRequisition
) -> dict[str, float]:
    """领料单可退额度底账：{material_id(str): {'issued': Σ实发, 'returned': Σ已退/在退}}。"""
    issued: dict[str, float] = {}
    items = (
        await db.execute(
            select(HardwareRequisitionItem).where(
                HardwareRequisitionItem.requisition_id == requisition.id,
                HardwareRequisitionItem.is_deleted.is_(False),
            )
        )
    ).scalars().all()
    for it in items:
        key = str(it.material_id)
        qty = it.issued_qty if it.issued_qty is not None else it.need_qty
        issued[key] = issued.get(key, 0) + float(qty or 0)

    returned: dict[str, float] = {}
    linked_code = requisition.approval_instance_code
    stmt = select(HardwareReturn).where(
        HardwareReturn.status.in_(_RESERVING_STATUSES),
        HardwareReturn.is_deleted.is_(False),
        or_(
            HardwareReturn.requisition_id == requisition.id,
            *(
                [HardwareReturn.requisition_instance_code == linked_code]
                if linked_code
                else []
            ),
            text("hardware_returns.items @> :jq"),
        ),
    )
    params: dict[str, Any] = {}
    if linked_code:
        params["jq"] = json.dumps([{"linked_code": linked_code}])
    else:
        params["jq"] = json.dumps([{"linked_code": requisition.id}])
    prior = (await db.execute(stmt, params)).scalars().all()
    for ret in prior:
        doc_link_req = ret.requisition_id
        doc_link_code = ret.requisition_instance_code
        for row in ret.items or []:
            row_link = str(row.get("linked_code") or "")
            hit = (
                row_link == (linked_code or "")
                or (not row_link and (doc_link_req == requisition.id
                                      or (bool(linked_code) and doc_link_code == linked_code)))
            )
            if not hit:
                continue
            key = str(row.get("material_id") or "")
            returned[key] = returned.get(key, 0) + float(row.get("quantity") or 0)

    return {
        key: {"issued": issued[key], "returned": returned.get(key, 0)}
        for key in issued
    }


async def validate_return_quota(
    db: AsyncSession,
    requisition: HardwareRequisition,
    rows: list[dict[str, Any]],
    *,
    exclude_return_id: UUID | None = None,
) -> str:
    """平台退料额度校验：rows=[{material_id, quantity}]，返回问题文案，空串=通过。

    卡点：领料单须已发料；退料物资须在领料明细内；逐料
    退量 ≤ Σ实发 − 已退/在退（本单行内亦累积，exclude_return_id 排除自身重校验）。
    """
    problems: list[str] = []
    if requisition.status != "issued":
        return f"领料单 {requisition.req_no} 状态为 {requisition.status}（须已发料才可退料）"

    quota = await collect_requisition_quota(db, requisition)
    if exclude_return_id is not None:
        # 重校验（提交时）：把自身已占额度从底账里扣除
        own = await db.get(HardwareReturn, exclude_return_id)
        if own is not None and own.status in _RESERVING_STATUSES:
            for row in own.items or []:
                key = str(row.get("material_id") or "")
                if key in quota:
                    quota[key]["returned"] -= float(row.get("quantity") or 0)

    cumulative: dict[str, float] = {}
    for i, r in enumerate(rows):
        key = str(r.get("material_id") or "")
        q = float(r.get("quantity") or 0)
        base = quota.get(key)
        if base is None:
            material = await db.get(HardwareMaterial, UUID(key)) if key else None
            problems.append(
                f"第{i + 1}行 {r.get('name') or (material.name if material else key)}"
                f" 不在领料单 {requisition.req_no} 明细中"
            )
            continue
        already = base["returned"] + cumulative.get(key, 0)
        remain = base["issued"] - already
        if q > remain + 1e-9:
            problems.append(
                f"第{i + 1}行 {r.get('name')} 退 {q:g} 超可退 {remain:g}"
                f"（实发 {base['issued']:g}，已退/在退 {already:g}，单 {requisition.req_no}）"
            )
        cumulative[key] = already + q
    return "；".join(problems)


# ── 平台发起链路 ──


async def create_return_from_requisition(
    db: AsyncSession,
    requisition_id: UUID,
    *,
    returned_by: str,
    approver_user_id: str | None = None,
    approver_name: str | None = None,
    items: list[dict[str, Any]],
    reason_note: str | None = None,
    user: Any = None,
) -> HardwareReturn:
    """从已发料领料单建退料草稿（不动账）：行快照+发料批次预填+额度校验。"""
    req = await db.get(HardwareRequisition, requisition_id)
    if req is None or req.is_deleted:
        raise hw.HardwareError("领料单不存在", status_code=404)
    if req.status != "issued":
        raise hw.HardwareError(
            f"领料单 {req.req_no} 状态为 {req.status}（须已发料才可退料）", status_code=422
        )

    rows: list[dict[str, Any]] = []
    for raw in items or []:
        qty = Decimal(str(raw.get("quantity")))
        if qty <= ZERO:
            raise hw.HardwareError("退料数量必须大于 0", status_code=422)
        material = await db.get(HardwareMaterial, UUID(str(raw.get("material_id"))))
        if material is None:
            raise hw.HardwareError(f"物料不存在: {raw.get('material_id')}", status_code=404)
        rows.append({
            "material_id": str(material.id),
            "code": material.code,
            "name": material.name,
            "spec": material.spec,
            "unit": material.unit,
            "quantity": float(qty),
            # 预填发料批次（可退回原批次）；空=验收时新建 return 批次
            "preferred_lot_id": raw.get("preferred_lot_id"),
            "linked_code": req.approval_instance_code or str(req.id),
        })
    if not rows:
        raise hw.HardwareError("退料单无明细行", status_code=422)

    problem = await validate_return_quota(db, req, rows)
    if problem:
        raise hw.HardwareError(problem, status_code=422)

    ret = HardwareReturn(
        return_no=await hw.generate_doc_no(
            db, HardwareReturn, "WJK-TK", column=HardwareReturn.return_no
        ),
        requisition_id=req.id,
        requisition_instance_code=req.approval_instance_code,
        approver_user_id=approver_user_id,
        approver_name=approver_name,
        dept_name=req.dept_name,
        returned_by=returned_by or req.applicant,
        returned_by_open_id=req.applicant_open_id,
        items=rows,
        status="draft",
        remark=reason_note,
        created_by=getattr(user, "id", None) if user is not None else None,
    )
    db.add(ret)
    await db.flush()
    return ret


async def get_return(db: AsyncSession, return_id: UUID) -> HardwareReturn:
    ret = await db.get(HardwareReturn, return_id)
    if ret is None:
        raise hw.HardwareError("退料单不存在", status_code=404)
    return ret


async def submit_return(
    db: AsyncSession, return_id: UUID, *, user: Any = None
) -> HardwareReturn:
    """draft → pending：提交即发起审批（飞书分支已配置=发审批单给所选审批人，
    失败上抛停在 draft 不降级；未配置=manual 平台点通过），提交前额度重校验。"""
    from app.modules.warehouse.hardware.approval_channel import (
        ApprovalChannelError,
        get_return_approval_channel,
    )

    ret = await get_return(db, return_id)
    if ret.status != "draft":
        raise hw.HardwareError(f"退料单状态 {ret.status} 不可提交（仅草稿可提交）")
    if ret.requisition_id is None:
        raise hw.HardwareError("该退料单不是从领料单发起的（走原登记/签收验收链路）")

    req = await db.get(HardwareRequisition, ret.requisition_id)
    if req is None:
        raise hw.HardwareError("关联领料单不存在", status_code=404)
    problem = await validate_return_quota(db, req, ret.items or [], exclude_return_id=ret.id)
    if problem:
        raise hw.HardwareError(f"提交失败：{problem}", status_code=422)

    channel = get_return_approval_channel()
    if channel is not None:
        if not str(ret.approver_user_id or "").strip():
            raise hw.HardwareError(
                "未选择审批人（主管及以上），请重新发起并选择审批人", status_code=422
            )
        try:
            ref = await channel.submit_return(db, ret, req)
        except ApprovalChannelError as exc:
            logger.exception("五金退料审批发起失败: return=%s", ret.return_no)
            raise hw.HardwareError(
                f"飞书审批发起失败，单据已留在草稿可重试：{exc}", status_code=502
            ) from exc
        logger.info("五金退料审批已提交: return=%s channel=feishu ref=%s", ret.return_no, ref)
    else:
        ret.approval_channel = "manual"
        ret.approval_status = "pending"
        logger.info("五金退料审批走平台通过: return=%s", ret.return_no)

    ret.status = "pending"
    if user is not None and hasattr(user, "id"):
        ret.updated_by = user.id
    await db.flush()
    return ret


async def approve_return(
    db: AsyncSession, return_id: UUID, *, approved_by: str, user: Any = None,
    withdraw_instance: bool = False,
) -> HardwareReturn:
    """pending → approved：审批人同意（飞书回流/平台通过共用），不动账。

    审批人同意视同部门负责人签收（leader_signed），仓管验收前置即满足。
    """
    from app.modules.warehouse.hardware.approval_channel import cancel_return_approval

    ret = await get_return(db, return_id)
    if ret.status != "pending":
        raise hw.HardwareError(f"退料单状态 {ret.status} 不可审批通过（仅待审批可通过）")
    if withdraw_instance and ret.approval_status == "pending":
        await cancel_return_approval(db, ret)
    ret.status = "approved"
    ret.approval_status = "approved"
    # 审批人同意视同部门负责人签收（验收前置）；同意人记在签收人 + 备注留痕
    if not ret.leader_signed:
        ret.leader_signed = True
        ret.leader_signed_by = approved_by
        ret.leader_signed_at = _now()
    ret.remark = f"{ret.remark or ''}；审批通过：{approved_by}".strip("；")
    if user is not None and hasattr(user, "id"):
        ret.updated_by = user.id
    await db.flush()
    return ret


async def reject_return(
    db: AsyncSession, return_id: UUID, *, rejected_by: str, reason: str,
    user: Any = None, withdraw_instance: bool = False,
) -> HardwareReturn:
    """pending/approved → rejected：驳回留证不动账（pending 驳回=审批否，
    approved 驳回=拒退），pending 时尽力撤回飞书实例。"""
    from app.modules.warehouse.hardware.approval_channel import cancel_return_approval

    ret = await get_return(db, return_id)
    if ret.status not in ("pending", "approved"):
        raise hw.HardwareError(f"退料单状态 {ret.status} 不可驳回")
    if withdraw_instance and ret.approval_status == "pending":
        await cancel_return_approval(db, ret)
    ret.status = "rejected"
    ret.approval_status = "rejected"
    ret.rejected_by = rejected_by
    ret.rejected_reason = reason
    if user is not None and hasattr(user, "id"):
        ret.updated_by = user.id
    await db.flush()
    return ret


async def cancel_return(db: AsyncSession, return_id: UUID) -> HardwareReturn:
    """draft/pending → cancelled：发起人撤回（尽力撤回飞书实例）。"""
    from app.modules.warehouse.hardware.approval_channel import cancel_return_approval

    ret = await get_return(db, return_id)
    if ret.status not in ("draft", "pending"):
        raise hw.HardwareError(f"退料单状态 {ret.status} 不可撤回")
    if ret.approval_status == "pending":
        await cancel_return_approval(db, ret)
    ret.status = "cancelled"
    await db.flush()
    return ret
