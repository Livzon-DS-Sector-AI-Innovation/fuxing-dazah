"""Safety business workflows — 每日风险作业报备."""

import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    DailyRiskReport,
    HazardIdentification,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    DailyRiskReportCreate,
    DailyRiskReportUpdate,
)

logger = logging.getLogger(__name__)


class DailyRiskReportService:
    """每日风险作业报备业务服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    # ── CRUD ──

    async def get_reports(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        department: str | None = None,
        report_date: datetime | None = None,
        keyword: str | None = None,
    ) -> tuple[list[DailyRiskReport], int]:
        """获取每日风险作业报备列表"""
        return await self.repo.get_daily_risk_reports(
            skip, limit, status, department, report_date, keyword
        )

    async def get_report(self, report_id: uuid.UUID) -> DailyRiskReport | None:
        """获取报备详情"""
        return await self.repo.get_daily_risk_report_by_id(report_id)

    async def create_report(
        self, data: DailyRiskReportCreate
    ) -> DailyRiskReport:
        """创建报备"""
        return await self.repo.create_daily_risk_report(data.model_dump())

    async def update_report(
        self, report_id: uuid.UUID, data: DailyRiskReportUpdate
    ) -> DailyRiskReport | None:
        """更新报备"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        return await self.repo.update_daily_risk_report(report_id, update_data)

    async def delete_report(self, report_id: uuid.UUID) -> bool:
        """删除报备"""
        return await self.repo.delete_daily_risk_report(report_id)

    # ── 工作流 ──

    async def submit_report(
        self, report_id: uuid.UUID
    ) -> DailyRiskReport | None:
        """提交报备（草稿→已提交）"""
        report = await self.repo.get_daily_risk_report_by_id(report_id)
        if not report or report.status != "draft":
            return None
        return await self.repo.update_daily_risk_report(
            report_id, {"status": "submitted"}
        )

    async def approve_report(
        self, report_id: uuid.UUID
    ) -> DailyRiskReport | None:
        """审批报备（已提交→已审批）"""
        report = await self.repo.get_daily_risk_report_by_id(report_id)
        if not report or report.status != "submitted":
            return None
        return await self.repo.update_daily_risk_report(
            report_id,
            {"status": "approved", "approved_at": datetime.now()},
        )

    async def reject_report(
        self, report_id: uuid.UUID, reason: str
    ) -> DailyRiskReport | None:
        """驳回报备（已提交→已驳回）"""
        report = await self.repo.get_daily_risk_report_by_id(report_id)
        if not report or report.status != "submitted":
            return None
        return await self.repo.update_daily_risk_report(
            report_id,
            {"status": "rejected", "rejection_reason": reason},
        )

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
