"""办结联动（closed）：员工签字确认后，档案/证件/花名册/入职台账/离职台账一次收口。

办结是唯一改写员工档案状态的节点——审批通过、开证、送达都不动档案，
避免流程中途取消后要把档案改回去。
"""

import logging
from uuid import UUID

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.hr.models import (
    EmployeeCertificate,
    OnboardingRecord,
    TrainingRosterProfile,
)
from app.modules.hr.offboarding import notify
from app.modules.hr.offboarding import repository as repo
from app.modules.hr.offboarding.models import OffboardingCase
from app.modules.hr.offboarding.service.common import (
    notify_context,
    now,
    refetch,
    upsert_departure_record,
)

logger = logging.getLogger(__name__)


async def close_case(
    db: AsyncSession, case: OffboardingCase, *,
    account_deactivated: bool = True, user_id: UUID | None = None,
) -> OffboardingCase:
    """办结。账号注销是 HR 确认勾选的登记项——平台不自动操作飞书账号。"""
    if case.status != OffboardingCase.STATUS_SIGNED:
        raise AppException(message="员工签字确认后才能办结")

    employee = await repo.get_employee(db, case.employee_id)
    # 1) 员工档案：状态→离职 + 离职日期/原因
    if employee:
        employee.status = "离职"
        employee.departure_date = case.offboarding_date
        employee.departure_reason = case.reason or case.offboarding_type

    # 2) 证件档案：当前版本转历史保留（行不删除，员工证件视图仍可查）
    await db.execute(
        update(EmployeeCertificate)
        .where(
            EmployeeCertificate.employee_id == case.employee_id,
            EmployeeCertificate.is_current.is_(True),
            EmployeeCertificate.is_deleted.is_(False),
        )
        .values(is_current=False)
    )

    # 3) 培训花名册：随档案口径同步离职（与 service._sync_roster_status 同款）
    await db.execute(
        update(TrainingRosterProfile)
        .where(
            TrainingRosterProfile.employee_number == case.employee_number,
            TrainingRosterProfile.is_deleted.is_(False),
        )
        .values(status="离职")
    )

    # 4) 入职台账：用工状态置不在职（与旧「新建离职」口径一致，各列表按不在职过滤）
    await db.execute(
        update(OnboardingRecord)
        .where(
            OnboardingRecord.employee_number == case.employee_number,
            OnboardingRecord.is_deleted.is_(False),
            # is_employed 为空的行也要更新：NULL != '否' 不成立，会被漏掉
            or_(OnboardingRecord.is_employed.is_(None), OnboardingRecord.is_employed != "否"),
        )
        .values(is_employed="否")
    )

    # 5) 离职台账：办结结果是权威口径，回写覆盖
    await upsert_departure_record(db, case, employee, overwrite=True)

    case.account_deactivated = account_deactivated
    case.closed_at = now()
    case.status = OffboardingCase.STATUS_CLOSED
    case.updated_by = user_id
    await db.commit()
    await notify.notify_stage_advanced(db, case, await notify_context(db))
    logger.info("离职办结: %s(%s) 档案/证件/花名册/入职台账/离职台账已联动", case.name, case.case_no)
    return await refetch(db, case.id)
