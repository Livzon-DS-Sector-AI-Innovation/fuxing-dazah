"""Safety business workflows."""

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    DailyRiskReport,
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


# ==================== EHS变更管理 (MOC) Service ====================


