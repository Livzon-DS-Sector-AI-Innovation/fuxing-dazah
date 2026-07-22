"""培训台账管理员路由：部门筛选、成绩批量录入、统计。"""

from datetime import date
from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.hr.deps import HrAccessContext, require_hr_access
from app.modules.hr.schemas import BatchScoreUpdate
from app.shared.module_api import create_module_router
from app.shared.module_registry import MODULES_BY_CODE

router = create_module_router(MODULES_BY_CODE["hr"])


@router.get("/training-ledgers/admin", summary="管理员培训台账总览")
async def admin_list_training_ledgers(
    department: str | None = Query(None, description="部门筛选"),
    training_subject: str | None = Query(None, description="培训内容筛选"),
    date_from: date | None = Query(None, description="培训日期起"),
    date_to: date | None = Query(None, description="培训日期止"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:read")),
):
    """管理员视角：按部门+培训内容筛选所有员工的培训台账记录，关联员工表获取姓名和部门。"""
    from app.modules.hr.models import Employee, TrainingLedger

    cols = (
        TrainingLedger.id, TrainingLedger.employee_number,
        Employee.name.label("employee_name"), Employee.department.label("department"),
        TrainingLedger.training_date, TrainingLedger.training_subject,
        TrainingLedger.training_method, TrainingLedger.duration_hours,
        TrainingLedger.location, TrainingLedger.trainer,
        TrainingLedger.assessment_result, TrainingLedger.source_type,
        TrainingLedger.remarks, TrainingLedger.created_at, TrainingLedger.updated_at,
    )

    base = (
        select(*cols).select_from(TrainingLedger)
        .join(Employee, TrainingLedger.employee_number == Employee.employee_number)
        .where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
    )
    count_base = (
        select(func.count()).select_from(TrainingLedger)
        .join(Employee, TrainingLedger.employee_number == Employee.employee_number)
        .where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
    )

    if department:
        base = base.where(Employee.department == department)
        count_base = count_base.where(Employee.department == department)
    if training_subject:
        base = base.where(TrainingLedger.training_subject.ilike(f"%{training_subject}%"))
        count_base = count_base.where(TrainingLedger.training_subject.ilike(f"%{training_subject}%"))
    if date_from:
        base = base.where(TrainingLedger.training_date >= date_from)
        count_base = count_base.where(TrainingLedger.training_date >= date_from)
    if date_to:
        base = base.where(TrainingLedger.training_date <= date_to)
        count_base = count_base.where(TrainingLedger.training_date <= date_to)

    total = (await session.execute(count_base)).scalar() or 0
    rows = (await session.execute(
        base.order_by(TrainingLedger.training_date.desc(), Employee.department, Employee.name)
        .offset((page - 1) * page_size).limit(page_size)
    )).all()

    data = [{
        "id": str(r[0]), "employee_number": r[1], "employee_name": r[2] or "",
        "department": r[3] or "", "training_date": r[4].isoformat() if r[4] else None,
        "training_subject": r[5] or "", "training_method": r[6],
        "duration_hours": r[7], "location": r[8], "trainer": r[9],
        "assessment_result": r[10], "source_type": r[11] or "manual",
        "remarks": r[12], "created_at": r[13].isoformat() if r[13] else None,
        "updated_at": r[14].isoformat() if r[14] else None,
    } for r in rows]
    return paginated_response(data=data, page=page, page_size=page_size, total=total)


@router.get("/training-ledgers/admin/subjects", summary="台账中的培训内容列表")
async def admin_list_training_subjects(
    department: str | None = Query(None, description="部门筛选"),
    session: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:read")),
):
    """返回培训台账中不重复的培训内容，可按部门筛选。"""
    from app.modules.hr.models import Employee, TrainingLedger

    stmt = (
        select(TrainingLedger.training_subject).select_from(TrainingLedger)
        .join(Employee, TrainingLedger.employee_number == Employee.employee_number)
        .where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
    )
    if department:
        stmt = stmt.where(Employee.department == department)
    stmt = stmt.distinct().order_by(TrainingLedger.training_subject)
    rows = (await session.execute(stmt)).all()
    return success_response(data=[r[0] for r in rows if r[0]])


@router.get("/training-ledgers/admin/departments", summary="台账中的部门列表")
async def admin_list_ledger_departments(
    session: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:read")),
):
    """返回培训台账中涉及的不重复部门（通过员工表关联）。"""
    from app.modules.hr.models import Employee, TrainingLedger

    stmt = (
        select(Employee.department).select_from(TrainingLedger)
        .join(Employee, TrainingLedger.employee_number == Employee.employee_number)
        .where(TrainingLedger.is_deleted == False, Employee.is_deleted == False)
        .distinct().order_by(Employee.department)
    )
    rows = (await session.execute(stmt)).all()
    return success_response(data=[r[0] for r in rows if r[0]])


@router.put("/training-ledgers/batch-scores", summary="批量录入考核成绩")
async def batch_update_training_scores(
    payload: BatchScoreUpdate,
    session: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:manage")),
):
    """批量更新培训台账记录的考核成绩。"""
    updated = 0
    for item in payload.records:
        result = await session.execute(
            text("UPDATE hr.training_ledgers SET assessment_result = :score, updated_at = now() "
                 "WHERE id = :id AND is_deleted = false"),
            {"score": item.assessment_result, "id": item.id},
        )
        updated += result.rowcount or 0
    await session.commit()
    return success_response(data={"updated": updated}, message=f"成功更新 {updated} 条记录")


@router.get("/training-ledgers/admin/stats", summary="培训台账统计")
async def get_training_ledger_stats(
    department: str | None = Query(None),
    training_subject: str | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    session: AsyncSession = Depends(get_db),
    ctx: HrAccessContext = Depends(require_hr_access("hr:training:read")),
):
    """根据筛选条件自动计算合格率、实到人数等统计数据。合格线为 >= 80 分。"""
    from app.modules.hr.models import Employee, TrainingLedger
    from sqlalchemy import Integer

    base_where = (TrainingLedger.is_deleted == False, Employee.is_deleted == False)
    if department:
        base_where += (Employee.department == department,)
    if training_subject:
        base_where += (TrainingLedger.training_subject.ilike(f"%{training_subject}%"),)
    if date_from:
        base_where += (TrainingLedger.training_date >= date_from,)
    if date_to:
        base_where += (TrainingLedger.training_date <= date_to,)

    def _count(extra=()):
        stmt = select(func.count()).select_from(TrainingLedger).join(
            Employee, TrainingLedger.employee_number == Employee.employee_number
        ).where(*(base_where + extra))
        return stmt

    total_count = (await session.execute(_count())).scalar() or 0
    assessed_count = (await session.execute(_count((
        TrainingLedger.assessment_result.isnot(None),
        TrainingLedger.assessment_result != "",
    )))).scalar() or 0

    qualified_count = (await session.execute(_count((
        TrainingLedger.assessment_result.isnot(None),
        TrainingLedger.assessment_result != "",
        (
            TrainingLedger.assessment_result.in_(["合格", "优秀"])
            | (func.coalesce(func.nullif(
                func.regexp_replace(TrainingLedger.assessment_result, r"[^0-9.]", "", "g"), ""
            ), "-1").cast(Integer) >= 80)
        ),
    )))).scalar() or 0

    unqualified_count = assessed_count - qualified_count
    pass_rate = f"{round(qualified_count / assessed_count * 100, 1)}%" if assessed_count > 0 else "0%"

    avg_row = (await session.execute(
        select(func.avg(
            func.nullif(func.regexp_replace(TrainingLedger.assessment_result, r"[^0-9.]", "", "g"), "").cast(Integer)
        )).select_from(TrainingLedger).join(
            Employee, TrainingLedger.employee_number == Employee.employee_number
        ).where(
            *base_where,
            TrainingLedger.assessment_result.isnot(None),
            TrainingLedger.assessment_result != "",
            TrainingLedger.assessment_result.op("~")("^[0-9]+"),
        )
    )).scalar()

    return success_response(data={
        "total_count": total_count, "assessed_count": assessed_count,
        "qualified_count": qualified_count, "unqualified_count": unqualified_count,
        "pass_rate": pass_rate,
        "avg_score": round(float(avg_row), 1) if avg_row else None,
    })
