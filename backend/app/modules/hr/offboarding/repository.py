"""离职管理数据访问：办结单/清退明细/保存视图/导出留痕的读写。

约定：只做查询与字段写入，业务校验在 service 层；软删除一律显式过滤。
"""

import logging
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.models import DepartureRecord, Employee, HrDepartment
from app.modules.hr.offboarding.models import (
    DepartureSavedView,
    HrExportLog,
    OffboardingCase,
    OffboardingClearanceItem,
)

logger = logging.getLogger(__name__)

ACTIVE_CASE_STATUSES = tuple(OffboardingCase.FLOW_ORDER[:-1])  # closed 之外均算进行中
OVERDUE_DUE_DAYS = 2  # 清退交接应于离职日前 2 天发起：仍未走出审批 / 清退即算临期


# ─── 办结单 ───

async def get_case(db: AsyncSession, case_id: UUID) -> OffboardingCase | None:
    return (await db.execute(
        select(OffboardingCase).where(
            OffboardingCase.id == case_id,
            OffboardingCase.is_deleted.is_(False),
        )
    )).scalars().first()


async def list_cases(
    db: AsyncSession,
    *,
    status: str | None = None,
    department: str | None = None,
    departments: frozenset[str] | None = None,
    keyword: str | None = None,
    offboarding_date_from: date | None = None,
    offboarding_date_to: date | None = None,
    overdue: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[OffboardingCase], int]:
    stmt = select(OffboardingCase).where(OffboardingCase.is_deleted.is_(False))
    if overdue:
        # 与 count_overdue_cases 同口径：审批 / 清退中且距离职日 ≤ 2 天
        stmt = stmt.where(
            OffboardingCase.status.in_((
                OffboardingCase.STATUS_APPROVING, OffboardingCase.STATUS_CLEARING,
            )),
            OffboardingCase.offboarding_date <= date.today() + timedelta(days=OVERDUE_DUE_DAYS),
        )
    if status:
        stmt = stmt.where(OffboardingCase.status == status)
    if departments is not None:
        stmt = stmt.where(OffboardingCase.department.in_(departments))
    if department:
        stmt = stmt.where(OffboardingCase.department == department)
    if offboarding_date_from:
        stmt = stmt.where(OffboardingCase.offboarding_date >= offboarding_date_from)
    if offboarding_date_to:
        stmt = stmt.where(OffboardingCase.offboarding_date <= offboarding_date_to)
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            OffboardingCase.name.ilike(like)
            | OffboardingCase.employee_number.ilike(like)
            | OffboardingCase.department.ilike(like)
            | OffboardingCase.position.ilike(like)
        )
    total = (await db.execute(
        select(func.count()).select_from(stmt.subquery())
    )).scalar_one()
    rows = (await db.execute(
        stmt.order_by(OffboardingCase.created_at.desc())
        .offset(max(page - 1, 0) * page_size).limit(page_size)
    )).scalars().all()
    return list(rows), int(total)


async def list_open_cases(db: AsyncSession) -> list[OffboardingCase]:
    """全部未办结未取消的办结单（列表「进行中」默认视图/重复发起校验用）。"""
    return list((await db.execute(
        select(OffboardingCase).where(
            OffboardingCase.is_deleted.is_(False),
            OffboardingCase.status.in_(ACTIVE_CASE_STATUSES),
        ).order_by(OffboardingCase.offboarding_date.asc())
    )).scalars().all())


async def count_cases_by_status(
    db: AsyncSession, *, departments: frozenset[str] | None = None,
) -> dict[str, int]:
    """各状态的有效办结单数（看板页头统计）。"""
    stmt = (
        select(OffboardingCase.status, func.count())
        .where(OffboardingCase.is_deleted.is_(False))
        .group_by(OffboardingCase.status)
    )
    if departments is not None:
        stmt = stmt.where(OffboardingCase.department.in_(departments))
    return {status: int(count) for status, count in (await db.execute(stmt)).all()}


async def count_overdue_cases(
    db: AsyncSession, *, departments: frozenset[str] | None = None, due_days: int = OVERDUE_DUE_DAYS,
) -> int:
    """临期 / 超期单：仍在审批或清退阶段、但距离职日已不足 due_days 天（含已过）。"""
    stmt = (
        select(func.count())
        .select_from(OffboardingCase)
        .where(
            OffboardingCase.is_deleted.is_(False),
            OffboardingCase.status.in_((
                OffboardingCase.STATUS_APPROVING, OffboardingCase.STATUS_CLEARING,
            )),
            OffboardingCase.offboarding_date <= date.today() + timedelta(days=due_days),
        )
    )
    if departments is not None:
        stmt = stmt.where(OffboardingCase.department.in_(departments))
    return int((await db.execute(stmt)).scalar_one())


async def has_active_case(db: AsyncSession, employee_id: UUID) -> bool:
    row = (await db.execute(
        select(OffboardingCase.id).where(
            OffboardingCase.employee_id == employee_id,
            OffboardingCase.is_deleted.is_(False),
            OffboardingCase.status.in_(ACTIVE_CASE_STATUSES),
        ).limit(1)
    )).scalar_one_or_none()
    return row is not None


async def list_pending_approval_sync(db: AsyncSession) -> list[OffboardingCase]:
    """审批编排轮询范围：approving/clearing 且已存实例码的办结单。"""
    return list((await db.execute(
        select(OffboardingCase).where(
            OffboardingCase.is_deleted.is_(False),
            OffboardingCase.status.in_((OffboardingCase.STATUS_APPROVING, OffboardingCase.STATUS_CLEARING)),
            OffboardingCase.resignation_instance_code.is_not(None)
            | OffboardingCase.clearance_instance_code.is_not(None),
        )
    )).scalars().all())


async def next_case_no(db: AsyncSession, today: date) -> str:
    """当日序号取最大值 +1：LB-YYYYMMDD-0001。

    含软删行一起取：case_no 是全表唯一索引，只看未删行会复用已删单的编号而撞索引。
    """
    prefix = f"LB-{today:%Y%m%d}-"
    rows = (await db.execute(
        select(OffboardingCase.case_no).where(OffboardingCase.case_no.like(f"{prefix}%"))
    )).scalars().all()
    seq = 0
    for no in rows:
        try:
            seq = max(seq, int(str(no).rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"{prefix}{seq + 1:04d}"


# ─── 员工 / 台账 ───

async def get_employee(db: AsyncSession, employee_id: UUID) -> Employee | None:
    return (await db.execute(
        select(Employee).where(Employee.id == employee_id, Employee.is_deleted.is_(False))
    )).scalars().first()


# ─── 节点提醒取数（方案 §3.9）───

async def list_employees_with_departure_date(db: AsyncSession) -> list[Employee]:
    """档案已定离职日、尚未置离职的员工（发起时限提醒的扫描范围）。"""
    return list((await db.execute(
        select(Employee).where(
            Employee.is_deleted.is_(False),
            Employee.departure_date.is_not(None),
            Employee.status != "离职",
        )
    )).scalars().all())


async def active_case_employee_numbers(db: AsyncSession) -> set[str]:
    """有进行中办结单的工号（这些员工不必再提醒发起）。"""
    rows = (await db.execute(
        select(OffboardingCase.employee_number).where(
            OffboardingCase.is_deleted.is_(False),
            OffboardingCase.status.in_(ACTIVE_CASE_STATUSES),
        )
    )).scalars().all()
    return set(rows)


async def list_cases_in_statuses(db: AsyncSession, statuses: tuple[str, ...]) -> list[OffboardingCase]:
    return list((await db.execute(
        select(OffboardingCase).where(
            OffboardingCase.is_deleted.is_(False),
            OffboardingCase.status.in_(statuses),
        )
    )).scalars().all())


async def list_department_manager_names(db: AsyncSession, names: set[str]) -> list[str]:
    """一组部门的负责人姓名（去重；没填负责人的部门不返回）。"""
    if not names:
        return []
    rows = (await db.execute(
        select(HrDepartment.department_manager_name).where(
            HrDepartment.name.in_(names),
            HrDepartment.is_deleted.is_(False),
            HrDepartment.department_manager_name.is_not(None),
        )
    )).scalars().all()
    return sorted({name.strip() for name in rows if name and name.strip()})


async def department_manager_map(db: AsyncSession, names: set[str]) -> dict[str, str]:
    """部门名 → 负责人姓名（导出「当前处理人」用；没填负责人的部门不在结果里）。"""
    if not names:
        return {}
    rows = (await db.execute(
        select(HrDepartment.name, HrDepartment.department_manager_name).where(
            HrDepartment.name.in_(names),
            HrDepartment.is_deleted.is_(False),
            HrDepartment.department_manager_name.is_not(None),
        )
    )).all()
    return {name: manager.strip() for name, manager in rows if manager and manager.strip()}


async def get_departure_record(db: AsyncSession, record_id: UUID) -> DepartureRecord | None:
    return (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.id == record_id,
            DepartureRecord.is_deleted.is_(False),
        )
    )).scalars().first()


async def find_record_by_sign_token(db: AsyncSession, token_hash: str) -> DepartureRecord | None:
    """按签字 token 的 sha256 找台账行（免登签字入口，token 即凭证）。"""
    return (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.cert_sign_token == token_hash,
            DepartureRecord.is_deleted.is_(False),
        )
    )).scalars().first()


async def latest_case_by_record(
    db: AsyncSession, record_id: UUID, *, statuses: tuple[str, ...] | None = None,
) -> OffboardingCase | None:
    """台账行对应的最近一张办结单；statuses 限定状态（签字确认只认送达中的单）。"""
    stmt = select(OffboardingCase).where(
        OffboardingCase.departure_record_id == record_id,
        OffboardingCase.is_deleted.is_(False),
    )
    if statuses:
        stmt = stmt.where(OffboardingCase.status.in_(statuses))
    return (await db.execute(
        stmt.order_by(OffboardingCase.created_at.desc()).limit(1)
    )).scalars().first()


async def find_departure_record(
    db: AsyncSession, employee_number: str | None,
) -> DepartureRecord | None:
    if not employee_number:
        return None
    return (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.employee_number == employee_number,
            DepartureRecord.is_deleted.is_(False),
        ).order_by(DepartureRecord.created_at.desc()).limit(1)
    )).scalars().first()


# ─── 清退明细 ───

async def list_clearance_items(
    db: AsyncSession, case_id: UUID, *, source: str | None = None,
) -> list[OffboardingClearanceItem]:
    stmt = select(OffboardingClearanceItem).where(
        OffboardingClearanceItem.case_id == case_id,
        OffboardingClearanceItem.is_deleted.is_(False),
    )
    if source:
        stmt = stmt.where(OffboardingClearanceItem.source == source)
    return list((await db.execute(
        stmt.order_by(
            OffboardingClearanceItem.category.asc(), OffboardingClearanceItem.created_at.asc(),
        )
    )).scalars().all())


async def soft_delete_clearance_items(
    db: AsyncSession, case_id: UUID, *, source: str | None = None,
) -> None:
    """软删清退明细；source 指定时只删该来源（飞书回读不覆盖 HR 手工登记的行）。"""
    for row in await list_clearance_items(db, case_id, source=source):
        row.is_deleted = True
    await db.flush()


# ─── 保存视图 / 导出留痕 ───

async def list_saved_views(
    db: AsyncSession, owner_user_id: UUID,
) -> list[DepartureSavedView]:
    return list((await db.execute(
        select(DepartureSavedView).where(
            DepartureSavedView.owner_user_id == owner_user_id,
            DepartureSavedView.is_deleted.is_(False),
        ).order_by(DepartureSavedView.created_at.asc())
    )).scalars().all())


async def get_saved_view(db: AsyncSession, view_id: UUID) -> DepartureSavedView | None:
    return (await db.execute(
        select(DepartureSavedView).where(
            DepartureSavedView.id == view_id,
            DepartureSavedView.is_deleted.is_(False),
        )
    )).scalars().first()


async def clear_default_saved_views(db: AsyncSession, owner_user_id: UUID) -> None:
    """同一人只保留一个默认视图：新设默认前把其余的 is_default 翻回 false。"""
    for view in await list_saved_views(db, owner_user_id):
        if view.is_default:
            view.is_default = False
    await db.flush()


async def add_export_log(
    db: AsyncSession,
    *,
    module: str,
    operator_id: UUID | None,
    operator_name: str | None,
    filters: dict[str, Any] | None,
    columns: list[Any] | None,
    row_count: int,
) -> None:
    db.add(HrExportLog(
        module=module,
        operator_id=operator_id,
        operator_name=operator_name,
        filters=filters,
        columns=columns,
        row_count=row_count,
    ))
    await db.flush()


async def list_export_logs(
    db: AsyncSession, *, module: str = "departure", limit: int = 100,
) -> list[HrExportLog]:
    return list((await db.execute(
        select(HrExportLog).where(
            HrExportLog.module == module,
            HrExportLog.is_deleted.is_(False),
        ).order_by(HrExportLog.created_at.desc()).limit(limit)
    )).scalars().all())
