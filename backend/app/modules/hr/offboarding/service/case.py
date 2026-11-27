"""离职办结单：建单、编辑、取消、发起审批、站内登记、清退明细、离岗体检登记。

状态机（见 models.OffboardingCase）：draft → approving → clearing → cert_issuing
→ delivering → signed → closed；closed 前可 canceled。证明签收见 certify.py，
办结联动见 closing.py。
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.core.file_storage import read_object, store_object, validate_upload
from app.modules.hr.models import Employee
from app.modules.hr.offboarding import approval as approval_flow
from app.modules.hr.offboarding import clearance, notify
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding import settings as offboarding_settings
from app.modules.hr.offboarding.models import OffboardingCase, OffboardingClearanceItem
from app.modules.hr.offboarding.service.common import (
    notify_context,
    now,
    refetch,
    upsert_departure_record,
)

logger = logging.getLogger(__name__)

# 离岗体检报告：PDF / 图片，20MB
_HEALTH_FILE_TYPES = {
    ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
}
_HEALTH_FILE_MAX = 20 * 1024 * 1024


# ─── 建单 / 编辑 / 取消 ───

async def create_case(
    db: AsyncSession,
    *,
    employee_id: UUID,
    offboarding_date: date,
    offboarding_type: str = OffboardingCase.TYPE_RESIGN,
    reason: str | None = None,
    application_submitted: bool = True,
    health_check_required: bool | None = None,
    remark: str | None = None,
    user_id: UUID | None = None,
    initiator_name: str | None = None,
) -> OffboardingCase:
    employee = await repo.get_employee(db, employee_id)
    if not employee:
        raise NotFoundException("员工档案", str(employee_id))
    if employee.status == "离职":
        raise AppException(message="该员工档案已是离职状态，无需重复发起离职办理")
    if not employee.employee_number:
        raise AppException(message="该员工档案缺少工号，无法发起离职办理（台账按工号关联）")
    if await repo.has_active_case(db, employee_id):
        raise DuplicateException("进行中的离职办理", f"{employee.name}（{employee.employee_number}）")
    if offboarding_type not in OffboardingCase.TYPE_LABELS:
        raise AppException(message="离职类型只能是：辞职/辞退/合同到期/退休/其他")

    kv = await offboarding_settings.load_offboarding_settings(db)
    # 用工类型：离职台账「员工性质」优先，没有则按档案状态推导
    ledger = await repo.find_departure_record(db, employee.employee_number)
    employee_category = (ledger.employee_category if ledger else None) or (
        "试用期" if employee.status == "试用期" else "转正员工"
    )

    case = OffboardingCase(
        case_no=await repo.next_case_no(db, date.today()),
        employee_id=employee.id,
        employee_number=employee.employee_number,
        name=employee.name,
        department=employee.department,
        position=employee.position,
        level=employee.level,
        initiator_name=initiator_name,
        offboarding_date=offboarding_date,
        offboarding_type=offboarding_type,
        reason=(reason or "").strip()[:512] or None,
        employee_category=employee_category,
        application_submitted=application_submitted,
        status=OffboardingCase.STATUS_DRAFT,
        approval_track=offboarding_settings.resolve_track(kv, employee.level),
        health_check_required=(
            bool(employee.is_key_position) if health_check_required is None else health_check_required
        ),
        remark=remark,
        created_by=user_id,
    )
    db.add(case)
    await db.flush()
    await upsert_departure_record(db, case, employee)
    await db.commit()
    logger.info(
        "创建离职办理: %s(%s) 编号 %s 离职日 %s",
        employee.name, employee.employee_number, case.case_no, offboarding_date,
    )
    return await refetch(db, case.id)


async def update_case(
    db: AsyncSession,
    case: OffboardingCase,
    *,
    offboarding_date: date | None = None,
    offboarding_type: str | None = None,
    reason: str | None = None,
    application_submitted: bool | None = None,
    health_check_required: bool | None = None,
    remark: str | None = None,
    user_id: UUID | None = None,
) -> OffboardingCase:
    if case.status not in (OffboardingCase.STATUS_DRAFT, OffboardingCase.STATUS_APPROVING):
        raise AppException(message="仅「待发起审批 / 离职审批中」可编辑基本信息")
    if case.resignation_instance_code:
        raise AppException(message="飞书审批进行中，请先在飞书撤销审批后再修改")
    if offboarding_type is not None and offboarding_type not in OffboardingCase.TYPE_LABELS:
        raise AppException(message="离职类型只能是：辞职/辞退/合同到期/退休/其他")
    if health_check_required is False and case.health_check_required and case.status != OffboardingCase.STATUS_DRAFT:
        raise AppException(message="审批已发起，不能取消离岗体检要求")

    if offboarding_date is not None:
        case.offboarding_date = offboarding_date
    if offboarding_type is not None:
        case.offboarding_type = offboarding_type
    if reason is not None:
        case.reason = reason.strip()[:512] or None
    if application_submitted is not None:
        case.application_submitted = application_submitted
    if health_check_required is not None:
        case.health_check_required = health_check_required
    if remark is not None:
        case.remark = remark
    case.updated_by = user_id
    await upsert_departure_record(db, case, None)
    await db.commit()
    return await refetch(db, case.id)


async def cancel_case(
    db: AsyncSession, case: OffboardingCase, *, user_id: UUID | None = None,
) -> OffboardingCase:
    """取消办理。平台建单时自动落的台账行一并撤下——否则在职员工会挂在
    离职台账里；已被飞书同步认领的行（有 feishu_record_id）是源表数据，不动。"""
    if case.status == OffboardingCase.STATUS_CLOSED:
        raise AppException(message="已办结的离职单不可取消")
    if case.status == OffboardingCase.STATUS_CANCELED:
        raise AppException(message="该离职办理已取消")

    case.status = OffboardingCase.STATUS_CANCELED
    case.updated_by = user_id
    await db.flush()
    record = await repo.get_departure_record(db, case.departure_record_id) if case.departure_record_id else None
    if record is not None and not record.feishu_record_id:
        record.is_deleted = True
        record.cert_sign_token = None
    await db.commit()
    logger.info("取消离职办理: %s(%s)", case.name, case.case_no)
    return await refetch(db, case.id)


# ─── 发起离职审批（体检门禁 + 提前天数提示 + 飞书编排/降级）───

def lead_time_warning(case: OffboardingCase, employee: Employee | None, *, lead_days: int) -> str | None:
    """提前天数不足时给出提示（不硬卡——存在协商离职场景）。"""
    days_left = (case.offboarding_date - date.today()).days
    probation = bool(employee and employee.status == "试用期")
    if days_left < lead_days:
        who = "试用期员工" if probation else "转正员工"
        return f"{who}按制度应提前 {lead_days} 天发起（当前提前 {max(days_left, 0)} 天），请确认已获批准"
    return None


async def submit_approval(
    db: AsyncSession, case: OffboardingCase, *, user_id: UUID | None = None,
    operator_open_id: str | None = None,
) -> tuple[OffboardingCase, str | None]:
    """发起离职审批。返回 (case, 提前天数提示)。体检门禁未过直接拒绝。

    operator_open_id：点「发起」的 HR 的飞书身份，员工本人没有飞书 open_id 时
    作为审批实例的发起人。
    """
    if case.status != OffboardingCase.STATUS_DRAFT:
        raise AppException(message="仅「待发起审批」状态可发起离职审批")
    if case.health_check_required and not case.health_check_done:
        raise AppException(message="该员工涉及职业健康体检，须先完成离岗体检登记才能发起离职审批")

    employee = await repo.get_employee(db, case.employee_id)
    kv = await offboarding_settings.load_offboarding_settings(db)
    probation = bool(employee and employee.status == "试用期")
    warning = lead_time_warning(
        case, employee, lead_days=offboarding_settings.lead_days(kv, probation=probation),
    )

    case.status = OffboardingCase.STATUS_APPROVING
    case.updated_by = user_id
    await db.flush()
    result = await approval_flow.initiate_resignation(db, case, operator_open_id=operator_open_id)
    await db.commit()

    ctx = await notify_context(db)
    if result.ok or result.unconfigured:
        # 未配置定义 = 设计内的降级路径，按阶段推进通知（不当失败报警）
        await notify.notify_stage_advanced(
            db, case, ctx,
            note="飞书审批定义未配置，走站内登记办结" if result.unconfigured else None,
        )
    else:
        await notify.notify_initiate_failed(db, case, ctx, stage="离职审批", error=result.reason)
    logger.info("发起离职审批: %s(%s) 飞书=%s", case.name, case.case_no, result.ok)
    return await refetch(db, case.id), warning


async def manual_stage_done(
    db: AsyncSession, case: OffboardingCase, *, stage: str,
    note: str | None = None, user_id: UUID | None = None,
    operator_open_id: str | None = None,
) -> OffboardingCase:
    """站内登记办结（飞书审批未配置/不可用时的降级路径）。

    stage=approving：登记离职审批办结 → 清退会签（并尝试发起清退交接飞书审批）；
    stage=clearing：登记会签办结 → 待开具证明。
    """
    expected = {
        "approving": OffboardingCase.STATUS_APPROVING,
        "clearing": OffboardingCase.STATUS_CLEARING,
    }.get(stage)
    if expected is None:
        raise AppException(message="stage 只能是 approving / clearing")
    if case.status != expected:
        raise AppException(message=f"当前状态不在「{OffboardingCase.STATUS_LABELS[expected]}」")

    stamp = now()
    result = None
    if stage == "approving":
        case.resignation_finished_at = stamp
        case.resignation_instance_code = None  # 站内登记后不再轮询旧实例
        case.status = OffboardingCase.STATUS_CLEARING
        await db.flush()
        await clearance.seed_default_items(db, case)
        result = await approval_flow.initiate_clearance(db, case, operator_open_id=operator_open_id)
    else:
        case.clearance_finished_at = stamp
        case.clearance_instance_code = None
        case.status = OffboardingCase.STATUS_CERT_ISSUING
    if note and note.strip():
        # 追加而不是覆盖：建单时的备注要留住
        entry = f"站内登记（{OffboardingCase.STATUS_LABELS[expected]}）：{note.strip()}"
        case.remark = "；".join(filter(None, [case.remark, entry]))[-512:]
    case.updated_by = user_id
    await db.commit()

    ctx = await notify_context(db)
    if result is not None and not result.ok and not result.unconfigured:
        await notify.notify_initiate_failed(db, case, ctx, stage="清退交接", error=result.reason)
    else:
        await notify.notify_stage_advanced(
            db, case, ctx,
            note="飞书审批定义未配置，走站内登记办结" if result and result.unconfigured else None,
        )
    logger.info("站内登记办结: %s(%s) stage=%s", case.name, case.case_no, stage)
    return await refetch(db, case.id)


# ─── 清退明细 ───

def _clearance_row(
    payload: dict[str, Any], *, case_id: UUID, user_id: UUID | None,
) -> OffboardingClearanceItem:
    category = payload.get("category")
    status = payload.get("status") or OffboardingClearanceItem.STATUS_PENDING
    if category not in OffboardingClearanceItem.CATEGORY_LABELS:
        raise AppException(message="清退部门维度只能是：行政后勤部/财务部/人力资源部/工作部门")
    if status not in OffboardingClearanceItem.STATUS_LABELS:
        raise AppException(message="清退状态只能是：待确认/已清退/有扣补")
    item_name = str(payload.get("item_name") or "").strip()
    if not item_name:
        raise AppException(message="清退事项名称不能为空")
    amounts: dict[str, Decimal | None] = {}
    for field_name, label in (("deduction_amount", "扣款"), ("supplement_amount", "补发")):
        value = payload.get(field_name)
        if value is None:
            amounts[field_name] = None
            continue
        value = Decimal(str(value))
        if value < 0:
            raise AppException(message=f"{label}金额不能为负数")
        amounts[field_name] = value
    return OffboardingClearanceItem(
        case_id=case_id,
        category=category,
        item_name=item_name[:64],
        status=status,
        deduction_amount=amounts["deduction_amount"],
        supplement_amount=amounts["supplement_amount"],
        remark=(str(payload.get("remark") or "").strip() or None),
        confirmed_by=(str(payload.get("confirmed_by") or "").strip()[:64] or None),
        confirmed_at=now() if status != OffboardingClearanceItem.STATUS_PENDING else None,
        source=OffboardingClearanceItem.SOURCE_MANUAL,
        created_by=user_id,
    )


async def replace_clearance_items(
    db: AsyncSession, case: OffboardingCase, items: list[dict[str, Any]], *,
    user_id: UUID | None = None,
) -> list[OffboardingClearanceItem]:
    """全量替换清退明细（前端表格一次保存）。校验全部通过后才落库，不会存一半。"""
    if case.status not in (OffboardingCase.STATUS_CLEARING, OffboardingCase.STATUS_CERT_ISSUING):
        raise AppException(message="仅「清退会签中 / 待开具证明」可维护清退明细")
    rows = [_clearance_row(item, case_id=case.id, user_id=user_id) for item in items]
    await repo.soft_delete_clearance_items(db, case.id)
    db.add_all(clearance.in_entry_order(rows))  # 保持前端表格里的录入顺序
    await db.commit()
    return await repo.list_clearance_items(db, case.id)


# ─── 离岗体检（重点岗位门禁）───

def read_health_check_file(case: OffboardingCase) -> tuple[bytes, str] | None:
    if not case.health_check_file_key:
        return None
    return read_object("hr", case.health_check_file_key)


async def register_health_check(
    db: AsyncSession, case: OffboardingCase, *,
    done: bool, check_date: date | None = None,
    file_name: str | None = None, file_bytes: bytes | None = None,
    user_id: UUID | None = None,
) -> OffboardingCase:
    """离岗体检登记（重点岗位门禁）：日期 + 报告附件（可选）。

    撤销登记（done=False）只允许在发起审批前；报告按扩展名 + 文件头校验。
    """
    if case.status == OffboardingCase.STATUS_CLOSED:
        raise AppException(message="已办结的离职单不能再修改体检登记")
    if not done:
        if case.status != OffboardingCase.STATUS_DRAFT:
            raise AppException(message="审批已发起，不能撤销离岗体检登记")
        case.health_check_done = False
        case.health_check_date = None
        case.health_check_file_key = None
        case.health_check_file_name = None
    else:
        if check_date and check_date > date.today():
            raise AppException(message="体检完成日期不能晚于今天")
        case.health_check_done = True
        case.health_check_date = check_date or date.today()
        if file_bytes is not None:
            safe_name, ext, content_type = validate_upload(
                file_name, file_bytes,
                allowed=_HEALTH_FILE_TYPES, max_size=_HEALTH_FILE_MAX,
                kind_label="PDF 或图片", default_name="离岗体检报告",
            )
            # 对象 key 不带原始文件名：中文名/特殊字符只留在 health_check_file_name
            key = store_object(
                "hr",
                f"offboarding/{case.id}/health_check_{now():%Y%m%d%H%M%S%f}.{ext}",
                file_bytes, content_type,
            )
            case.health_check_file_key = key
            case.health_check_file_name = safe_name
    case.updated_by = user_id
    await db.commit()
    return await refetch(db, case.id)


__all__ = [
    "create_case",
    "update_case",
    "cancel_case",
    "lead_time_warning",
    "submit_approval",
    "manual_stage_done",
    "replace_clearance_items",
    "read_health_check_file",
    "register_health_check",
]
