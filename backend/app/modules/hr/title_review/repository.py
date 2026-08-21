"""职称评审数据读写（class-per-table，v2）。"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.hr.title_review.models import (
    TitleReviewActivity,
    TitleReviewApplication,
    TitleReviewDeptCommittee,
    TitleReviewDimension,
    TitleReviewJudge,
    TitleReviewLevel,
    TitleReviewScore,
)


class TitleReviewActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(
        self,
        *,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[TitleReviewActivity], int]:
        stmt = select(TitleReviewActivity).where(
            TitleReviewActivity.is_deleted == False  # noqa: E712
        )
        if status:
            stmt = stmt.where(TitleReviewActivity.status == status)
        if keyword:
            stmt = stmt.where(TitleReviewActivity.name.ilike(f"%{keyword}%"))
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(
                stmt.order_by(TitleReviewActivity.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def get_by_id(self, activity_id: UUID) -> TitleReviewActivity | None:
        result = await self.session.execute(
            select(TitleReviewActivity).where(
                TitleReviewActivity.id == activity_id,
                TitleReviewActivity.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_feishu_app(self, app_token: str) -> TitleReviewActivity | None:
        result = await self.session.execute(
            select(TitleReviewActivity).where(
                TitleReviewActivity.feishu_app_token == app_token,
                TitleReviewActivity.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[TitleReviewActivity]:
        """进行中的活动（open/reviewing），用于对账与事件映射。"""
        result = await self.session.execute(
            select(TitleReviewActivity).where(
                TitleReviewActivity.is_deleted == False,  # noqa: E712
                TitleReviewActivity.status.in_(["open", "reviewing"]),
            )
        )
        return list(result.scalars().all())

    async def create(self, activity: TitleReviewActivity) -> TitleReviewActivity:
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def update(self, activity: TitleReviewActivity) -> TitleReviewActivity:
        """UPDATE 后 re-fetch，保证 onupdate 字段回填（避免 MissingGreenlet）。"""
        await self.session.flush()
        result = await self.session.execute(
            select(TitleReviewActivity).where(TitleReviewActivity.id == activity.id)
        )
        return result.scalar_one()


class TitleReviewLevelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_activity(self, activity_id: UUID) -> list[TitleReviewLevel]:
        result = await self.session.execute(
            select(TitleReviewLevel)
            .where(
                TitleReviewLevel.activity_id == activity_id,
                TitleReviewLevel.is_deleted == False,  # noqa: E712
            )
            .order_by(TitleReviewLevel.sort_order, TitleReviewLevel.created_at)
        )
        return list(result.scalars().all())

    async def get_by_sequence_level(
        self, activity_id: UUID, sequence: str, level_name: str
    ) -> TitleReviewLevel | None:
        result = await self.session.execute(
            select(TitleReviewLevel).where(
                TitleReviewLevel.activity_id == activity_id,
                TitleReviewLevel.sequence == sequence,
                TitleReviewLevel.level_name == level_name,
                TitleReviewLevel.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def create(self, level: TitleReviewLevel) -> TitleReviewLevel:
        self.session.add(level)
        await self.session.flush()
        return level


class TitleReviewDimensionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_activity(self, activity_id: UUID) -> list[TitleReviewDimension]:
        result = await self.session.execute(
            select(TitleReviewDimension)
            .where(
                TitleReviewDimension.activity_id == activity_id,
                TitleReviewDimension.is_deleted == False,  # noqa: E712
            )
            .order_by(TitleReviewDimension.sort_order, TitleReviewDimension.created_at)
        )
        return list(result.scalars().all())

    async def create(self, dimension: TitleReviewDimension) -> TitleReviewDimension:
        self.session.add(dimension)
        await self.session.flush()
        return dimension


class TitleReviewApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_activity(
        self,
        activity_id: UUID,
        *,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[TitleReviewApplication], int]:
        stmt = select(TitleReviewApplication).where(
            TitleReviewApplication.activity_id == activity_id,
            TitleReviewApplication.is_deleted == False,  # noqa: E712
        )
        if status:
            stmt = stmt.where(TitleReviewApplication.status == status)
        if keyword:
            stmt = stmt.where(
                TitleReviewApplication.name.ilike(f"%{keyword}%")
                | TitleReviewApplication.employee_no.ilike(f"%{keyword}%")
            )
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        rows = (
            await self.session.execute(
                stmt.order_by(TitleReviewApplication.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return list(rows), total

    async def list_all_by_activity(self, activity_id: UUID) -> list[TitleReviewApplication]:
        result = await self.session.execute(
            select(TitleReviewApplication).where(
                TitleReviewApplication.activity_id == activity_id,
                TitleReviewApplication.is_deleted == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, application_id: UUID) -> TitleReviewApplication | None:
        result = await self.session.execute(
            select(TitleReviewApplication).where(
                TitleReviewApplication.id == application_id,
                TitleReviewApplication.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_feishu_record(
        self, activity_id: UUID, record_id: str
    ) -> TitleReviewApplication | None:
        result = await self.session.execute(
            select(TitleReviewApplication).where(
                TitleReviewApplication.activity_id == activity_id,
                TitleReviewApplication.feishu_record_id == record_id,
                TitleReviewApplication.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def count_by_activity(self, activity_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(TitleReviewApplication).where(
                TitleReviewApplication.activity_id == activity_id,
                TitleReviewApplication.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one()

    async def create(self, application: TitleReviewApplication) -> TitleReviewApplication:
        self.session.add(application)
        await self.session.flush()
        return application

    async def update(
        self, application: TitleReviewApplication
    ) -> TitleReviewApplication:
        await self.session.flush()
        result = await self.session.execute(
            select(TitleReviewApplication).where(
                TitleReviewApplication.id == application.id
            )
        )
        return result.scalar_one()


class TitleReviewJudgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_application(self, application_id: UUID) -> list[TitleReviewJudge]:
        result = await self.session.execute(
            select(TitleReviewJudge)
            .where(
                TitleReviewJudge.application_id == application_id,
                TitleReviewJudge.is_deleted == False,  # noqa: E712
            )
            .order_by(TitleReviewJudge.created_at, TitleReviewJudge.judge_code)
        )
        return list(result.scalars().all())

    async def list_by_activity(self, activity_id: UUID) -> list[TitleReviewJudge]:
        result = await self.session.execute(
            select(TitleReviewJudge).where(
                TitleReviewJudge.activity_id == activity_id,
                TitleReviewJudge.is_deleted == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_by_id(self, judge_id: UUID) -> TitleReviewJudge | None:
        result = await self.session.execute(
            select(TitleReviewJudge).where(
                TitleReviewJudge.id == judge_id,
                TitleReviewJudge.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_feishu_record(self, record_id: str) -> TitleReviewJudge | None:
        result = await self.session.execute(
            select(TitleReviewJudge).where(
                TitleReviewJudge.feishu_record_id == record_id,
                TitleReviewJudge.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_application_and_employee(
        self, application_id: UUID, judge_employee_id: UUID
    ) -> TitleReviewJudge | None:
        result = await self.session.execute(
            select(TitleReviewJudge).where(
                TitleReviewJudge.application_id == application_id,
                TitleReviewJudge.judge_employee_id == judge_employee_id,
                TitleReviewJudge.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def create(self, judge: TitleReviewJudge) -> TitleReviewJudge:
        self.session.add(judge)
        await self.session.flush()
        return judge

    async def update(self, judge: TitleReviewJudge) -> TitleReviewJudge:
        await self.session.flush()
        result = await self.session.execute(
            select(TitleReviewJudge).where(TitleReviewJudge.id == judge.id)
        )
        return result.scalar_one()


class TitleReviewScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_judge(self, judge_id: UUID) -> list[TitleReviewScore]:
        result = await self.session.execute(
            select(TitleReviewScore).where(
                TitleReviewScore.judge_id == judge_id,
                TitleReviewScore.is_deleted == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def list_by_application(self, application_id: UUID) -> list[TitleReviewScore]:
        result = await self.session.execute(
            select(TitleReviewScore).where(
                TitleReviewScore.application_id == application_id,
                TitleReviewScore.is_deleted == False,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    async def get_by_judge_and_dimension(
        self, judge_id: UUID, dimension_id: UUID
    ) -> TitleReviewScore | None:
        result = await self.session.execute(
            select(TitleReviewScore).where(
                TitleReviewScore.judge_id == judge_id,
                TitleReviewScore.dimension_id == dimension_id,
                TitleReviewScore.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def create(self, score: TitleReviewScore) -> TitleReviewScore:
        self.session.add(score)
        await self.session.flush()
        return score

    async def update(self, score: TitleReviewScore) -> TitleReviewScore:
        await self.session.flush()
        result = await self.session.execute(
            select(TitleReviewScore).where(TitleReviewScore.id == score.id)
        )
        return result.scalar_one()


class TitleReviewDeptCommitteeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[TitleReviewDeptCommittee]:
        result = await self.session.execute(
            select(TitleReviewDeptCommittee)
            .where(TitleReviewDeptCommittee.is_deleted == False)  # noqa: E712
            .order_by(TitleReviewDeptCommittee.department)
        )
        return list(result.scalars().all())

    async def get_by_department(self, department: str) -> TitleReviewDeptCommittee | None:
        result = await self.session.execute(
            select(TitleReviewDeptCommittee).where(
                TitleReviewDeptCommittee.department == department,
                TitleReviewDeptCommittee.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, committee_id: UUID) -> TitleReviewDeptCommittee | None:
        result = await self.session.execute(
            select(TitleReviewDeptCommittee).where(
                TitleReviewDeptCommittee.id == committee_id,
                TitleReviewDeptCommittee.is_deleted == False,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, committee: TitleReviewDeptCommittee
    ) -> TitleReviewDeptCommittee:
        self.session.add(committee)
        await self.session.flush()
        return committee

    async def update(
        self, committee: TitleReviewDeptCommittee
    ) -> TitleReviewDeptCommittee:
        await self.session.flush()
        result = await self.session.execute(
            select(TitleReviewDeptCommittee).where(
                TitleReviewDeptCommittee.id == committee.id
            )
        )
        return result.scalar_one()
