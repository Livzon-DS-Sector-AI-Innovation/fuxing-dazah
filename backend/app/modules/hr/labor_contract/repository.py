"""劳动合同数据读写：只做查询与持久化，不含业务语义判断。"""

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract.models import LaborContract
from app.modules.hr.models import DepartureRecord, Employee


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
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[LaborContract]]:
    """台账分页查询。departments 为 None 表示不限部门（HR 全量）。"""
    conds: list[ColumnElement[bool]] = [LaborContract.is_deleted.is_(False)]
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
    if expiring_within_days is not None:
        today = date.today()
        deadline = today.fromordinal(today.toordinal() + expiring_within_days)
        conds.append(LaborContract.end_date.is_not(None))
        conds.append(LaborContract.end_date >= today)
        conds.append(LaborContract.end_date <= deadline)

    total = (await db.execute(
        select(func.count()).select_from(LaborContract).where(*conds)
    )).scalar_one()
    rows = (await db.execute(
        select(LaborContract).where(*conds)
        .order_by(
            LaborContract.end_date.asc().nulls_last(),
            LaborContract.employee_number.asc(),
            LaborContract.seq_no.desc(),
        )
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
