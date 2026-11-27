"""劳动合同 HTTP 路由：台账 CRUD、续签、审批、盖章/领取、终止。

本 router 挂在 hr 模块路由下（require_hr_basic 门禁 + _HR_PATH_PERMISSIONS 映射）。
系统只在公司内网可达，员工在手机上打不开本系统的链接，所以没有「线上签字」：
员工到人事办公室领取合同即完成签收，由 HR 登记领取。
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
from app.modules.hr.labor_contract import (
    archive_service,
    offboarding_handoff,
    renewal_approval,
    service,
)
from app.modules.hr.labor_contract import repository as repo
from app.modules.hr.labor_contract import settings as contract_settings
from app.modules.hr.labor_contract.models import ContractNoticeLog, LaborContract
from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)

router = APIRouter(tags=["HR-劳动合同"])

RESOURCE_TYPE = "hr_labor_contract"
# 详情页通知留痕条数上限
NOTICE_LOG_LIMIT = 20
# 「待我处理」口径取值（与 /labor-contracts/stats 的键名一致，另加 attention = 五项待办并集）
_TODO_PATTERN = "^(" + "|".join(repo.LIST_TODO_KEYS) + ")$"

# ─── 请求体 ───


class ContractCreateInput(BaseModel):
    employee_number: str = Field(..., max_length=32, description="工号")
    start_date: date = Field(..., description="合同起始日")
    sign_date: date | None = Field(None, description="实际签订日（缺省同起始日）")
    seq_no: int | None = Field(
        None, ge=1, description="签订次序（缺省按入职日期+期限规则推算，可人工指定）",
    )
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


class TransferOffboardingInput(BaseModel):
    offboarding_date: date | None = Field(
        None, description="离职日期；不传则合同到期日未过用到期日，否则用今天",
    )
    reason: str | None = Field(None, max_length=512, description="离职原因；不传则按部门意见自动生成")


class ResendNoticeInput(BaseModel):
    kind: Literal["renew", "collect"] = Field(..., description="renew 续签通知 / collect 领取通知")


# ─── 序列化 ───

_DECISION_LABELS: dict[str | None, str] = {"agree": "同意续签", "disagree": "不同意续签"}
_APPROVAL_MODE_LABELS: dict[str | None, str] = {"feishu": "飞书审批", "manual": "站内审批"}


def _split_csv(raw: str | None) -> list[str] | None:
    """逗号分隔的筛选项 → 去空白的非空列表；没传或全为空返回 None（即不筛选）。"""
    if not raw:
        return None
    return [item.strip() for item in raw.split(",") if item.strip()] or None


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
        "origin": c.origin,
        "origin_label": c.origin_label,
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


def _notice_dict(log: ContractNoticeLog) -> dict[str, Any]:
    return {
        "kind": log.kind,
        "recipient_name": log.recipient_name,
        "status": log.status,
        "error_message": log.error_message,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _progress_dicts(contract: LaborContract, notices: list[ContractNoticeLog]) -> list[dict[str, Any]]:
    """进度步骤的 JSON 形态（时间统一 ISO 字符串，与本模块其余接口一致）。"""
    return [
        {**step, "at": step["at"].isoformat() if step["at"] else None}
        for step in service.build_progress(contract, notices)
    ]


def _notice_suffix(notice: dict[str, Any]) -> str:
    """通知没送达时在提示语后追加原因（送达则不追加）。"""
    if notice["status"] == ContractNoticeLog.STATUS_SENT:
        return ""
    return f"（通知未送达：{notice['error'] or '发送失败'}）"


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


@router.get("/labor-contracts", summary="劳动合同台账（分页，支持到期窗口/状态/待办口径/学历筛选）")
async def list_contracts(
    status: str | None = Query(None, description="逗号分隔状态过滤"),
    keyword: str | None = Query(None, max_length=64, description="姓名/工号模糊"),
    expiring_days: int | None = Query(None, ge=1, le=365, description="N 天内到期的公告期视图"),
    department: str | None = Query(None, max_length=64),
    archive_status: str | None = Query(
        None, pattern="^(unarchived|archived)$", description="归档状态过滤",
    ),
    education: str | None = Query(
        None, max_length=128, description="学历过滤（逗号分隔多值；取自员工档案）",
    ),
    todo: str | None = Query(
        None, pattern=_TODO_PATTERN,
        description="「待我处理」口径（键名同 /labor-contracts/stats）",
    ),
    include_history: bool = Query(
        False,
        description="true 时返回已续签取代 / 已终止的历史行（缺省且未传 status、todo 时不返回）",
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> JSONResponse:
    # 在职台账只放在职人员合同（两本台账不交叉），离职人员合同见离职台账「合同台账」页签
    employee_number, departments = _list_scope(ctx, department)

    total, rows = await repo.list_page(
        db,
        departments=departments,
        statuses=_split_csv(status),
        keyword=keyword,
        expiring_within_days=expiring_days,
        employee_number=employee_number,
        archive_status=archive_status,
        educations=_split_csv(education),
        todo=todo,
        exclude_history=not include_history,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    education_map = await repo.map_education(db, [c.employee_number for c in rows])
    return paginated_response(
        data=[
            {**_contract_dict(c), "education": education_map.get(c.employee_number)}
            for c in rows
        ],
        total=total, page=page, page_size=page_size,
    )


@router.get(
    "/labor-contracts/stats",
    summary="劳动合同「待我处理」统计（口径与列表 todo 筛选一致；人群同在职台账）",
)
async def contract_stats(
    department: str | None = Query(None, max_length=64),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> JSONResponse:
    # 必须登记在 /labor-contracts/{contract_id} 之前，否则 stats 会被当成 contract_id
    employee_number, departments = _list_scope(ctx, department)
    return success_response(data=await service.contract_stats(
        db, departments=departments, employee_number=employee_number,
    ))


@router.get("/labor-contracts/entry-preview", summary="录入预推：签订次序与期限（按入职日期推算）")
async def entry_preview(
    employee_number: str = Query(..., description="工号"),
    start_date: date = Query(..., description="合同起始日"),
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:read")),
) -> JSONResponse:
    employee = await repo.get_employee(db, employee_number)
    if not employee:
        raise NotFoundException("员工档案", f"工号 {employee_number}")
    prior = await repo.list_by_employee(db, employee_number)
    max_prior = max((c.seq_no for c in prior), default=0)
    seq_no = max(max_prior + 1, service.infer_seq_from_hire(employee.hire_date, start_date))
    term_type, years = service.term_for_seq(seq_no)
    end_date = service.compute_end_date(start_date, term_type, years)
    hire_date = employee.hire_date
    years_employed = None
    if hire_date is not None and hire_date.year >= 1950 and start_date >= hire_date:
        years_employed = round((start_date - hire_date).days / 365.25, 1)
    return success_response(data={
        "employee_number": employee_number,
        "seq_no": seq_no,
        "seq_label": service.next_term_preview(seq_no),
        "term_type": term_type,
        "term_years": years,
        "end_date": end_date.isoformat() if end_date else None,
        "years_employed": years_employed,
        "existing_contracts": len(prior),
    })


@router.post("/labor-contracts", summary="录入劳动合同（签订次序按入职日期推算，期限按签订次数自动计算）")
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
        seq_no=payload.seq_no,
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
    notices = await repo.list_notices(db, contract.id, limit=NOTICE_LOG_LIMIT)
    data = _contract_dict(contract)
    data["history"] = [_contract_dict(c) for c in history]
    # 通知留痕（新→旧）与状态驱动的进度步骤：前端只渲染，不再按字段自行推断
    data["notices"] = [_notice_dict(log) for log in notices]
    data["progress"] = _progress_dicts(contract, notices)
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
    summary="登记部门续签意见（同意 / 不同意）",
)
async def dept_decision(
    contract_id: UUID,
    payload: DecisionInput,
    db: AsyncSession = Depends(get_db),
    # 部门负责人只需 approve；HR 持 manage 可代登记（任一即可，仍走数据范围校验）
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage", "hr:contract:approve")),
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
    contract, notice = await service.mark_stamped(
        db, contract, user_id=ctx.user.id, user_name=ctx.user.name,
    )
    await record_audit_log(
        db, action="hr.contract.stamp", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
    )
    notice_data = notice.as_dict()
    return success_response(
        data={**_contract_dict(contract), "notice": notice_data},
        message="已标记盖章完成" + _notice_suffix(notice_data),
    )


@router.post("/labor-contracts/{contract_id}/deliver", summary="登记已领取（员工到人事办公室领取合同即签收）")
async def deliver_contract(
    contract_id: UUID,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    contract = await service.mark_delivered(
        db, contract, user_id=ctx.user.id, user_name=ctx.user.name,
    )
    await record_audit_log(
        db, action="hr.contract.deliver", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
    )
    return success_response(data=_contract_dict(contract), message="已登记领取")


@router.post(
    "/labor-contracts/{contract_id}/resend-notice",
    summary="重发员工通知（续签通知 / 领取通知）",
)
async def resend_notice(
    contract_id: UUID,
    payload: ResendNoticeInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    notice = await service.resend_notice(
        db, contract, kind=payload.kind, user_id=ctx.user.id, user_name=ctx.user.name,
    )
    await record_audit_log(
        db, action="hr.contract.resend_notice", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        new_value={"kind": payload.kind, "status": notice.status, "error": notice.error},
    )
    notice_data = notice.as_dict()
    if notice.status == ContractNoticeLog.STATUS_SENT:
        message = "通知已发送"
    else:
        message = f"通知未发送：{notice.error or '发送失败'}"
    return success_response(data=notice_data, message=message)


@router.post(
    "/labor-contracts/{contract_id}/transfer-offboarding",
    summary="转入离职办理（为员工创建离职办理单；合同未终止的置已终止并关联）",
)
async def transfer_offboarding(
    contract_id: UUID,
    payload: TransferOffboardingInput,
    db: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:contract:manage")),
) -> JSONResponse:
    contract = await service.get_or_404(db, contract_id)
    await _ensure_in_scope(db, ctx, contract)
    case = await offboarding_handoff.transfer_to_offboarding(
        db, contract,
        offboarding_date=payload.offboarding_date, reason=payload.reason,
        user_id=ctx.user.id, initiator_name=ctx.user.name,
    )
    await record_audit_log(
        db, action="hr.contract.transfer_offboarding", user=ctx.user,
        resource_type=RESOURCE_TYPE, resource_id=contract.id,
        new_value={
            "case_id": case["id"], "case_no": case["case_no"],
            "offboarding_date": case["offboarding_date"],
        },
    )
    return success_response(data=case, message="已转入离职办理")


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
