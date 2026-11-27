"""劳动合同数据读写：只做查询与持久化，不含业务语义判断。"""

from datetime import date
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.labor_contract.models import (
    ContractArchiveVersion,
    ContractNoticeLog,
    LaborContract,
)
from app.modules.hr.models import DepartureRecord, Employee

# 台账人群口径（两本台账不交叉）：在职台账只放在职人员合同，离职人员合同归离职台账
POPULATION_IN_SERVICE = "in_service"
POPULATION_DEPARTED = "departed"
POPULATION_ALL = "all"

# 历史行：已续签取代 / 已终止。在职台账缺省视图不展示（显式要历史或按状态筛时才返回）
HISTORY_STATUSES = (LaborContract.STATUS_SUPERSEDED, LaborContract.STATUS_TERMINATED)


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


def pending_offboarding_expr() -> ColumnElement[bool]:
    """「离职办理中」：离职台账里有未删除、且离职日期 ≥ 今天的记录（登记了将要离职的人）。

    这些人已在走离职流程，合同不再进入到期预警 / 公告期，也不给部门负责人发审批提醒。
    """
    return exists().where(
        DepartureRecord.employee_number == LaborContract.employee_number,
        DepartureRecord.is_deleted.is_(False),
        DepartureRecord.offboarding_date.is_not(None),
        DepartureRecord.offboarding_date >= date.today(),
    )


# ─── 「待我处理」口径（统计与列表筛选共用同一组谓词，避免两处漂移）───

TODO_PENDING_DEPT_APPROVAL = "pending_dept_approval"
TODO_TO_RENEW = "to_renew"
TODO_TO_STAMP = "to_stamp"
TODO_TO_DELIVER = "to_deliver"
TODO_TO_ARCHIVE = "to_archive"
TODO_PENDING_RENEWAL = "pending_renewal"
TODO_EXPIRED_UNRENEWED = "expired_unrenewed"
# 前 5 项是 HR 手上要办的事（合计 = attention_total），后 2 项是存量提示
ATTENTION_KEYS = (
    TODO_PENDING_DEPT_APPROVAL, TODO_TO_RENEW, TODO_TO_STAMP,
    TODO_TO_DELIVER, TODO_TO_ARCHIVE,
)
TODO_KEYS = (*ATTENTION_KEYS, TODO_PENDING_RENEWAL, TODO_EXPIRED_UNRENEWED)
# 列表筛选额外支持「全部待办」= 五项的并集（合同页默认视图，等于 stats 的 attention_total）
TODO_ATTENTION = "attention"
LIST_TODO_KEYS = (*TODO_KEYS, TODO_ATTENTION)


def todo_expr(todo: str) -> ColumnElement[bool]:
    """某个「待我处理」口径的 SQL 谓词（count_todos 与 list_page 都用这一份）。"""
    lc = LaborContract
    predicates: dict[str, ColumnElement[bool]] = {
        # 公告期且还没登记部门意见
        TODO_PENDING_DEPT_APPROVAL: and_(
            lc.status == lc.STATUS_PENDING_RENEWAL, lc.dept_decision.is_(None),
        ),
        # 部门已同意、新合同还没生成
        TODO_TO_RENEW: lc.status == lc.STATUS_RENEWING,
        # 续签生成的新合同：盖章 → 领取（领取即签收）
        TODO_TO_STAMP: and_(
            lc.origin == lc.ORIGIN_RENEWAL, lc.status == lc.STATUS_ACTIVE, lc.stamped_at.is_(None),
        ),
        TODO_TO_DELIVER: and_(
            lc.origin == lc.ORIGIN_RENEWAL, lc.stamped_at.is_not(None), lc.delivered_at.is_(None),
        ),
        TODO_TO_ARCHIVE: and_(
            lc.delivered_at.is_not(None), lc.archive_status == lc.ARCHIVE_UNARCHIVED,
        ),
        TODO_PENDING_RENEWAL: lc.status == lc.STATUS_PENDING_RENEWAL,
        TODO_EXPIRED_UNRENEWED: lc.status == lc.STATUS_EXPIRED_UNRENEWED,
    }
    predicates[TODO_ATTENTION] = or_(*(predicates[key] for key in ATTENTION_KEYS))
    if todo not in predicates:
        raise ValueError(f"未知的待办口径: {todo}")
    return predicates[todo]


def population_conds(population: str) -> list[ColumnElement[bool]]:
    """台账人群条件：in_service 在职 / departed 离职 / all 全部（始终排除软删行）。"""
    conds: list[ColumnElement[bool]] = [LaborContract.is_deleted.is_(False)]
    if population == POPULATION_IN_SERVICE:
        conds.append(not_(departed_expr()))
    elif population == POPULATION_DEPARTED:
        conds.append(departed_expr())
    return conds


def education_in_expr(educations: list[str]) -> ColumnElement[bool]:
    """员工档案学历命中任一取值（合同行按工号关联 hr.employees）。"""
    return exists().where(
        Employee.employee_number == LaborContract.employee_number,
        Employee.is_deleted.is_(False),
        Employee.education.in_(educations),
    )


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
    todo: str | None = None,
    educations: list[str] | None = None,
    exclude_history: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> tuple[int, list[LaborContract]]:
    """台账分页查询。departments 为 None 表示不限部门（HR 全量）。

    employee_number：self_only 数据范围按工号收敛到本人；
    population：in_service（缺省，在职台账）/ departed（离职人员合同）/ all（电子档案库全量）；
    order_by="department"：按部门-工号-签订次数排序（档案库/补扫清单按部门分组用）；
    todo：「待我处理」口径键（谓词见 todo_expr，与 count_todos 同一份）；
    educations：员工档案学历 IN 过滤；
    exclude_history：未按 status / todo 筛选时排除已续签取代、已终止的历史行。
    """
    conds = population_conds(population)
    if departments is not None:
        if not departments:
            return 0, []
        conds.append(LaborContract.department.in_(departments))
    if statuses:
        conds.append(LaborContract.status.in_(statuses))
    if todo:
        conds.append(todo_expr(todo))
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
    if educations:
        conds.append(education_in_expr(educations))
    if expiring_within_days is not None:
        today = date.today()
        deadline = today.fromordinal(today.toordinal() + expiring_within_days)
        conds.append(LaborContract.end_date.is_not(None))
        conds.append(LaborContract.end_date >= today)
        conds.append(LaborContract.end_date <= deadline)
    if exclude_history and not statuses and not todo:
        conds.append(LaborContract.status.notin_(HISTORY_STATUSES))

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


async def count_todos(
    db: AsyncSession, *,
    departments: frozenset[str] | None = None,
    employee_number: str | None = None,
    population: str = POPULATION_IN_SERVICE,
) -> dict[str, int]:
    """各「待我处理」口径的计数（人群、数据范围、谓词都与 list_page 一致）。"""
    counts = dict.fromkeys(TODO_KEYS, 0)
    if departments is not None and not departments:
        return counts
    conds = population_conds(population)
    if departments is not None:
        conds.append(LaborContract.department.in_(departments))
    if employee_number:
        conds.append(LaborContract.employee_number == employee_number)
    row = (await db.execute(
        select(*(func.count().filter(todo_expr(key)).label(key) for key in TODO_KEYS))
        .select_from(LaborContract).where(*conds)
    )).one()
    # 按位置取值：列顺序即 TODO_KEYS 的顺序（异步驱动的 Row 不保证支持按列名取值）
    return {key: int(value) for key, value in zip(TODO_KEYS, row, strict=True)}


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


async def map_education(
    db: AsyncSession, employee_numbers: list[str],
) -> dict[str, str | None]:
    """按工号批量取学历 {工号: 学历}（台账行展示用；员工档案一个工号只有一行）。"""
    if not employee_numbers:
        return {}
    rows = (await db.execute(
        select(Employee.employee_number, Employee.education).where(
            Employee.employee_number.in_(employee_numbers),
            Employee.is_deleted.is_(False),
        )
    )).all()
    return {number: education for number, education in rows}


async def distinct_departments(
    db: AsyncSession, *, departments: frozenset[str] | None = None,
    employee_number: str | None = None,
) -> list[str]:
    """有合同行的部门（去重升序）。departments=None 不限，空集即无范围。"""
    if departments is not None and not departments:
        return []
    conds: list[ColumnElement[bool]] = [LaborContract.is_deleted.is_(False)]
    if departments is not None:
        conds.append(LaborContract.department.in_(departments))
    if employee_number:
        conds.append(LaborContract.employee_number == employee_number)
    rows = (await db.execute(
        select(LaborContract.department).where(*conds)
        .distinct().order_by(LaborContract.department.asc())
    )).scalars().all()
    return list(rows)


async def distinct_education(
    db: AsyncSession, *, departments: frozenset[str] | None = None,
    employee_number: str | None = None,
) -> list[str]:
    """有合同行的员工档案学历取值（去重；排序与脏值过滤由 archive_service 处理）。"""
    if departments is not None and not departments:
        return []
    contract_conds: list[ColumnElement[bool]] = [
        LaborContract.employee_number == Employee.employee_number,
        LaborContract.is_deleted.is_(False),
    ]
    if departments is not None:
        contract_conds.append(LaborContract.department.in_(departments))
    if employee_number:
        contract_conds.append(LaborContract.employee_number == employee_number)
    rows = (await db.execute(
        select(Employee.education).where(
            Employee.is_deleted.is_(False),
            Employee.education.is_not(None),
            exists().where(*contract_conds),
        ).distinct()
    )).scalars().all()
    return [value for value in rows if value]


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


# 未完结合同的状态（离职归入、办结终止、续签范围共用）
OPEN_STATUSES = (
    LaborContract.STATUS_ACTIVE,
    LaborContract.STATUS_PENDING_RENEWAL,
    LaborContract.STATUS_RENEWING,
    LaborContract.STATUS_EXPIRED_UNRENEWED,
)


async def list_open_contracts(
    db: AsyncSession, *, employee_number: str | None = None,
) -> list[LaborContract]:
    """未完结合同（active / pending_renewal / renewing / expired_unrenewed）；指定工号只取该员工。"""
    conds: list[ColumnElement[bool]] = [
        LaborContract.is_deleted.is_(False),
        LaborContract.status.in_(OPEN_STATUSES),
    ]
    if employee_number:
        conds.append(LaborContract.employee_number == employee_number)
    rows = (await db.execute(
        select(LaborContract).where(*conds).order_by(LaborContract.employee_number.asc())
    )).scalars().all()
    return list(rows)


async def list_unarchived(
    db: AsyncSession, *, department: str | None = None,
    educations: list[str] | None = None,
) -> list[LaborContract]:
    """未归档合同（在职 + 离职；含已续签取代/已终止——原合同同样要归档保留）。"""
    conds: list[ColumnElement[bool]] = [
        LaborContract.is_deleted.is_(False),
        LaborContract.archive_status == LaborContract.ARCHIVE_UNARCHIVED,
    ]
    if department:
        conds.append(LaborContract.department == department)
    if educations:
        conds.append(education_in_expr(educations))
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


# ─── 通知留痕 ───


async def list_notices(
    db: AsyncSession, contract_id: UUID, *, limit: int = 20,
) -> list[ContractNoticeLog]:
    """某份合同的通知留痕（新→旧）。"""
    rows = (await db.execute(
        select(ContractNoticeLog).where(
            ContractNoticeLog.contract_id == contract_id,
            ContractNoticeLog.is_deleted.is_(False),
        ).order_by(ContractNoticeLog.created_at.desc()).limit(limit)
    )).scalars().all()
    return list(rows)


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
