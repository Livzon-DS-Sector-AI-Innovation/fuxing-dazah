"""劳动合同 HTTP 路由：台账 CRUD、续签、审批、盖章/领取、终止、公开签字。

本 router 挂在 hr 模块路由下（require_hr_basic 门禁 + _HR_PATH_PERMISSIONS
映射）；公开签字路由 sign_router 挂在全局 api_router（免登，token 即凭证）。
"""

import logging
from datetime import date, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.labor_contract import archive_service, renewal_approval, service
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import LaborContract
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-劳动合同"])

RESOURCE_TYPE = "hr_labor_contract"

# ─── 请求体 ───


class ContractCreateInput(BaseModel):
    employee_number: str = Field(..., max_length=32, description="工号")
    start_date: date = Field(..., description="合同起始日")
    sign_date: date | None = Field(None, description="实际签订日（缺省同起始日）")
    remark: str | None = Field(None, max_length=512)


class ContractUpdateInput(BaseModel):
    start_date: date | None = None
    sign_date: date | None = None
    position: str | None = Field(None, max_length=64)
    remark: str | None = Field(None, max_length=512)


class RenewInput(BaseModel):
    start_date: date = Field(..., description="新合同起始日（默认原到期日次日）")
    sign_date: date | None = None


class DecisionInput(BaseModel):
    decision: Literal["agree", "disagree"]


class TerminateInput(BaseModel):
    reason: str | None = Field(None, max_length=128)


# ─── 序列化 ───

_DECISION_LABELS: dict[str | None, str] = {"agree": "同意续签", "disagree": "不同意续签"}
_APPROVAL_MODE_LABELS: dict[str | None, str] = {"feishu": "飞书审批", "manual": "站内审批"}


def _contract_dict(c: LaborContract) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "employee_number": c.employee_number,
        "name": c.name,
        "department": c.department,
        "position": c.position,
        "seq_no": c.seq_no,
        "seq_label": c.seq_label,
        "term_type": c.term_type,
        "term_label": c.term_label,
        "term_years": c.term_years,
        "start_date": c.start_date.isoformat() if c.start_date else None,
        "end_date": c.end_date.isoformat() if c.end_date else None,
        "sign_date": c.sign_date.isoformat() if c.sign_date else None,
        "status": c.status,
        "status_label": c.status_label,
        "remark": c.remark,
        "dept_decision": c.dept_decision,
        "dept_decision_label": _DECISION_LABELS.get(c.dept_decision),
        "dept_decision_by": c.dept_decision_by,
        "dept_decision_at": c.dept_decision_at.isoformat() if c.dept_decision_at else None,
        "approval_mode": c.approval_mode,
        "approval_mode_label": _APPROVAL_MODE_LABELS.get(c.approval_mode),
        "approval_instance_code": c.approval_instance_code,
        "stamped_at": c.stamped_at.isoformat() if c.stamped_at else None,
        "delivered_at": c.delivered_at.isoformat() if c.delivered_at else None,
        "sign_confirmed_at": c.sign_confirmed_at.isoformat() if c.sign_confirmed_at else None,
        "terminated_reason": c.terminated_reason,
        "terminated_at": c.terminated_at.isoformat() if c.terminated_at else None,
        "departure_record_id": str(c.departure_record_id) if c.departure_record_id else None,
        "archive_status": c.archive_status,
        "archive_status_label": LaborContract.ARCHIVE_LABELS.get(c.archive_status, c.archive_status),
        "archive_file_name": c.archive_file_name,
        "archive_uploaded_at": c.archive_uploaded_at.isoformat() if c.archive_uploaded_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


async def _ensure_in_scope(
    db: AsyncSession, ctx: HrAccessContext, contract: LaborContract,
) -> None:
    """单条合同的数据范围校验（调阅权限三级，需求归档规则第 8 条）。

    - 全量范围（HR）：全部合同
    - self_only（员工本人）：仅本人合同
    - 部门范围（部门负责人）：授权部门内在职人员的合同；离职人员合同归离职台账，仅 HR 可见
    """
    if ctx.is_unrestricted:
        return
    if ctx.data_scope == "self_only":
        if not ctx.employee_number or contract.employee_number != ctx.employee_number:
            raise ForbiddenException("数据范围限制：仅可访问本人合同")
        return
    ctx.ensure_can_access_department(contract.department)
    if await repo.is_departed(db, contract.employee_number):
        raise ForbiddenException("数据范围限制：离职人员合同仅限 HR 在离职台账查看")


def _scope_departments(ctx: HrAccessContext) -> frozenset[str] | None:
    """台账列表的部门过滤：None=不限（HR 全量），空集=无授权部门。"""
    if ctx.is_unrestricted:
        return None
    if ctx.data_scope == "self_only":
        return frozenset()
    return ctx.scoped_departments or (
        frozenset({ctx.department}) if ctx.department else frozenset()
    )


def _archive_caps(ctx: HrAccessContext, contract: LaborContract) -> dict[str, bool]:
    """归档相关能力随数据范围变化，由后端下发供前端控制入口显隐（把关仍在各端点）。"""
    return {
        "can_archive": ctx.is_unrestricted,
        "can_access_file": archive_service.can_access_file(ctx, contract),
    }


def _list_scope(
    ctx: HrAccessContext, department: str | None,
) -> tuple[str | None, frozenset[str] | None]:
    """列表查询的数据范围收敛，返回 (工号过滤, 部门集合)。

    self_only（员工本人）按工号收敛到本人合同；其余按授权部门（None=不限，空集=无授权部门）。
    """
    employee_number = ctx.employee_number if ctx.data_scope == "self_only" else None
    departments = None if employee_number else _scope_departments(ctx)
    if department:
        if departments is not None and department not in departments:
            raise ForbiddenException("数据范围限制：仅可查看授权部门")
        departments = frozenset({department})
    return employee_number, departments


# ─── 台账 ───


@router.get("/labor-contracts", summary="劳动合同台账（分页，支持到期窗口/状态/关键字筛选）")
async def list_contracts(
    status: str | None = Query(None, description="逗号分隔状态过滤"),
    keyword: str | None = Query(None, max_length=64, description="姓名/工号模糊"),
    expiring_days: int | None = Query(None, ge=1, le=365, description="N 天内到期的公告期视图"),
    department: str | None = Query(None, max_length=64),
    archive_status: str | None = Query(
        None, pattern="^(unarchived|archived)$", description="归档状态过滤",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> JSONResponse:
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else None
    # 在职台账只放在职人员合同（两本台账不交叉），离职人员合同见离职台账「合同台账」页签
    employee_number, departments = _list_scope(ctx, department)

    total, rows = await repo.list_page(
        db,
        departments=departments,
        statuses=statuses,
        keyword=keyword,
        expiring_within_days=expiring_days,
        employee_number=employee_number,
        archive_status=archive_status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    return paginated_response(
        data=[_contract_dict(c) for c in rows], total=total, page=page, page_size=page_size
    )


@router.post("/labor-contracts", summary="录入劳动合同（期限按签订次数自动计算）")
async def create_contract(
    payload: ContractCreateInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.create_contract(
        db,
        employee_number=payload.employee_number,
        start_date=payload.start_date,
        sign_date=payload.sign_date,
        remark=payload.remark,
        user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.contract.create", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        new_value={"employee_number": contract.employee_number, "seq_no": contract.seq_no},
    )
    return success_response(data=_contract_dict(contract), message="已录入")


@router.get("/labor-contracts/{contract_id}", summary="合同详情（含同一员工历次合同）")
async def get_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    history = await service.contract_history(db, contract)
    data = _contract_dict(contract)
    data["history"] = [_contract_dict(c) for c in history]
    data.update(_archive_caps(ctx, contract))
    # 飞书原生审批为可选增强：配置了定义编码才展示「转飞书审批」入口（默认站内审批）
    kv = await contract_settings.load_contract_settings(db)
    data["renewal_approval_configured"] = bool(contract_settings.approval_code(kv))
    return success_response(data=data)


@router.put("/labor-contracts/{contract_id}", summary="编辑合同（限生效中/续签办理中）")
async def update_contract(
    contract_id: UUID,
    payload: ContractUpdateInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    contract = await service.update_contract(
        db, contract,
        start_date=payload.start_date,
        sign_date=payload.sign_date,
        position=payload.position,
        remark=payload.remark,
        user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.contract.update", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
    )
    return success_response(data=_contract_dict(contract), message="已保存")


# ─── 流转动作 ───


@router.post("/labor-contracts/{contract_id}/renew", summary="办理续签（生成新合同行，旧行被取代）")
async def renew_contract(
    contract_id: UUID,
    payload: RenewInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    new_contract = await service.renew_contract(
        db, contract,
        start_date=payload.start_date,
        sign_date=payload.sign_date,
        user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.contract.renew", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=new_contract.id,
        new_value={"from_id": str(contract.id), "seq_no": new_contract.seq_no},
    )
    return success_response(data=_contract_dict(new_contract), message="续签已办理")


@router.post(
    "/labor-contracts/{contract_id}/dept-decision",
    summary="部门审批（站内勾选；飞书审批由轮询回写）",
)
async def dept_decision(
    contract_id: UUID,
    payload: DecisionInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    contract = await service.apply_dept_decision(
        db, contract,
        decision=payload.decision,
        decided_by=ctx.user.name or str(ctx.user.id),
        user_id=ctx.user.id,
    )
    await record_audit_log(
        db, action="hr.contract.dept_decision", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        new_value={"decision": payload.decision},
    )
    return success_response(data=_contract_dict(contract), message="审批已记录")


@router.post("/labor-contracts/{contract_id}/terminate", summary="终止合同（不同意续签/到期未续签等）")
async def terminate_contract(
    contract_id: UUID,
    payload: TerminateInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    contract = await service.terminate_contract(
        db, contract, reason=payload.reason, user_id=ctx.user.id
    )
    await record_audit_log(
        db, action="hr.contract.terminate", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        new_value={"reason": contract.terminated_reason},
    )
    return success_response(data=_contract_dict(contract), message="已终止")


@router.post("/labor-contracts/{contract_id}/stamp", summary="标记盖章完成（推送领取通知）")
async def stamp_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    contract = await service.mark_stamped(db, contract, user_id=ctx.user.id)
    await record_audit_log(
        db, action="hr.contract.stamp", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
    )
    return success_response(data=_contract_dict(contract), message="已标记盖章完成")


@router.post("/labor-contracts/{contract_id}/deliver", summary="标记已领取（签发签字链接并推送提醒）")
async def deliver_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    contract, sign_url = await service.mark_delivered(db, contract, user_id=ctx.user.id)
    await record_audit_log(
        db, action="hr.contract.deliver", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
    )
    return success_response(
        data={**_contract_dict(contract), "sign_url": sign_url},
        message="已标记领取" + ("" if sign_url else "（未配置签字页地址，链接未生成）"),
    )


@router.post("/labor-contracts/{contract_id}/re-announce", summary="重新发起飞书审批（撤销/降级后补救）")
async def re_announce(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    if contract.status != LaborContract.STATUS_PENDING_RENEWAL:
        raise AppException(message="仅「公告期」的合同可重新发起审批")
    proposed_start = (contract.end_date or date.today()) + timedelta(days=1)
    ok, result = await renewal_approval.initiate(db, contract, next_start=proposed_start)
    if not ok:
        raise AppException(message=result)
    await service.mark_pending_renewal(
        db, contract, mode=LaborContract.APPROVAL_FEISHU, instance_code=result
    )
    await record_audit_log(
        db, action="hr.contract.re_announce", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
    )
    return success_response(data=_contract_dict(contract), message="已重新发起审批")


# ─── 公开签字（免登；挂全局 api_router，不走 hr 门禁）───

sign_router = APIRouter(tags=["HR-劳动合同"])


def _sign_view(contract: LaborContract) -> dict[str, Any]:
    """签字页最小视图：不含 id/工号等可枚举信息。"""
    return {
        "name": contract.name,
        "department": contract.department,
        "seq_no": contract.seq_no,
        "seq_label": contract.seq_label,
        "term_label": contract.term_label,
        "start_date": contract.start_date.isoformat() if contract.start_date else None,
        "end_date": contract.end_date.isoformat() if contract.end_date else None,
        "delivered_at": contract.delivered_at.isoformat() if contract.delivered_at else None,
        "sign_confirmed_at": (
            contract.sign_confirmed_at.isoformat() if contract.sign_confirmed_at else None
        ),
    }


@sign_router.get("/contract-sign/{token}", summary="签字页信息（token 即凭证，免登）")
async def sign_page_info(token: str, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    contract = await service.find_by_sign_token(db, token)
    if not contract:
        raise AppException(message="签字链接无效或已失效", status_code=404)
    return success_response(data=_sign_view(contract))


@sign_router.post("/contract-sign/{token}/confirm", summary="确认签字（一次性，成功后链接作废）")
async def sign_confirm(token: str, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    contract = await service.confirm_sign_by_token(db, token)
    return success_response(data=_sign_view(contract), message="签字确认成功")
