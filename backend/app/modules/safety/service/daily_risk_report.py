"""Safety business workflows — 危险源风险选项（供危险源辨识 risk-options 端点）."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    HazardIdentification,
)


class DailyRiskReportService:
    """危险源风险选项查询服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── 危险源风险选项（常规作业报备关联危险源）──

    async def get_hazard_risk_options(
        self,
        department: str | None = None,
        keyword: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[HazardIdentification], int]:
        """返回风险等级为 level_1/level_2 且 overall_status=completed 的危险源辨识项"""
        query = select(HazardIdentification).where(
            HazardIdentification.is_deleted.is_(False),
            HazardIdentification.overall_status == "completed",
            HazardIdentification.inherent_risk_level.in_(["level_1", "level_2"]),
        )
        count_query = select(func.count(HazardIdentification.id)).where(
            HazardIdentification.is_deleted.is_(False),
            HazardIdentification.overall_status == "completed",
            HazardIdentification.inherent_risk_level.in_(["level_1", "level_2"]),
        )

        if department:
            query = query.where(HazardIdentification.department == department)
            count_query = count_query.where(HazardIdentification.department == department)
        if keyword:
            like = f"%{keyword}%"
            filters = (
                HazardIdentification.hazard_id_no.ilike(like)
                | HazardIdentification.department.ilike(like)
                | HazardIdentification.position.ilike(like)
            )
            query = query.where(filters)
            count_query = count_query.where(filters)

        total = await self.session.scalar(count_query)
        query = (
            query.order_by(HazardIdentification.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0
