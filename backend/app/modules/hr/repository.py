"""HR database queries live here."""

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import asc, delete, desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.hr.models import (
    AnnualTrainingPlan,
    AnnualTrainingPlanItem,
    Candidate,
    CandidateAiEvaluation,
    CandidateReview,
    CandidateStatusLog,
    DepartureRecord,
    Employee,
    HrDepartment,
    Interview,
    JobRequirement,
    OffboardingRecord,
    OnboardingRecord,
    Team,
    TrainingLedger,
    TrainingLedgerPage,
)

class EmployeeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, employee_id: UUID) -> Employee | None:
        result = await self.session.execute(
            select(Employee).where(Employee.id == employee_id, Employee.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_employee_number(
        self, employee_number: str, *, include_deleted: bool = False
    ) -> Employee | None:
        stmt = select(Employee).where(
            Employee.employee_number == employee_number,
        )
        if not include_deleted:
            stmt = stmt.where(Employee.is_deleted.is_(False))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_employees(
        self,
        *,
        department: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        team: str | None = None,
        position: str | None = None,
        job_category: str | None = None,
        level: str | None = None,
        gender: str | None = None,
        education: str | None = None,
        political_status: str | None = None,
        marital_status: str | None = None,
        status_category: str | None = None,
        age_min: int | None = None,
        age_max: int | None = None,
        birth_year_min: int | None = None,
        birth_year_max: int | None = None,
        hire_date_after: date | None = None,
        hire_date_before: date | None = None,
        factory_entry_date_after: date | None = None,
        factory_entry_date_before: date | None = None,
        work_start_date_after: date | None = None,
        work_start_date_before: date | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "sort_order",
        sort_order: str = "asc",
    ) -> tuple[list[Employee], int]:
        stmt = select(Employee).where(Employee.is_deleted.is_(False))

        if department:
            stmt = stmt.where(Employee.department.ilike(f"{department}%"))
        if status:
            stmt = stmt.where(Employee.status == status)
        else:
            # 默认排除待审批和离职员工，只有显式筛选时才显示
            stmt = stmt.where(Employee.status != "待审批", Employee.status != "离职")
        if keyword:
            stmt = stmt.where(
                Employee.name.ilike(f"{keyword}%")
                | Employee.employee_number.ilike(f"{keyword}%")
            )
        if team:
            stmt = stmt.where(Employee.team == team)
        if position:
            stmt = stmt.where(Employee.position.ilike(f"{position}%"))
        if job_category:
            stmt = stmt.where(Employee.job_category == job_category)
        if level:
            stmt = stmt.where(Employee.level == level)
        if gender:
            stmt = stmt.where(Employee.gender == gender)
        if education:
            stmt = stmt.where(Employee.education == education)
        if political_status:
            stmt = stmt.where(Employee.political_status == political_status)
        if marital_status:
            stmt = stmt.where(Employee.marital_status == marital_status)
        if status_category:
            stmt = stmt.where(Employee.status_category == status_category)
        if age_min is not None:
            stmt = stmt.where(Employee.age >= age_min)
        if age_max is not None:
            stmt = stmt.where(Employee.age <= age_max)
        if birth_year_min is not None:
            stmt = stmt.where(Employee.birth_year >= birth_year_min)
        if birth_year_max is not None:
            stmt = stmt.where(Employee.birth_year <= birth_year_max)
        if hire_date_after:
            stmt = stmt.where(Employee.hire_date >= hire_date_after)
        if hire_date_before:
            stmt = stmt.where(Employee.hire_date <= hire_date_before)
        if factory_entry_date_after:
            stmt = stmt.where(Employee.factory_entry_date >= factory_entry_date_after)
        if factory_entry_date_before:
            stmt = stmt.where(Employee.factory_entry_date <= factory_entry_date_before)
        if work_start_date_after:
            stmt = stmt.where(Employee.work_start_date >= work_start_date_after)
        if work_start_date_before:
            stmt = stmt.where(Employee.work_start_date <= work_start_date_before)

        # 并行执行 COUNT 和数据查询，减少 TTFB
        count_stmt = select(func.count()).select_from(stmt.subquery())
        sort_column = getattr(Employee, sort_by, Employee.created_at)
        order_func = desc if sort_order == "desc" else asc
        data_stmt = (
            stmt.order_by(order_func(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        # NOTE: asyncio.gather 在共享 AsyncSession 下可能无法真正并行，
        # 且小数据量时顺序执行更稳定。保留顺序执行。
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        data_result = await self.session.execute(data_stmt)
        return list(data_result.scalars().all()), total

    async def create(self, employee: Employee) -> Employee:
        self.session.add(employee)
        await self.session.flush()
        await self.session.refresh(employee)
        return employee

    async def update(self, employee: Employee) -> Employee:
        await self.session.flush()
        await self.session.refresh(employee)
        return employee

    async def get_by_name_and_department(self, name: str, department: str) -> Employee | None:
        """按姓名+部门精确匹配一位员工。"""
        result = await self.session.execute(
            select(Employee).where(
                Employee.name == name,
                Employee.department == department,
                Employee.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def upsert_by_employee_number(self, data: dict) -> bool:
        """UPDATE-then-INSERT 策略：先 UPDATE，成功则完成；否则 INSERT。

        UPDATE 永远不会触发 UniqueViolationError。
        即使 INSERT 与并发请求产生极低概率的竞态，也会捕获异常后回退到 UPDATE。

        UPDATE 使用原始 data（含 None → 设为 NULL），INSERT 过滤掉 None。
        Returns True if a new record was created, False if updated.
        """
        from sqlalchemy.exc import IntegrityError

        insert_data = {k: v for k, v in data.items() if v is not None}

        # ── 构建 SET 子句（UPDATE 含 None 值 → NULL）──
        skip_update = {"id", "employee_number", "created_at"}
        set_parts = []
        for c in data:  # 用原始 data，包含 None → NULL
            if c not in skip_update:
                set_parts.append(f"{c} = :{c}")
        set_parts.append("is_deleted = false")
        set_parts.append("updated_at = now()")

        sql_update = text(
            f"UPDATE hr.employees SET {', '.join(set_parts)} "
            f"WHERE employee_number = :employee_number"
        )

        conn = await self.session.connection()

        # ── Step 1: 先 UPDATE（含 None → NULL）──
        result = await conn.execute(sql_update, data)
        if result.rowcount and result.rowcount > 0:
            return False  # 更新成功

        # ── Step 2: 确认不存在，INSERT（过滤 None）──
        columns = list(insert_data.keys())
        col_names = "id, " + ", ".join(columns) + ", created_at"
        placeholders = "gen_random_uuid(), " + ", ".join(f":{c}" for c in columns) + ", now()"
        sql_insert = text(
            f"INSERT INTO hr.employees ({col_names}) "
            f"VALUES ({placeholders})"
        )

        try:
            await conn.execute(sql_insert, insert_data)
            return True
        except IntegrityError:
            # 极低概率竞态：UPDATE 后 INSERT 前，另一请求插入了同工号
            # 此时回退到 UPDATE
            await conn.execute(sql_update, data)
            return False

    async def count_total(self) -> int:
        result = await self.session.execute(
            select(func.count()).where(Employee.is_deleted.is_(False))
        )
        return result.scalar() or 0

    def _apply_filters(self, stmt, **filters) -> Any:
        """Apply common filters to a select statement."""
        if filters.get("department"):
            stmt = stmt.where(Employee.department.ilike(f"{filters['department']}%"))
        if filters.get("status"):
            stmt = stmt.where(Employee.status == filters["status"])
        else:
            stmt = stmt.where(Employee.status.not_in(["待审批", "离职"]))
        if filters.get("keyword"):
            stmt = stmt.where(
                Employee.name.ilike(f"{filters['keyword']}%")
                | Employee.employee_number.ilike(f"{filters['keyword']}%")
            )
        if filters.get("team"):
            stmt = stmt.where(Employee.team == filters["team"])
        if filters.get("position"):
            stmt = stmt.where(Employee.position.ilike(f"{filters['position']}%"))
        if filters.get("job_category"):
            stmt = stmt.where(Employee.job_category == filters["job_category"])
        if filters.get("level"):
            stmt = stmt.where(Employee.level == filters["level"])
        if filters.get("gender"):
            stmt = stmt.where(Employee.gender == filters["gender"])
        if filters.get("education"):
            stmt = stmt.where(Employee.education == filters["education"])
        if filters.get("political_status"):
            stmt = stmt.where(Employee.political_status == filters["political_status"])
        if filters.get("marital_status"):
            stmt = stmt.where(Employee.marital_status == filters["marital_status"])
        if filters.get("status_category"):
            stmt = stmt.where(Employee.status_category == filters["status_category"])
        if filters.get("age_min") is not None:
            stmt = stmt.where(Employee.age >= filters["age_min"])
        if filters.get("age_max") is not None:
            stmt = stmt.where(Employee.age <= filters["age_max"])
        if filters.get("birth_year_min") is not None:
            stmt = stmt.where(Employee.birth_year >= filters["birth_year_min"])
        if filters.get("birth_year_max") is not None:
            stmt = stmt.where(Employee.birth_year <= filters["birth_year_max"])
        if filters.get("hire_date_after"):
            stmt = stmt.where(Employee.hire_date >= filters["hire_date_after"])
        if filters.get("hire_date_before"):
            stmt = stmt.where(Employee.hire_date <= filters["hire_date_before"])
        if filters.get("factory_entry_date_after"):
            stmt = stmt.where(
                Employee.factory_entry_date >= filters["factory_entry_date_after"]
            )
        if filters.get("factory_entry_date_before"):
            stmt = stmt.where(
                Employee.factory_entry_date <= filters["factory_entry_date_before"]
            )
        if filters.get("work_start_date_after"):
            stmt = stmt.where(
                Employee.work_start_date >= filters["work_start_date_after"]
            )
        if filters.get("work_start_date_before"):
            stmt = stmt.where(
                Employee.work_start_date <= filters["work_start_date_before"]
            )
        return stmt

    async def group_count(self, field_name: str, **filters) -> list[dict]:
        """Group employees by a field and count occurrences.

        Returns:
            List of {"value": field_value, "count": int} sorted by count descending.
        """
        field = getattr(Employee, field_name, None)
        if field is None:
            return []

        stmt = select(field, func.count().label("count")).where(
            Employee.is_deleted.is_(False)
        )
        stmt = self._apply_filters(stmt, **filters)
        stmt = stmt.group_by(field).order_by(desc("count"))
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            {"value": row[0], "count": row[1]}
            for row in rows
            if row[0] is not None
        ]

    async def get_distinct_values(self, field_name: str, **filters) -> list[str]:
        """Get distinct non-null values for a field.

        Returns:
            List of distinct values.
        """
        field = getattr(Employee, field_name, None)
        if field is None:
            return []

        stmt = select(field).where(Employee.is_deleted.is_(False)).distinct()
        stmt = self._apply_filters(stmt, **filters)
        result = await self.session.execute(stmt)
        rows = result.all()
        return [row[0] for row in rows if row[0] is not None]

    async def soft_delete(self, employee: Employee) -> None:
        employee.is_deleted = True
        await self.session.flush()

class DepartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, department_id: UUID) -> HrDepartment | None:
        result = await self.session.execute(
            select(HrDepartment).where(HrDepartment.id == department_id, HrDepartment.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> HrDepartment | None:
        # 包含已删除记录，确保唯一性检查覆盖软删除数据
        result = await self.session.execute(
            select(HrDepartment).where(HrDepartment.code == code)
        )
        return result.scalar_one_or_none()

    async def list_departments(
        self,
        *,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[HrDepartment], int]:
        stmt = select(HrDepartment).where(HrDepartment.is_deleted.is_(False))

        if keyword:
            stmt = stmt.where(
                HrDepartment.name.ilike(f"%{keyword}%")
                | HrDepartment.code.ilike(f"%{keyword}%")
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(asc(HrDepartment.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, department: HrDepartment) -> HrDepartment:
        self.session.add(department)
        await self.session.flush()
        await self.session.refresh(department)
        return department

    async def update(self, department: HrDepartment) -> HrDepartment:
        await self.session.flush()
        await self.session.refresh(department)
        return department

    async def soft_delete(self, department: HrDepartment) -> None:
        department.is_deleted = True
        await self.session.flush()

class TeamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, team_id: UUID) -> Team | None:
        result = await self.session.execute(
            select(Team)
            .where(Team.id == team_id, Team.is_deleted.is_(False))
            .options(selectinload(Team.department))
        )
        return result.scalar_one_or_none()

    async def list_teams(
        self,
        *,
        department_id: UUID | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Team], int]:
        stmt = select(Team).where(Team.is_deleted.is_(False)).options(
            selectinload(Team.department)
        )

        if department_id:
            stmt = stmt.where(Team.department_id == department_id)
        if keyword:
            stmt = stmt.where(
                Team.name.ilike(f"%{keyword}%")
                | Team.code.ilike(f"%{keyword}%")
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(asc(Team.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, team: Team) -> Team:
        self.session.add(team)
        await self.session.flush()
        await self.session.refresh(team)
        return team

    async def update(self, team: Team) -> Team:
        await self.session.flush()
        await self.session.refresh(team)
        return team

    async def soft_delete(self, team: Team) -> None:
        team.is_deleted = True
        await self.session.flush()

class OffboardingRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: UUID) -> OffboardingRecord | None:
        result = await self.session.execute(
            select(OffboardingRecord)
            .where(OffboardingRecord.id == record_id, OffboardingRecord.is_deleted.is_(False))
            .options(selectinload(OffboardingRecord.employee))
        )
        return result.scalar_one_or_none()

    async def list_records(
        self,
        *,
        employee_id: UUID | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[OffboardingRecord], int]:
        stmt = (
            select(OffboardingRecord)
            .where(OffboardingRecord.is_deleted.is_(False))
            .options(selectinload(OffboardingRecord.employee))
        )

        if employee_id:
            stmt = stmt.where(OffboardingRecord.employee_id == employee_id)
        if keyword:
            stmt = stmt.join(Employee).where(
                Employee.name.ilike(f"%{keyword}%")
                | Employee.employee_number.ilike(f"%{keyword}%")
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(desc(OffboardingRecord.created_at))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, record: OffboardingRecord) -> OffboardingRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def update(self, record: OffboardingRecord) -> OffboardingRecord:
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def soft_delete(self, record: OffboardingRecord) -> None:
        record.is_deleted = True
        await self.session.flush()

class OnboardingRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: UUID) -> OnboardingRecord | None:
        result = await self.session.execute(
            select(OnboardingRecord).where(
                OnboardingRecord.id == record_id,
                OnboardingRecord.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_records(
        self,
        *,
        department: str | None = None,
        position: str | None = None,
        is_employed: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        days: int = 7,
    ) -> tuple[list[OnboardingRecord], int]:
        from datetime import datetime, timedelta, timezone
        stmt = select(OnboardingRecord).where(OnboardingRecord.is_deleted.is_(False))

        # 七天自动清空：只显示最近 N 天内创建的记录
        if days > 0:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            stmt = stmt.where(OnboardingRecord.created_at >= cutoff)

        if department:
            stmt = stmt.where(OnboardingRecord.department == department)
        if position:
            stmt = stmt.where(OnboardingRecord.position.ilike(f"%{position}%"))
        if is_employed:
            stmt = stmt.where(OnboardingRecord.is_employed == is_employed)
        if keyword:
            stmt = stmt.where(
                OnboardingRecord.name.ilike(f"%{keyword}%")
                | OnboardingRecord.employee_number.ilike(f"%{keyword}%")
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        sort_column = getattr(OnboardingRecord, sort_by, OnboardingRecord.created_at)
        order_func = desc if sort_order == "desc" else asc
        data_stmt = (
            stmt.order_by(order_func(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        data_result = await self.session.execute(data_stmt)
        return list(data_result.scalars().all()), total

    async def create(self, record: OnboardingRecord) -> OnboardingRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def update(self, record: OnboardingRecord) -> OnboardingRecord:
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def count_total(self) -> int:
        result = await self.session.execute(
            select(func.count()).where(OnboardingRecord.is_deleted.is_(False))
        )
        return result.scalar() or 0

    async def soft_delete(self, record: OnboardingRecord) -> None:
        record.is_deleted = True
        await self.session.flush()

class DepartureRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: UUID) -> DepartureRecord | None:
        result = await self.session.execute(
            select(DepartureRecord).where(
                DepartureRecord.id == record_id,
                DepartureRecord.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_records(
        self,
        *,
        department: str | None = None,
        offboarding_type: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "offboarding_date",
        sort_order: str = "desc",
    ) -> tuple[list[DepartureRecord], int]:
        stmt = select(DepartureRecord).where(DepartureRecord.is_deleted.is_(False))

        if department:
            stmt = stmt.where(DepartureRecord.department == department)
        if offboarding_type:
            stmt = stmt.where(DepartureRecord.offboarding_type == offboarding_type)
        if keyword:
            stmt = stmt.where(
                DepartureRecord.name.ilike(f"%{keyword}%")
                | DepartureRecord.department.ilike(f"%{keyword}%")
                | DepartureRecord.position.ilike(f"%{keyword}%")
            )

        count_stmt = select(func.count()).select_from(stmt.subquery())
        sort_column = getattr(DepartureRecord, sort_by, DepartureRecord.offboarding_date)
        order_func = desc if sort_order == "desc" else asc
        data_stmt = (
            stmt.order_by(order_func(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        data_result = await self.session.execute(data_stmt)
        return list(data_result.scalars().all()), total

    async def create(self, record: DepartureRecord) -> DepartureRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def update(self, record: DepartureRecord) -> DepartureRecord:
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def count_total(self) -> int:
        result = await self.session.execute(
            select(func.count()).where(DepartureRecord.is_deleted.is_(False))
        )
        return result.scalar() or 0

    async def soft_delete(self, record: DepartureRecord) -> None:
        record.is_deleted = True
        await self.session.flush()

class TrainingLedgerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, record_id: UUID) -> TrainingLedger | None:
        result = await self.session.execute(
            select(TrainingLedger).where(
                TrainingLedger.id == record_id,
                TrainingLedger.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_records(
        self,
        *,
        employee_number: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "training_date",
        sort_order: str = "desc",
        exclude_employee_numbers: Any | None = None,
    ) -> tuple[list[TrainingLedger], int]:
        stmt = select(TrainingLedger).where(TrainingLedger.is_deleted.is_(False))

        if employee_number:
            stmt = stmt.where(TrainingLedger.employee_number == employee_number)
        if date_from:
            stmt = stmt.where(TrainingLedger.training_date >= date_from)
        if date_to:
            stmt = stmt.where(TrainingLedger.training_date <= date_to)
        if exclude_employee_numbers is not None:
            stmt = stmt.where(TrainingLedger.employee_number.not_in(exclude_employee_numbers))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        sort_column = getattr(TrainingLedger, sort_by, TrainingLedger.training_date)
        order_func = desc if sort_order == "desc" else asc
        data_stmt = (
            stmt.order_by(order_func(sort_column))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        data_result = await self.session.execute(data_stmt)
        return list(data_result.scalars().all()), total

    async def create(self, record: TrainingLedger) -> TrainingLedger:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def update(self, record: TrainingLedger) -> TrainingLedger:
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def soft_delete(self, record: TrainingLedger) -> None:
        record.is_deleted = True
        await self.session.flush()

    async def get_by_source(self, source_type: str, source_id: str) -> TrainingLedger | None:
        result = await self.session.execute(
            select(TrainingLedger).where(
                TrainingLedger.source_type == source_type,
                TrainingLedger.source_id == source_id,
                TrainingLedger.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

class TrainingLedgerPageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_pages(self) -> list[TrainingLedgerPage]:
        result = await self.session.execute(
            select(TrainingLedgerPage).where(TrainingLedgerPage.is_deleted.is_(False))
        )
        return list(result.scalars().all())

    async def get_by_employee_number(self, employee_number: str) -> TrainingLedgerPage | None:
        result = await self.session.execute(
            select(TrainingLedgerPage).where(
                TrainingLedgerPage.employee_number == employee_number,
                TrainingLedgerPage.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_pages_with_department(self) -> list[tuple[TrainingLedgerPage, str | None]]:
        """List all training ledger pages joined with employee department."""
        result = await self.session.execute(
            select(TrainingLedgerPage, Employee.department)
            .outerjoin(Employee, TrainingLedgerPage.employee_number == Employee.employee_number)
            .where(TrainingLedgerPage.is_deleted.is_(False))
        )
        return [(row[0], row[1]) for row in result.all()]

    async def create(self, page: TrainingLedgerPage) -> TrainingLedgerPage:
        self.session.add(page)
        await self.session.flush()
        await self.session.refresh(page)
        return page

class AnnualTrainingPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, plan_id: UUID) -> AnnualTrainingPlan | None:
        result = await self.session.execute(
            select(AnnualTrainingPlan)
            .where(AnnualTrainingPlan.id == plan_id, AnnualTrainingPlan.is_deleted.is_(False))
            .options(selectinload(AnnualTrainingPlan.items))
        )
        return result.scalar_one_or_none()

    async def get_by_year_and_department(self, year: int, department: str) -> AnnualTrainingPlan | None:
        result = await self.session.execute(
            select(AnnualTrainingPlan).where(
                AnnualTrainingPlan.year == year,
                AnnualTrainingPlan.department == department,
                AnnualTrainingPlan.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def list_plans(
        self,
        *,
        year: int | None = None,
        department: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AnnualTrainingPlan], int]:
        stmt = select(AnnualTrainingPlan).where(AnnualTrainingPlan.is_deleted.is_(False))

        if year is not None:
            stmt = stmt.where(AnnualTrainingPlan.year == year)
        if department:
            stmt = stmt.where(AnnualTrainingPlan.department.ilike(f"%{department}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(desc(AnnualTrainingPlan.year), asc(AnnualTrainingPlan.department))
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)

        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, plan: AnnualTrainingPlan) -> AnnualTrainingPlan:
        self.session.add(plan)
        await self.session.flush()
        await self.session.refresh(plan)
        return plan

    async def update(self, plan: AnnualTrainingPlan) -> AnnualTrainingPlan:
        await self.session.flush()
        await self.session.refresh(plan)
        return plan

    async def soft_delete(self, plan: AnnualTrainingPlan) -> None:
        plan.is_deleted = True
        await self.session.flush()

class AnnualTrainingPlanItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_items(self, plan_id: UUID) -> list[AnnualTrainingPlanItem]:
        result = await self.session.execute(
            select(AnnualTrainingPlanItem)
            .where(
                AnnualTrainingPlanItem.plan_id == plan_id,
                AnnualTrainingPlanItem.is_deleted.is_(False),
            )
            .order_by(asc(AnnualTrainingPlanItem.sort_order), asc(AnnualTrainingPlanItem.created_at))
        )
        return list(result.scalars().all())

    async def get_by_id(self, item_id: UUID) -> AnnualTrainingPlanItem | None:
        result = await self.session.execute(
            select(AnnualTrainingPlanItem).where(
                AnnualTrainingPlanItem.id == item_id,
                AnnualTrainingPlanItem.is_deleted.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def create(self, item: AnnualTrainingPlanItem) -> AnnualTrainingPlanItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update(self, item: AnnualTrainingPlanItem) -> AnnualTrainingPlanItem:
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def delete(self, item: AnnualTrainingPlanItem) -> None:
        await self.session.delete(item)
        await self.session.flush()

    async def delete_by_plan_id(self, plan_id: UUID) -> None:
        await self.session.execute(
            delete(AnnualTrainingPlanItem).where(AnnualTrainingPlanItem.plan_id == plan_id)
        )
        await self.session.flush()


# ─── Recruitment Repositories ───


class JobRequirementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self, *, status: str | None = None) -> list[JobRequirement]:
        stmt = select(JobRequirement).where(JobRequirement.is_deleted.is_(False))
        if status:
            stmt = stmt.where(JobRequirement.status == status)
        stmt = stmt.order_by(desc(JobRequirement.created_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, req_id: UUID) -> JobRequirement | None:
        result = await self.session.execute(
            select(JobRequirement).where(JobRequirement.id == req_id, JobRequirement.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def create(self, req: JobRequirement) -> JobRequirement:
        self.session.add(req)
        await self.session.flush()
        await self.session.refresh(req)
        return req

    async def update(self, req: JobRequirement) -> JobRequirement:
        await self.session.flush()
        result = await self.session.execute(select(JobRequirement).where(JobRequirement.id == req.id))
        return result.scalar_one()

    async def soft_delete(self, req_id: UUID) -> None:
        await self.session.execute(text("UPDATE hr.job_requirements SET is_deleted = true WHERE id = :id"), {"id": req_id})
        await self.session.flush()

    async def increment_hired_count(self, req_id: UUID) -> None:
        await self.session.execute(text("UPDATE hr.job_requirements SET hired_count = hired_count + 1 WHERE id = :id"), {"id": req_id})
        await self.session.flush()

    async def count_active(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(JobRequirement).where(
                JobRequirement.is_deleted.is_(False), JobRequirement.status == "招聘中"
            )
        )
        return result.scalar() or 0


class CandidateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(
        self, *, job_requirement_id: UUID | None = None, status: str | None = None,
        keyword: str | None = None, candidate_type: str | None = None,
        page: int = 1, page_size: int = 100,
    ) -> tuple[list[Candidate], int]:
        stmt = select(Candidate).where(Candidate.is_deleted.is_(False))
        if job_requirement_id:
            stmt = stmt.where(Candidate.job_requirement_id == job_requirement_id)
        if status:
            stmt = stmt.where(Candidate.status == status)
        if candidate_type:
            stmt = stmt.where(Candidate.candidate_type == candidate_type)
        if keyword:
            stmt = stmt.where(or_(
                Candidate.name.ilike(f"%{keyword}%"),
                Candidate.phone.ilike(f"%{keyword}%"),
            ))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar() or 0
        data_stmt = stmt.order_by(desc(Candidate.created_at)).offset((page - 1) * page_size).limit(page_size)
        return list((await self.session.execute(data_stmt)).scalars().all()), total

    async def get_by_id(self, candidate_id: UUID) -> Candidate | None:
        result = await self.session.execute(
            select(Candidate).where(Candidate.id == candidate_id, Candidate.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def create(self, candidate: Candidate) -> Candidate:
        self.session.add(candidate)
        await self.session.flush()
        await self.session.refresh(candidate)
        return candidate

    async def update(self, candidate: Candidate) -> Candidate:
        await self.session.flush()
        result = await self.session.execute(select(Candidate).where(Candidate.id == candidate.id))
        return result.scalar_one()

    async def soft_delete(self, candidate_id: UUID) -> None:
        await self.session.execute(text("UPDATE hr.candidates SET is_deleted = true WHERE id = :id"), {"id": candidate_id})
        await self.session.flush()

    async def count_by_status(self, status: str) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Candidate).where(Candidate.status == status, Candidate.is_deleted.is_(False))
        )
        return result.scalar() or 0

    async def count_total(self) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Candidate).where(Candidate.is_deleted.is_(False))
        )
        return result.scalar() or 0


class InterviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_candidate(self, candidate_id: UUID) -> list[Interview]:
        result = await self.session.execute(
            select(Interview).where(Interview.candidate_id == candidate_id, Interview.is_deleted.is_(False))
            .order_by(desc(Interview.interview_date))
        )
        return list(result.scalars().all())

    async def get_by_id(self, interview_id: UUID) -> Interview | None:
        result = await self.session.execute(
            select(Interview).where(Interview.id == interview_id, Interview.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def create(self, interview: Interview) -> Interview:
        self.session.add(interview)
        await self.session.flush()
        await self.session.refresh(interview)
        return interview

    async def update(self, interview: Interview) -> Interview:
        await self.session.flush()
        result = await self.session.execute(select(Interview).where(Interview.id == interview.id))
        return result.scalar_one()

    async def soft_delete(self, interview_id: UUID) -> None:
        await self.session.execute(text("UPDATE hr.interviews SET is_deleted = true WHERE id = :id"), {"id": interview_id})
        await self.session.flush()


class CandidateAiEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_interview(self, interview_id: UUID) -> CandidateAiEvaluation | None:
        result = await self.session.execute(
            select(CandidateAiEvaluation).where(
                CandidateAiEvaluation.interview_id == interview_id, CandidateAiEvaluation.is_deleted.is_(False)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_candidate(self, candidate_id: UUID) -> CandidateAiEvaluation | None:
        result = await self.session.execute(
            select(CandidateAiEvaluation).where(
                CandidateAiEvaluation.candidate_id == candidate_id, CandidateAiEvaluation.is_deleted.is_(False)
            ).order_by(desc(CandidateAiEvaluation.created_at))
        )
        return result.scalars().first()

    async def create(self, evaluation: CandidateAiEvaluation) -> CandidateAiEvaluation:
        self.session.add(evaluation)
        await self.session.flush()
        await self.session.refresh(evaluation)
        return evaluation

    async def update(self, evaluation: CandidateAiEvaluation) -> CandidateAiEvaluation:
        await self.session.flush()
        result = await self.session.execute(
            select(CandidateAiEvaluation).where(CandidateAiEvaluation.id == evaluation.id)
        )
        return result.scalar_one()


class CandidateReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_pending(self, *, reviewer: str | None = None) -> list[CandidateReview]:
        stmt = select(CandidateReview).where(CandidateReview.is_deleted.is_(False), CandidateReview.status == "待审核")
        if reviewer:
            stmt = stmt.where(CandidateReview.reviewer == reviewer)
        stmt = stmt.order_by(desc(CandidateReview.created_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_candidate(self, candidate_id: UUID) -> CandidateReview | None:
        result = await self.session.execute(
            select(CandidateReview).where(CandidateReview.candidate_id == candidate_id, CandidateReview.is_deleted.is_(False))
            .order_by(desc(CandidateReview.created_at))
        )
        return result.scalars().first()

    async def get_by_id(self, review_id: UUID) -> CandidateReview | None:
        result = await self.session.execute(
            select(CandidateReview).where(CandidateReview.id == review_id, CandidateReview.is_deleted.is_(False))
        )
        return result.scalar_one_or_none()

    async def create(self, review: CandidateReview) -> CandidateReview:
        self.session.add(review)
        await self.session.flush()
        await self.session.refresh(review)
        return review

    async def update(self, review: CandidateReview) -> CandidateReview:
        await self.session.flush()
        result = await self.session.execute(select(CandidateReview).where(CandidateReview.id == review.id))
        return result.scalar_one()


class CandidateStatusLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, log: CandidateStatusLog) -> CandidateStatusLog:
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def list_by_candidate(self, candidate_id: UUID) -> list[CandidateStatusLog]:
        result = await self.session.execute(
            select(CandidateStatusLog).where(CandidateStatusLog.candidate_id == candidate_id)
            .order_by(desc(CandidateStatusLog.created_at))
        )
        return list(result.scalars().all())
