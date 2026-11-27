"""劳动合同数据读写：只做查询与持久化，不含业务语义判断。"""

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract.models import ContractArchiveVersion, LaborContract
from app.modules.hr.models import DepartureRecord, Employee

# 台账人群口径（两本台账不交叉）：在职台账只放在职人员合同，离职人员合同归离职台账
POPULATION_IN_SERVICE = "in_service"
POPULATION_DEPARTED = "departed"
POPULATION_ALL = "all"


def departed_expr() -> ColumnElement[bool]:
    """「已离职」判定：有未删除的离职记录，或员工档案状态为离职。

    离职人员通常已不在员工档案里（本地 195 个离职人员 0 个在档），只看档案状态
    会漏；离职办理一发起即建离职记录，此时合同即归入离职台账、退出在职台账。
    """
    has_departure = exists().where(
        DepartureRecord.employee_number == LaborContract.employee_number,
        DepartureRecord.is_deleted.is_(False),
    )
    emp_left = exists().where(
        Employee.employee_number == LaborContract.employee_number,
        Employee.is_deleted.is_(False),
        Employee.status == "离职",
    )
    return or_(has_departure, emp_left)


async def get(db: AsyncSession, contract_id: UUID) -> LaborContract | None:
    return (await db.execute(
        select(LaborContract).where(
            LaborContract.id == contract_id,
            LaborContract.is_deleted.is_(False),
        )
    )).scalar_one_or_none()


async def list_by_employee(
    db: AsyncSession, employee_number: str
) -> list[LaborContract]:
    """某工号全部合同（按签订次数升序），供详情履历与「历次合同」聚合。"""
    rows = (await db.execute(
        select(LaborContract).where(
            LaborContract.employee_number == employee_number,
            LaborContract.is_deleted.is_(False),
        ).order_by(LaborContract.seq_no.asc())
    )).scalars().all()
    return list(rows)


async def list_page(
    db: AsyncSession,
    *,
    departments: frozenset[str] | None = None,
    statuses: list[str] | None = None,
    keyword: str | None = None,
    expiring_within_days: int | None = None,
    employee_number: str | None = None,
    population: str = POPULATION_IN_SERVICE,
    archive_status: str | None = None,
    order_by: str = "default",
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[LaborContract]]:
    """台账分页查询。departments 为 None 表示不限部门（HR 全量）。

    employee_number：self_only 数据范围按工号收敛到本人；
    population：in_service（缺省，在职台账）/ departed（离职人员合同）/ all（电子档案库全量）；
    order_by="department"：按部门-工号-签订次数排序（档案库/补扫清单按部门分组用）。
    """
    conds: list[ColumnElement[bool]] = [LaborContract.is_deleted.is_(False)]
    if population == POPULATION_IN_SERVICE:
        conds.append(not_(departed_expr()))
    elif population == POPULATION_DEPARTED:
        conds.append(departed_expr())
    if departments is not None:
        if not departments:
            return 0, []
        conds.append(LaborContract.department.in_(departments))
    if statuses:
        conds.append(LaborContract.status.in_(statuses))
    if keyword:
        kw = f"%{keyword.strip()}%"
        conds.append(or_(
            LaborContract.name.ilike(kw),
            LaborContract.employee_number.ilike(kw),
        ))
    if employee_number:
        conds.append(LaborContract.employee_number == employee_number)
    if archive_status:
        conds.append(LaborContract.archive_status == archive_status)
    if expiring_within_days is not None:
        today = date.today()
        deadline = today.fromordinal(today.toordinal() + expiring_within_days)
        conds.append(LaborContract.end_date.is_not(None))
        conds.append(LaborContract.end_date >= today)
        conds.append(LaborContract.end_date <= deadline)

    total = (await db.execute(
        select(func.count()).select_from(LaborContract).where(*conds)
    )).scalar_one()
    ordering = (
        (LaborContract.department.asc(), LaborContract.employee_number.asc(),
         LaborContract.seq_no.desc())
        if order_by == "department" else
        (LaborContract.end_date.asc().nulls_last(), LaborContract.employee_number.asc(),
         LaborContract.seq_no.desc())
    )
    rows = (await db.execute(
        select(LaborContract).where(*conds)
        .order_by(*ordering)
        .offset(offset).limit(limit)
    )).scalars().all()
    return int(total), list(rows)


async def get_active_with_seq(
    db: AsyncSession, employee_number: str, seq_no: int
) -> LaborContract | None:
    """同工号同签订次数的有效合同（部分唯一索引的业务侧防御）。"""
    return (await db.execute(
        select(LaborContract).where(
            LaborContract.employee_number == employee_number,
            LaborContract.seq_no == seq_no,
            LaborContract.is_deleted.is_(False),
            LaborContract.status.notin_(
                [LaborContract.STATUS_SUPERSEDED, LaborContract.STATUS_TERMINATED]
            ),
        )
    )).scalar_one_or_none()


async def list_active_employees(
    db: AsyncSession, employee_numbers: list[str]
) -> dict[str, Employee]:
    """按工号批量取在职员工档案（status != 离职），返回 {工号: Employee}。

    合同行是录入时快照，公告期判定「是否仍在职」必须以员工档案实时状态为准。
    """
    if not employee_numbers:
        return {}
    rows = (await db.execute(
        select(Employee).where(
            Employee.employee_number.in_(employee_numbers),
            Employee.is_deleted.is_(False),
            Employee.status != "离职",
        )
    )).scalars().all()
    return {e.employee_number: e for e in rows}


async def get_employee(db: AsyncSession, employee_number: str) -> Employee | None:
    """按工号取员工档案（含离职，供快照/通知取 open_id）。"""
    return (await db.execute(
        select(Employee).where(
            Employee.employee_number == employee_number,
            Employee.is_deleted.is_(False),
        )
    )).scalar_one_or_none()


async def find_departure_record_id(
    db: AsyncSession, employee_number: str
) -> UUID | None:
    """取该工号最新一条离职记录 ID（终止合同回写关联用）。"""
    row = (await db.execute(
        select(DepartureRecord.id).where(
            DepartureRecord.employee_number == employee_number,
            DepartureRecord.is_deleted.is_(False),
        ).order_by(DepartureRecord.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    return row


async def get_departure_record(
    db: AsyncSession, employee_number: str
) -> DepartureRecord | None:
    """取该工号最新一条离职记录（离职日期最近者优先，空值排最后）。"""
    row = (await db.execute(
        select(DepartureRecord).where(
            DepartureRecord.employee_number == employee_number,
            DepartureRecord.is_deleted.is_(False),
        ).order_by(
            DepartureRecord.offboarding_date.desc().nulls_last(),
            DepartureRecord.created_at.desc(),
        ).limit(1)
    )).scalars().first()
    return row


async def map_left_employees(db: AsyncSession, employee_numbers: list[str]) -> set[str]:
    """档案状态为「离职」的工号集合（批量）。"""
    if not employee_numbers:
        return set()
    rows = (await db.execute(
        select(Employee.employee_number).where(
            Employee.employee_number.in_(employee_numbers),
            Employee.is_deleted.is_(False),
            Employee.status == "离职",
        )
    )).scalars().all()
    return set(rows)


async def is_departed(db: AsyncSession, employee_number: str) -> bool:
    """单个工号的「已离职」判定（口径同 departed_expr）。"""
    departure = (await db.execute(
        select(DepartureRecord.id).where(
            DepartureRecord.employee_number == employee_number,
            DepartureRecord.is_deleted.is_(False),
        ).limit(1)
    )).scalars().first()
    if departure is not None:
        return True
    return employee_number in await map_left_employees(db, [employee_number])


async def list_open_contracts(db: AsyncSession) -> list[LaborContract]:
    """未完结合同（active / pending_renewal / renewing / expired_unrenewed）。"""
    rows = (await db.execute(
        select(LaborContract).where(
            LaborContract.is_deleted.is_(False),
            LaborContract.status.in_([
                LaborContract.STATUS_ACTIVE,
                LaborContract.STATUS_PENDING_RENEWAL,
                LaborContract.STATUS_RENEWING,
                LaborContract.STATUS_EXPIRED_UNRENEWED,
            ]),
        ).order_by(LaborContract.employee_number.asc())
    )).scalars().all()
    return list(rows)


async def list_unarchived(
    db: AsyncSession, *, department: str | None = None,
) -> list[LaborContract]:
    """未归档合同（在职 + 离职；含已续签取代/已终止——原合同同样要归档保留）。"""
    conds: list[ColumnElement[bool]] = [
        LaborContract.is_deleted.is_(False),
        LaborContract.archive_status == LaborContract.ARCHIVE_UNARCHIVED,
    ]
    if department:
        conds.append(LaborContract.department == department)
    rows = (await db.execute(
        select(LaborContract).where(*conds).order_by(
            LaborContract.department.asc(),
            LaborContract.employee_number.asc(),
            LaborContract.seq_no.asc(),
        )
    )).scalars().all()
    return list(rows)


async def map_contracts_for_numbers(
    db: AsyncSession, employee_numbers: list[str]
) -> dict[str, list[LaborContract]]:
    """多工号合同批量聚合（按签订次数升序），返回 {工号: [合同]}；聚合视图免 N+1。"""
    result: dict[str, list[LaborContract]] = {n: [] for n in employee_numbers}
    if not employee_numbers:
        return result
    rows = (await db.execute(
        select(LaborContract).where(
            LaborContract.employee_number.in_(employee_numbers),
            LaborContract.is_deleted.is_(False),
        ).order_by(LaborContract.seq_no.asc())
    )).scalars().all()
    for contract in rows:
        result.setdefault(contract.employee_number, []).append(contract)
    return result


# ─── 扫描件版本 ───


async def list_versions(
    db: AsyncSession, contract_id: UUID
) -> list[ContractArchiveVersion]:
    """某份合同的全部扫描件版本（新→旧）。"""
    rows = (await db.execute(
        select(ContractArchiveVersion).where(
            ContractArchiveVersion.contract_id == contract_id,
            ContractArchiveVersion.is_deleted.is_(False),
        ).order_by(ContractArchiveVersion.version_no.desc())
    )).scalars().all()
    return list(rows)


async def get_version(
    db: AsyncSession, version_id: UUID
) -> ContractArchiveVersion | None:
    return (await db.execute(
        select(ContractArchiveVersion).where(
            ContractArchiveVersion.id == version_id,
            ContractArchiveVersion.is_deleted.is_(False),
        )
    )).scalar_one_or_none()


async def get_current_version(
    db: AsyncSession, contract_id: UUID
) -> ContractArchiveVersion | None:
    return (await db.execute(
        select(ContractArchiveVersion).where(
            ContractArchiveVersion.contract_id == contract_id,
            ContractArchiveVersion.is_current.is_(True),
            ContractArchiveVersion.is_deleted.is_(False),
        )
    )).scalar_one_or_none()


async def max_version_no(db: AsyncSession, contract_id: UUID) -> int:
    return int((await db.execute(
        select(func.max(ContractArchiveVersion.version_no)).where(
            ContractArchiveVersion.contract_id == contract_id,
            ContractArchiveVersion.is_deleted.is_(False),
        )
    )).scalar_one() or 0)


async def list_pending_approval_sync(db: AsyncSession) -> list[LaborContract]:
    """公告期中已发起飞书审批、待回写结果的合同。"""
    rows = (await db.execute(
        select(LaborContract).where(
            LaborContract.is_deleted.is_(False),
            LaborContract.status == LaborContract.STATUS_PENDING_RENEWAL,
            LaborContract.approval_mode == LaborContract.APPROVAL_FEISHU,
            LaborContract.approval_instance_code.is_not(None),
        )
    )).scalars().all()
    return list(rows)


async def update(db: AsyncSession, contract: LaborContract) -> LaborContract:
    db.add(contract)
    await db.flush()
    return contract
