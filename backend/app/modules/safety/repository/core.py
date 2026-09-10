"""Safety database queries."""

import uuid
from datetime import date, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, Integer, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.safety.models import (
    ChemicalInventoryRecord,
    Contractor,
    ContractorAdmission,
    ContractorWorkRecord,
    EhsChange,
    HazardIdentification,
    HazardReport,
    KeyRiskOperationReport,
    OhFollowup,
    OhHazardFactor,
    OhHealthExam,
    OhPerson,
    OhPosition,
    OperationRegulation,
    RegulationRevision,
    SafetyKnowledgeArticle,
    SafetyTraining,
    SpecialOperationPermit,
    SpecialOperationPersonnel,
    SpecialOperationReport,
    TrainingRecord,
)


class SafetyRepository:
    """Safety module repository"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ==================== HazardReport Operations ====================

    async def get_hazards(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        rectification_status: str | None = None,
        hazard_type: str | None = None,
        hazard_level: str | None = None,
        hazard_category: str | None = None,
        inspection_category: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[HazardReport], int]:
        """获取隐患列表"""
        query = select(HazardReport).where(HazardReport.is_deleted.is_(False))

        if status:
            query = query.where(HazardReport.status == status)
        if rectification_status:
            query = query.where(HazardReport.rectification_status == rectification_status)
        if hazard_type:
            query = query.where(HazardReport.hazard_type == hazard_type)
        if hazard_level:
            query = query.where(HazardReport.hazard_level == hazard_level)
        if hazard_category:
            query = query.where(HazardReport.hazard_category == hazard_category)
        if inspection_category:
            query = query.where(HazardReport.inspection_category.contains(inspection_category))
        if department:
            query = query.where(HazardReport.department == department)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                HazardReport.description.ilike(like)
                | HazardReport.hazard_no.ilike(like)
            )
        if date_from:
            query = query.where(HazardReport.discovered_at >= date_from)
        if date_to:
            query = query.where(HazardReport.discovered_at <= date_to)

        count_query = select(func.count(HazardReport.id)).where(HazardReport.is_deleted.is_(False))
        if status:
            count_query = count_query.where(HazardReport.status == status)
        if rectification_status:
            count_query = count_query.where(HazardReport.rectification_status == rectification_status)
        if hazard_type:
            count_query = count_query.where(HazardReport.hazard_type == hazard_type)
        if hazard_level:
            count_query = count_query.where(HazardReport.hazard_level == hazard_level)
        if hazard_category:
            count_query = count_query.where(HazardReport.hazard_category == hazard_category)
        if inspection_category:
            count_query = count_query.where(HazardReport.inspection_category.contains(inspection_category))
        if department:
            count_query = count_query.where(HazardReport.department == department)
        if keyword:
            like = f"%{keyword}%"
            count_query = count_query.where(
                HazardReport.description.ilike(like)
                | HazardReport.hazard_no.ilike(like)
            )
        if date_from:
            count_query = count_query.where(HazardReport.discovered_at >= date_from)
        if date_to:
            count_query = count_query.where(HazardReport.discovered_at <= date_to)

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(HazardReport.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_hazard_stats(self) -> dict[str, int]:
        """获取隐患状态统计数据（全局，不受分页/筛选影响）。"""
        from sqlalchemy import case

        base = select(
            func.count(HazardReport.id).label("total"),
            func.count(case((HazardReport.ai_generated.is_(True)
                             & (HazardReport.overall_status == "completed"), 1))).label("pending_review"),
            func.count(case((HazardReport.rectification_status == "pending", 1))).label("pending"),
            func.count(case((HazardReport.rectification_status == "in_progress", 1))).label("in_progress"),
            func.count(case((HazardReport.rectification_status == "replied", 1))).label("replied"),
            func.count(case((HazardReport.rectification_status.in_(["level1_approved", "level2_approved"]), 1))).label("verifying"),
            func.count(case((HazardReport.rectification_status == "rejected", 1))).label("rejected"),
            func.count(case((HazardReport.rectification_status == "closed", 1))).label("closed"),
            func.count(case(
                (HazardReport.deadline.is_not(None)
                 & (HazardReport.deadline < func.now())
                 & (HazardReport.rectification_status != "closed")
                 & (HazardReport.status != "closed"), 1)
            )).label("overdue"),
        ).where(HazardReport.is_deleted.is_(False))

        result = await self.session.execute(base)
        row = result.one()
        return {
            "total": row.total or 0,
            "pending_review": row.pending_review or 0,
            "pending": row.pending or 0,
            "in_progress": row.in_progress or 0,
            "replied": row.replied or 0,
            "verifying": row.verifying or 0,
            "rejected": row.rejected or 0,
            "closed": row.closed or 0,
            "overdue": row.overdue or 0,
        }

    async def get_hazard_stats_filtered(
        self,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        department: str | None = None,
    ) -> dict[str, int]:
        """获取隐患状态统计数据（支持日期范围和部门筛选）。"""
        from sqlalchemy import case

        base = select(
            func.count(HazardReport.id).label("total"),
            func.count(case((HazardReport.ai_generated.is_(True)
                             & (HazardReport.overall_status == "completed"), 1))).label("pending_review"),
            func.count(case((HazardReport.rectification_status == "pending", 1))).label("pending"),
            func.count(case((HazardReport.rectification_status == "in_progress", 1))).label("in_progress"),
            func.count(case((HazardReport.rectification_status == "replied", 1))).label("replied"),
            func.count(case((HazardReport.rectification_status.in_(["level1_approved", "level2_approved"]), 1))).label("verifying"),
            func.count(case((HazardReport.rectification_status == "rejected", 1))).label("rejected"),
            func.count(case((HazardReport.rectification_status.in_(["closed", "level3_approved"]), 1))).label("closed"),
            func.count(case(
                (HazardReport.deadline.is_not(None)
                 & (HazardReport.deadline < func.now())
                 & (HazardReport.rectification_status != "closed")
                 & (HazardReport.status != "closed"), 1)
            )).label("overdue"),
            func.count(case((HazardReport.description == "待AI填写", 1))).label("empty_description"),
        ).where(HazardReport.is_deleted.is_(False))

        if date_from:
            base = base.where(HazardReport.discovered_at >= date_from)
        if date_to:
            base = base.where(HazardReport.discovered_at <= date_to)
        if department:
            base = base.where(HazardReport.department == department)

        result = await self.session.execute(base)
        row = result.one()
        return {
            "total": row.total or 0,
            "pending_review": row.pending_review or 0,
            "pending": row.pending or 0,
            "in_progress": row.in_progress or 0,
            "replied": row.replied or 0,
            "verifying": row.verifying or 0,
            "rejected": row.rejected or 0,
            "closed": row.closed or 0,
            "overdue": row.overdue or 0,
            "empty_description": row.empty_description or 0,
        }

    async def get_hazard_by_id(self, hazard_id: uuid.UUID) -> HazardReport | None:
        """获取隐患详情"""
        query = select(HazardReport).where(
            HazardReport.id == hazard_id, HazardReport.is_deleted.is_(False)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_hazard(self, data: dict[str, Any]) -> HazardReport:
        """创建隐患"""
        item = HazardReport(**data)
        self.session.add(item)
        await self.session.flush()
        # 用 select 替代 refresh（避免 async MissingGreenlet）
        stmt = select(HazardReport).where(HazardReport.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    # 禁止以空字符串覆盖的 person 姓名字段（防御 Bitable 空 person → "" 覆盖已有数据）
    _PERSON_NAME_GUARD_FIELDS = frozenset({
        "discovered_by_name", "rectification_responsible_person_name",
    })

    async def update_hazard(self, hazard_id: uuid.UUID, data: dict[str, Any]) -> HazardReport | None:
        """更新隐患（写后 eager re-fetch，避免 session 缓存旧值）。

        RETURNING 返回的对象不会刷新 identity map 中已缓存的旧实例，
        导致同 session 内后续 get_hazard_by_id() 返回过期数据。
        改为 UPDATE + SELECT populate_existing 两步，强制覆盖缓存。
        """
        # ── 防御层：禁止空字符串覆盖 person 姓名字段 ──
        for guard_field in self._PERSON_NAME_GUARD_FIELDS:
            if data.get(guard_field) == "":
                import logging
                _logger = logging.getLogger(__name__)
                _logger.warning(
                    "repo.update_hazard 拦截空字符串: hazard_id=%s field=%s (已从 update_data 移除)",
                    hazard_id, guard_field,
                )
                del data[guard_field]

        stmt_update = (
            update(HazardReport)
            .where(HazardReport.id == hazard_id, HazardReport.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)

        stmt_select = (
            select(HazardReport)
            .where(HazardReport.id == hazard_id, HazardReport.is_deleted.is_(False))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_hazard(self, hazard_id: uuid.UUID) -> bool:
        """删除隐患（软删除）"""
        query = (
            update(HazardReport)
            .where(HazardReport.id == hazard_id, HazardReport.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    async def count_hazards_today(self, date_prefix: str) -> int:
        """统计指定日期前缀的隐患编号数量（含软删除），用于自动生成序号。"""
        query = select(func.count(HazardReport.id)).where(
            HazardReport.hazard_no.like(f"HZ-{date_prefix}-%"),
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def get_open_hazards_for_supervision(self) -> list[HazardReport]:
        """获取所有未关闭的隐患，用于督办等级全量计算。

        Returns:
            status=open 且 is_deleted=false 的隐患列表，
            按 department + discovered_at 排序
        """
        stmt = (
            select(HazardReport)
            .where(
                HazardReport.is_deleted.is_(False),
                HazardReport.status == "open",
            )
            .order_by(HazardReport.department, HazardReport.discovered_at)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ==================== SafetyTraining Operations ====================

    async def get_trainings(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        training_type: str | None = None,
        department: str | None = None,
    ) -> tuple[list[SafetyTraining], int]:
        """获取安全培训列表"""
        query = select(SafetyTraining).where(SafetyTraining.is_deleted.is_(False))

        if status:
            query = query.where(SafetyTraining.status == status)
        if training_type:
            query = query.where(SafetyTraining.training_type == training_type)
        if department:
            query = query.where(SafetyTraining.department == department)

        count_query = select(func.count(SafetyTraining.id)).where(
            SafetyTraining.is_deleted.is_(False)
        )
        if status:
            count_query = count_query.where(SafetyTraining.status == status)
        if training_type:
            count_query = count_query.where(SafetyTraining.training_type == training_type)
        if department:
            count_query = count_query.where(SafetyTraining.department == department)

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(SafetyTraining.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_training_by_id(self, training_id: uuid.UUID) -> SafetyTraining | None:
        """获取安全培训详情"""
        query = (
            select(SafetyTraining)
            .options(selectinload(SafetyTraining.records))
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted.is_(False))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_training(self, data: dict[str, Any]) -> SafetyTraining:
        """创建安全培训"""
        item = SafetyTraining(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(SafetyTraining).where(SafetyTraining.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_training(
        self, training_id: uuid.UUID, data: dict[str, Any]
    ) -> SafetyTraining | None:
        """更新安全培训"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(SafetyTraining)
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(SafetyTraining)
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted.is_(False))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_training(self, training_id: uuid.UUID) -> bool:
        """删除安全培训（软删除）"""
        query = (
            update(SafetyTraining)
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== TrainingRecord Operations ====================

    async def get_records_by_training(self, training_id: uuid.UUID) -> list[TrainingRecord]:
        """获取培训记录列表"""
        query = select(TrainingRecord).where(
            TrainingRecord.training_id == training_id, TrainingRecord.is_deleted.is_(False)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create_training_record(self, data: dict[str, Any]) -> TrainingRecord:
        """创建培训记录"""
        item = TrainingRecord(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(TrainingRecord).where(TrainingRecord.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_training_record(
        self, record_id: uuid.UUID, data: dict[str, Any]
    ) -> TrainingRecord | None:
        """更新培训记录"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(TrainingRecord)
            .where(TrainingRecord.id == record_id, TrainingRecord.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(TrainingRecord)
            .where(TrainingRecord.id == record_id, TrainingRecord.is_deleted.is_(False))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_training_record(self, record_id: uuid.UUID) -> bool:
        """删除培训记录（软删除）"""
        query = (
            update(TrainingRecord)
            .where(TrainingRecord.id == record_id, TrainingRecord.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ── 培训证书 ──

    async def get_training_certificates(
        self,
        skip: int = 0,
        limit: int = 20,
        certificate_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[TrainingRecord], int]:
        """获取培训证书列表（仅包含有证书的记录）"""
        query = select(TrainingRecord).where(
            TrainingRecord.is_deleted.is_(False),
            TrainingRecord.certificate_no.isnot(None),
        )
        count_query = select(func.count(TrainingRecord.id)).where(
            TrainingRecord.is_deleted.is_(False),
            TrainingRecord.certificate_no.isnot(None),
        )

        if certificate_status:
            query = query.where(TrainingRecord.certificate_status == certificate_status)
            count_query = count_query.where(TrainingRecord.certificate_status == certificate_status)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                TrainingRecord.employee_name.ilike(like)
                | TrainingRecord.department.ilike(like)
                | TrainingRecord.certificate_no.ilike(like)
            )
            count_query = count_query.where(
                TrainingRecord.employee_name.ilike(like)
                | TrainingRecord.department.ilike(like)
                | TrainingRecord.certificate_no.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(TrainingRecord.certificate_expiry.asc().nulls_last())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_expiring_certificates(self) -> list[TrainingRecord]:
        """获取30天内即将过期的证书"""
        from datetime import timedelta
        now = datetime.now()
        thirty_days_later = now + timedelta(days=30)
        query = select(TrainingRecord).where(
            TrainingRecord.is_deleted.is_(False),
            TrainingRecord.certificate_no.isnot(None),
            TrainingRecord.certificate_expiry.isnot(None),
            TrainingRecord.certificate_expiry >= now,
            TrainingRecord.certificate_expiry <= thirty_days_later,
        ).order_by(TrainingRecord.certificate_expiry.asc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ==================== HazardIdentification Operations ====================

    async def get_hazard_identifications(
        self,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        overall_status: str | None = None,
        ai_node_progress: str | None = None,
        keyword: str | None = None,
        position: str | None = None,
        risk_level: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        batch_id: str | None = None,
        review_status: str | None = None,
        ids: list[uuid.UUID] | None = None,
    ) -> tuple[list["HazardIdentification"], int]:
        """获取危险源辨识列表"""
        from datetime import datetime as dt_module

        from sqlalchemy import or_

        query = select(HazardIdentification).where(HazardIdentification.is_deleted.is_(False))
        count_query = select(func.count(HazardIdentification.id)).where(
            HazardIdentification.is_deleted.is_(False)
        )

        if ids:
            query = query.where(HazardIdentification.id.in_(ids))
            count_query = count_query.where(HazardIdentification.id.in_(ids))

        if batch_id:
            try:
                bid = uuid.UUID(batch_id)
            except ValueError:
                bid = None
            if bid:
                query = query.where(HazardIdentification.batch_id == bid)
                count_query = count_query.where(HazardIdentification.batch_id == bid)
        if department:
            query = query.where(HazardIdentification.department == department)
            count_query = count_query.where(HazardIdentification.department == department)
        if position:
            query = query.where(HazardIdentification.position == position)
            count_query = count_query.where(HazardIdentification.position == position)
        if risk_level:
            query = query.where(HazardIdentification.inherent_risk_level == risk_level)
            count_query = count_query.where(HazardIdentification.inherent_risk_level == risk_level)
        if date_from:
            try:
                dfrom = dt_module.strptime(date_from, "%Y-%m-%d")
                query = query.where(HazardIdentification.created_at >= dfrom)
                count_query = count_query.where(HazardIdentification.created_at >= dfrom)
            except ValueError:
                pass
        if date_to:
            try:
                dto = dt_module.strptime(date_to + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                query = query.where(HazardIdentification.created_at <= dto)
                count_query = count_query.where(HazardIdentification.created_at <= dto)
            except ValueError:
                pass
        if overall_status:
            query = query.where(HazardIdentification.overall_status == overall_status)
            count_query = count_query.where(HazardIdentification.overall_status == overall_status)
        if ai_node_progress:
            query = query.where(HazardIdentification.ai_node_progress == ai_node_progress)
            count_query = count_query.where(
                HazardIdentification.ai_node_progress == ai_node_progress
            )
        if review_status:
            review_filter = or_(
                HazardIdentification.script1_review_status == review_status,
                HazardIdentification.script2_review_status == review_status,
                HazardIdentification.script3_review_status == review_status,
                HazardIdentification.script4_review_status == review_status,
                HazardIdentification.script5_review_status == review_status,
                HazardIdentification.script6_review_status == review_status,
                HazardIdentification.script7_review_status == review_status,
            )
            query = query.where(review_filter)
            count_query = count_query.where(review_filter)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                HazardIdentification.hazard_id_no.ilike(like)
                | HazardIdentification.department.ilike(like)
                | HazardIdentification.position.ilike(like)
                | HazardIdentification.production_step.ilike(like)
            )
            count_query = count_query.where(
                HazardIdentification.hazard_id_no.ilike(like)
                | HazardIdentification.department.ilike(like)
                | HazardIdentification.position.ilike(like)
                | HazardIdentification.production_step.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(HazardIdentification.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_hazard_identification_stats(self) -> dict[str, int]:
        """获取危险源辨识工作流统计（按 overall_status 分组）"""


        base = select(HazardIdentification).where(HazardIdentification.is_deleted.is_(False))
        results = {"total_draft": 0, "total_in_progress": 0, "total_pending_review": 0, "total_completed": 0}

        # 按状态统计
        for status, key in [("draft", "total_draft"), ("in_progress", "total_in_progress"), ("completed", "total_completed")]:
            q = base.where(HazardIdentification.overall_status == status)
            results[key] = await self.session.scalar(select(func.count()).select_from(q.subquery())) or 0

        # 待审核：in_progress 且有未审批的脚本
        from sqlalchemy import or_
        pending_q = (
            select(func.count(HazardIdentification.id))
            .where(
                HazardIdentification.is_deleted.is_(False),
                HazardIdentification.overall_status == "in_progress",
                or_(
                    HazardIdentification.script1_review_status == "pending",
                    HazardIdentification.script2_review_status == "pending",
                    HazardIdentification.script3_review_status == "pending",
                    HazardIdentification.script4_review_status == "pending",
                    HazardIdentification.script5_review_status == "pending",
                    HazardIdentification.script6_review_status == "pending",
                    HazardIdentification.script7_review_status == "pending",
                ),
            )
        )
        results["total_pending_review"] = await self.session.scalar(pending_q) or 0
        return results

    async def get_hazard_identification_ledger_stats(
        self,
        department: str | None = None,
        position: str | None = None,
        risk_level: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, int]:
        """获取危险源辨识台账统计（按风险等级分组）"""
        from datetime import datetime as dt_module


        base = select(func.count(HazardIdentification.id)).where(
            HazardIdentification.is_deleted.is_(False),
            HazardIdentification.overall_status == "completed",
        )
        if department:
            base = base.where(HazardIdentification.department == department)
        if position:
            base = base.where(HazardIdentification.position == position)
        if risk_level:
            base = base.where(HazardIdentification.inherent_risk_level == risk_level)
        if date_from:
            try:
                base = base.where(HazardIdentification.created_at >= dt_module.strptime(date_from, "%Y-%m-%d"))
            except ValueError:
                pass
        if date_to:
            try:
                base = base.where(HazardIdentification.created_at <= dt_module.strptime(date_to + " 23:59:59", "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pass

        total = await self.session.scalar(base) or 0

        risk_base = select(func.count(HazardIdentification.id)).where(
            HazardIdentification.is_deleted.is_(False),
            HazardIdentification.overall_status == "completed",
        )
        if department:
            risk_base = risk_base.where(HazardIdentification.department == department)
        if position:
            risk_base = risk_base.where(HazardIdentification.position == position)
        if risk_level:
            risk_base = risk_base.where(HazardIdentification.inherent_risk_level == risk_level)
        if date_from:
            try:
                risk_base = risk_base.where(HazardIdentification.created_at >= dt_module.strptime(date_from, "%Y-%m-%d"))
            except ValueError:
                pass
        if date_to:
            try:
                risk_base = risk_base.where(HazardIdentification.created_at <= dt_module.strptime(date_to + " 23:59:59", "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                pass

        levels = {"level_1": 0, "level_2": 0, "level_3": 0, "level_4": 0}
        for level_key in levels:
            q = risk_base.where(HazardIdentification.inherent_risk_level == level_key)
            levels[level_key] = await self.session.scalar(q) or 0

        return {"total": total, **levels}

    async def get_hazard_identification_by_id(
        self, hid: uuid.UUID
    ) -> "HazardIdentification | None":
        """获取危险源辨识详情"""


        query = select(HazardIdentification).where(
            HazardIdentification.id == hid, HazardIdentification.is_deleted.is_(False)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def count_hi_today(self, date_prefix: str) -> int:
        """统计指定日期前缀的危险源编号数量（含软删除），用于自动生成序号。"""
        query = select(func.count(HazardIdentification.id)).where(
            HazardIdentification.hazard_id_no.like(f"HI-{date_prefix}-%"),
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def create_hazard_identification(
        self, data: dict[str, Any]
    ) -> "HazardIdentification":
        """创建危险源辨识记录"""


        item = HazardIdentification(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(HazardIdentification).where(HazardIdentification.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_hazard_identification(
        self, hid: uuid.UUID, data: dict[str, Any]
    ) -> "HazardIdentification | None":
        """更新危险源辨识记录"""

        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(HazardIdentification)
            .where(HazardIdentification.id == hid, HazardIdentification.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(HazardIdentification)
            .where(HazardIdentification.id == hid, HazardIdentification.is_deleted.is_(False))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_hazard_identification(self, hid: uuid.UUID) -> bool:
        """删除危险源辨识记录（软删除）"""


        query = (
            update(HazardIdentification)
            .where(HazardIdentification.id == hid, HazardIdentification.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    async def create_hazard_identifications_batch(
        self, records_data: list[dict[str, Any]]
    ) -> list["HazardIdentification"]:
        """批量创建危险源辨识记录（共享 batch_id，单次 INSERT）。"""
        items = [HazardIdentification(**data) for data in records_data]
        self.session.add_all(items)
        await self.session.flush()

        # 批量 re-fetch 以获取 server-generated 默认值
        ids = [item.id for item in items]
        stmt = (
            select(HazardIdentification)
            .where(HazardIdentification.id.in_(ids))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_hazard_identifications_by_batch_id(
        self, batch_id: uuid.UUID, skip: int = 0, limit: int = 100
    ) -> tuple[list["HazardIdentification"], int]:
        """按 batch_id 查询辨识记录。"""
        base = (
            select(HazardIdentification)
            .where(
                HazardIdentification.batch_id == batch_id,
                HazardIdentification.is_deleted.is_(False),
            )
        )
        count_query = select(func.count()).select_from(base.subquery())
        total_result = await self.session.execute(count_query)
        total = total_result.scalar() or 0

        query = base.order_by(HazardIdentification.created_at.asc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all()), total

    # ==================== OperationRegulation Operations ====================

    async def get_regulations(
        self,
        skip: int = 0,
        limit: int = 20,
        position: str | None = None,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[OperationRegulation], int]:
        """获取安全操作规程列表"""
        query = select(OperationRegulation).where(OperationRegulation.is_deleted.is_(False))
        count_query = select(func.count(OperationRegulation.id)).where(
            OperationRegulation.is_deleted.is_(False)
        )

        if position:
            query = query.where(OperationRegulation.position.ilike(f"%{position}%"))
            count_query = count_query.where(OperationRegulation.position.ilike(f"%{position}%"))
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                OperationRegulation.regulation_name.ilike(like)
                | OperationRegulation.regulation_no.ilike(like)
            )
            count_query = count_query.where(
                OperationRegulation.regulation_name.ilike(like)
                | OperationRegulation.regulation_no.ilike(like)
            )
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            if statuses:
                query = query.where(OperationRegulation.status.in_(statuses))
                count_query = count_query.where(OperationRegulation.status.in_(statuses))

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(OperationRegulation.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_regulation_by_id(self, regulation_id: uuid.UUID) -> OperationRegulation | None:
        """获取安全操作规程详情"""
        query = (
            select(OperationRegulation)
            .options(selectinload(OperationRegulation.revisions))
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted.is_(False))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_regulation(self, data: dict[str, Any]) -> OperationRegulation:
        """创建安全操作规程"""
        item = OperationRegulation(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OperationRegulation).where(OperationRegulation.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_regulation(
        self, regulation_id: uuid.UUID, data: dict[str, Any]
    ) -> OperationRegulation | None:
        """更新安全操作规程"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(OperationRegulation)
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(OperationRegulation)
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted.is_(False))
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_regulation(self, regulation_id: uuid.UUID) -> bool:
        """删除安全操作规程（软删除）"""
        query = (
            update(OperationRegulation)
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== RegulationRevision Operations ====================

    async def get_revisions(
        self,
        skip: int = 0,
        limit: int = 20,
        regulation_id: uuid.UUID | None = None,
        revision_type: str | None = None,
        review_opinion: str | None = None,
        revision_scope: str | None = None,
    ) -> tuple[list[RegulationRevision], int]:
        """获取修订记录列表"""
        query = select(RegulationRevision).where(RegulationRevision.is_deleted.is_(False))
        count_query = select(func.count(RegulationRevision.id)).where(
            RegulationRevision.is_deleted.is_(False)
        )

        if regulation_id:
            query = query.where(RegulationRevision.regulation_id == regulation_id)
            count_query = count_query.where(
                RegulationRevision.regulation_id == regulation_id
            )
        if revision_type:
            query = query.where(RegulationRevision.revision_type == revision_type)
            count_query = count_query.where(
                RegulationRevision.revision_type == revision_type
            )
        if review_opinion:
            query = query.where(RegulationRevision.review_opinion == review_opinion)
            count_query = count_query.where(
                RegulationRevision.review_opinion == review_opinion
            )
        if revision_scope:
            query = query.where(RegulationRevision.revision_scope.ilike(f"%{revision_scope}%"))
            count_query = count_query.where(
                RegulationRevision.revision_scope.ilike(f"%{revision_scope}%")
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(RegulationRevision.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_revision_by_id(self, revision_id: uuid.UUID) -> RegulationRevision | None:
        """获取修订记录详情"""
        query = (
            select(RegulationRevision)
            .where(RegulationRevision.id == revision_id, RegulationRevision.is_deleted.is_(False))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_revision(self, data: dict[str, Any]) -> RegulationRevision:
        """创建修订记录"""
        item = RegulationRevision(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(RegulationRevision).where(RegulationRevision.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_revision(
        self, revision_id: uuid.UUID, data: dict[str, Any]
    ) -> RegulationRevision | None:
        """更新修订记录"""
        query = (
            update(RegulationRevision)
            .where(RegulationRevision.id == revision_id, RegulationRevision.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
            .returning(RegulationRevision)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_revision(self, revision_id: uuid.UUID) -> bool:
        """删除修订记录（软删除）"""
        query = (
            update(RegulationRevision)
            .where(RegulationRevision.id == revision_id, RegulationRevision.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== 特殊作业人员资质 Operations ====================

    async def get_special_operation_personnel(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        certificate_type: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SpecialOperationPersonnel], int]:
        """获取特殊作业人员资质列表"""
        query = select(SpecialOperationPersonnel).where(
            SpecialOperationPersonnel.is_deleted.is_(False)
        )

        if status:
            query = query.where(SpecialOperationPersonnel.status == status)
        if certificate_type:
            query = query.where(SpecialOperationPersonnel.certificate_type == certificate_type)
        if department:
            query = query.where(SpecialOperationPersonnel.department == department)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                SpecialOperationPersonnel.name.ilike(like)
                | SpecialOperationPersonnel.personnel_no.ilike(like)
                | SpecialOperationPersonnel.certificate_number.ilike(like)
            )

        count_query = select(func.count(SpecialOperationPersonnel.id)).where(
            SpecialOperationPersonnel.is_deleted.is_(False)
        )
        if status:
            count_query = count_query.where(SpecialOperationPersonnel.status == status)
        if certificate_type:
            count_query = count_query.where(
                SpecialOperationPersonnel.certificate_type == certificate_type
            )
        if department:
            count_query = count_query.where(
                SpecialOperationPersonnel.department == department
            )
        if keyword:
            like = f"%{keyword}%"
            count_query = count_query.where(
                SpecialOperationPersonnel.name.ilike(like)
                | SpecialOperationPersonnel.personnel_no.ilike(like)
                | SpecialOperationPersonnel.certificate_number.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(
            SpecialOperationPersonnel.created_at.desc()
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_special_operation_personnel_by_id(
        self, personnel_id: uuid.UUID
    ) -> SpecialOperationPersonnel | None:
        """获取特殊作业人员资质详情"""
        query = select(SpecialOperationPersonnel).where(
            SpecialOperationPersonnel.id == personnel_id,
            SpecialOperationPersonnel.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_special_operation_personnel(
        self, data: dict[str, Any]
    ) -> SpecialOperationPersonnel:
        """创建特殊作业人员资质"""
        item = SpecialOperationPersonnel(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(SpecialOperationPersonnel).where(SpecialOperationPersonnel.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_special_operation_personnel(
        self, personnel_id: uuid.UUID, data: dict[str, Any]
    ) -> SpecialOperationPersonnel | None:
        """更新特殊作业人员资质"""
        query = (
            update(SpecialOperationPersonnel)
            .where(
                SpecialOperationPersonnel.id == personnel_id,
                SpecialOperationPersonnel.is_deleted.is_(False),
            )
            .values(**data, updated_at=func.now())
            .returning(SpecialOperationPersonnel)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_special_operation_personnel(
        self, personnel_id: uuid.UUID
    ) -> bool:
        """删除特殊作业人员资质（软删除）"""
        query = (
            update(SpecialOperationPersonnel)
            .where(
                SpecialOperationPersonnel.id == personnel_id,
                SpecialOperationPersonnel.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== 特殊作业票 Operations ====================

    async def get_special_operation_permits(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        operation_type: str | None = None,
        operation_level: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SpecialOperationPermit], int]:
        """获取特殊作业票列表"""
        query = select(SpecialOperationPermit).where(
            SpecialOperationPermit.is_deleted.is_(False)
        )

        if status:
            query = query.where(SpecialOperationPermit.status == status)
        if operation_type:
            query = query.where(SpecialOperationPermit.operation_type == operation_type)
        if operation_level:
            query = query.where(SpecialOperationPermit.operation_level == operation_level)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                SpecialOperationPermit.permit_no.ilike(like)
                | SpecialOperationPermit.location.ilike(like)
                | SpecialOperationPermit.work_description.ilike(like)
            )

        count_query = select(func.count(SpecialOperationPermit.id)).where(
            SpecialOperationPermit.is_deleted.is_(False)
        )
        if status:
            count_query = count_query.where(SpecialOperationPermit.status == status)
        if operation_type:
            count_query = count_query.where(
                SpecialOperationPermit.operation_type == operation_type
            )
        if operation_level:
            count_query = count_query.where(
                SpecialOperationPermit.operation_level == operation_level
            )
        if keyword:
            like = f"%{keyword}%"
            count_query = count_query.where(
                SpecialOperationPermit.permit_no.ilike(like)
                | SpecialOperationPermit.location.ilike(like)
                | SpecialOperationPermit.work_description.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(
            SpecialOperationPermit.created_at.desc()
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_special_operation_permit_by_id(
        self, permit_id: uuid.UUID
    ) -> SpecialOperationPermit | None:
        """获取特殊作业票详情"""
        query = select(SpecialOperationPermit).where(
            SpecialOperationPermit.id == permit_id,
            SpecialOperationPermit.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_special_operation_permit(
        self, data: dict[str, Any]
    ) -> SpecialOperationPermit:
        """创建特殊作业票"""
        item = SpecialOperationPermit(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(SpecialOperationPermit).where(SpecialOperationPermit.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_special_operation_permit(
        self, permit_id: uuid.UUID, data: dict[str, Any]
    ) -> SpecialOperationPermit | None:
        """更新特殊作业票"""
        query = (
            update(SpecialOperationPermit)
            .where(
                SpecialOperationPermit.id == permit_id,
                SpecialOperationPermit.is_deleted.is_(False),
            )
            .values(**data, updated_at=func.now())
            .returning(SpecialOperationPermit)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_special_operation_permit(
        self, permit_id: uuid.UUID
    ) -> bool:
        """删除特殊作业票（软删除）"""
        query = (
            update(SpecialOperationPermit)
            .where(
                SpecialOperationPermit.id == permit_id,
                SpecialOperationPermit.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== SafetyKnowledgeArticle Operations ====================

    async def get_knowledge_articles(
        self,
        skip: int = 0,
        limit: int = 20,
        category: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SafetyKnowledgeArticle], int]:
        """获取安全知识库文章列表"""
        query = select(SafetyKnowledgeArticle).where(SafetyKnowledgeArticle.is_deleted.is_(False))

        if category:
            query = query.where(SafetyKnowledgeArticle.category == category)
        if status:
            query = query.where(SafetyKnowledgeArticle.status == status)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                SafetyKnowledgeArticle.title.ilike(like)
                | SafetyKnowledgeArticle.summary.ilike(like)
                | SafetyKnowledgeArticle.content.ilike(like)
                | SafetyKnowledgeArticle.tags.ilike(like)
                | SafetyKnowledgeArticle.article_no.ilike(like)
                | SafetyKnowledgeArticle.source.ilike(like)
                | SafetyKnowledgeArticle.author.ilike(like)
            )

        count_query = select(func.count(SafetyKnowledgeArticle.id)).where(
            SafetyKnowledgeArticle.is_deleted.is_(False)
        )
        if category:
            count_query = count_query.where(SafetyKnowledgeArticle.category == category)
        if status:
            count_query = count_query.where(SafetyKnowledgeArticle.status == status)
        if keyword:
            like = f"%{keyword}%"
            count_query = count_query.where(
                SafetyKnowledgeArticle.title.ilike(like)
                | SafetyKnowledgeArticle.summary.ilike(like)
                | SafetyKnowledgeArticle.content.ilike(like)
                | SafetyKnowledgeArticle.tags.ilike(like)
                | SafetyKnowledgeArticle.article_no.ilike(like)
                | SafetyKnowledgeArticle.source.ilike(like)
                | SafetyKnowledgeArticle.author.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(SafetyKnowledgeArticle.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_knowledge_article_by_id(
        self, article_id: uuid.UUID
    ) -> SafetyKnowledgeArticle | None:
        """获取安全知识库文章详情"""
        query = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.id == article_id,
            SafetyKnowledgeArticle.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_knowledge_article_by_feishu_id(
        self, feishu_record_id: str
    ) -> SafetyKnowledgeArticle | None:
        """按飞书记录ID查询知识库文章（含已删除，用于同步匹配）"""
        query = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.feishu_record_id == feishu_record_id,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_knowledge_article(
        self, data: dict[str, Any]
    ) -> SafetyKnowledgeArticle:
        """创建安全知识库文章"""
        item = SafetyKnowledgeArticle(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(SafetyKnowledgeArticle).where(SafetyKnowledgeArticle.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_knowledge_article(
        self, article_id: uuid.UUID, data: dict[str, Any]
    ) -> SafetyKnowledgeArticle | None:
        """更新安全知识库文章"""
        query = (
            update(SafetyKnowledgeArticle)
            .where(
                SafetyKnowledgeArticle.id == article_id,
                SafetyKnowledgeArticle.is_deleted.is_(False),
            )
            .values(**data, updated_at=func.now())
            .returning(SafetyKnowledgeArticle)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_knowledge_article(self, article_id: uuid.UUID) -> bool:
        """删除安全知识库文章（软删除）"""
        query = (
            update(SafetyKnowledgeArticle)
            .where(
                SafetyKnowledgeArticle.id == article_id,
                SafetyKnowledgeArticle.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    async def get_article_by_no(
        self, article_no: str
    ) -> SafetyKnowledgeArticle | None:
        """按文档编号查询（用于唯一性检查）"""
        query = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.article_no == article_no,
            SafetyKnowledgeArticle.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def check_similar_articles(
        self, title: str
    ) -> list[SafetyKnowledgeArticle]:
        """按标题模糊匹配检测相似文档（快速筛查）"""
        like = f"%{title.strip()}%"
        query = (
            select(SafetyKnowledgeArticle)
            .where(
                SafetyKnowledgeArticle.is_deleted.is_(False),
                SafetyKnowledgeArticle.title.ilike(like),
            )
            .limit(5)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_article_versions(
        self, article_id: uuid.UUID
    ) -> list[SafetyKnowledgeArticle]:
        """获取版本链（同一文档的所有版本）。

        语义：旧版本.superseded_by_id → 新版本.id
        从当前文档出发，双向遍历完整版本链，返回按 version 升序排列的列表。
        """
        current = await self.get_knowledge_article_by_id(article_id)
        if not current:
            return []

        chain: list[SafetyKnowledgeArticle] = [current]
        visited: set[uuid.UUID] = {current.id}

        # 1. Walk backward: find older versions (docs whose superseded_by_id
        #    points to any doc already in the chain)
        changed = True
        while changed:
            changed = False
            superseded_ids = [a.id for a in chain]
            stmt = select(SafetyKnowledgeArticle).where(
                SafetyKnowledgeArticle.superseded_by_id.in_(superseded_ids),
                SafetyKnowledgeArticle.is_deleted.is_(False),
            )
            result = await self.session.execute(stmt)
            for older in result.scalars().all():
                if older.id not in visited:
                    visited.add(older.id)
                    chain.append(older)
                    changed = True

        # 2. Walk forward: find newer versions (docs that the current docs'
        #    superseded_by_id fields point to)
        for article in list(chain):
            if article.superseded_by_id and article.superseded_by_id not in visited:
                newer = await self.get_knowledge_article_by_id(article.superseded_by_id)
                if newer and newer.id not in visited:
                    visited.add(newer.id)
                    chain.append(newer)

        # Sort by version ascending (oldest first), then by created_at
        chain.sort(
            key=lambda a: (a.version or 1, a.created_at or datetime.min)
        )

        return chain

    async def search_by_keywords(
        self,
        keywords: list[str],
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[SafetyKnowledgeArticle], int]:
        """按关键词列表搜索文章（用于语义搜索）"""
        like_clauses = []
        for kw in keywords:
            like = f"%{kw}%"
            like_clauses.append(
                SafetyKnowledgeArticle.title.ilike(like)
                | SafetyKnowledgeArticle.summary.ilike(like)
                | SafetyKnowledgeArticle.content.ilike(like)
                | SafetyKnowledgeArticle.tags.ilike(like)
                | SafetyKnowledgeArticle.source.ilike(like)
                | SafetyKnowledgeArticle.author.ilike(like)
            )

        base_where = SafetyKnowledgeArticle.is_deleted.is_(False)
        combined = base_where
        for clause in like_clauses:
            combined = combined & clause

        query = select(SafetyKnowledgeArticle).where(combined)
        count_query = select(func.count(SafetyKnowledgeArticle.id)).where(combined)

        total = await self.session.scalar(count_query)
        query = (
            query.offset(skip)
            .limit(limit)
            .order_by(SafetyKnowledgeArticle.created_at.desc())
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_max_article_seq_for_date(
        self, prefix: str, date_str: str
    ) -> int:
        """获取指定前缀和日期的最大序号（用于自动编号）"""
        pattern = f"{prefix}-{date_str}-%"
        query = select(SafetyKnowledgeArticle.article_no).where(
            SafetyKnowledgeArticle.article_no.ilike(pattern),
            SafetyKnowledgeArticle.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        existing = result.scalars().all()
        max_seq = 0
        for no in existing:
            if no:
                try:
                    seq = int(no.rsplit("-", 1)[-1])
                    if seq > max_seq:
                        max_seq = seq
                except (ValueError, IndexError):
                    pass
        return max_seq

    # ==================== 八大特殊作业报备 Operations ====================

    async def get_special_operation_reports(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        operation_type: str | None = None,
        operation_level: str | None = None,
        risk_level: str | None = None,
        department: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        is_critical: bool | None = None,
    ) -> tuple[list[SpecialOperationReport], int]:
        """获取特殊作业报备列表"""
        query = select(SpecialOperationReport).where(SpecialOperationReport.is_deleted.is_(False))
        count_query = select(func.count(SpecialOperationReport.id)).where(
            SpecialOperationReport.is_deleted.is_(False)
        )

        def _apply_filters(q: Any) -> Any:
            if status:
                q = q.where(SpecialOperationReport.status == status)
            if operation_type:
                q = q.where(SpecialOperationReport.operation_type == operation_type)
            if operation_level:
                q = q.where(SpecialOperationReport.operation_level == operation_level)
            if risk_level:
                q = q.where(SpecialOperationReport.risk_level == risk_level)
            if department:
                q = q.where(SpecialOperationReport.department == department)
            if date_from:
                q = q.where(SpecialOperationReport.planned_start_time >= date_from)
            if date_to:
                q = q.where(SpecialOperationReport.planned_end_time <= date_to)
            if is_critical is not None:
                q = q.where(SpecialOperationReport.is_critical == is_critical)
            if keyword:
                like = f"%{keyword}%"
                q = q.where(
                    SpecialOperationReport.report_no.ilike(like)
                    | SpecialOperationReport.work_description.ilike(like)
                    | SpecialOperationReport.location.ilike(like)
                )
            return q

        query = _apply_filters(query)
        count_query = _apply_filters(count_query)

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(
            SpecialOperationReport.planned_start_time.desc()
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_special_operation_report_by_id(
        self, report_id: uuid.UUID
    ) -> SpecialOperationReport | None:
        """获取特殊作业报备详情"""
        query = select(SpecialOperationReport).where(
            SpecialOperationReport.id == report_id,
            SpecialOperationReport.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_special_operation_report(
        self, data: dict[str, Any]
    ) -> SpecialOperationReport:
        """创建特殊作业报备"""
        item = SpecialOperationReport(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(SpecialOperationReport).where(SpecialOperationReport.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_special_operation_report(
        self, report_id: uuid.UUID, data: dict[str, Any]
    ) -> SpecialOperationReport | None:
        """更新特殊作业报备"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(SpecialOperationReport)
            .where(
                SpecialOperationReport.id == report_id,
                SpecialOperationReport.is_deleted.is_(False),
            )
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(SpecialOperationReport)
            .where(
                SpecialOperationReport.id == report_id,
                SpecialOperationReport.is_deleted.is_(False),
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_special_operation_report(self, report_id: uuid.UUID) -> bool:
        """删除特殊作业报备（软删除）"""
        query = (
            update(SpecialOperationReport)
            .where(
                SpecialOperationReport.id == report_id,
                SpecialOperationReport.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ── 特殊作业台账查询 ──

    async def get_special_operation_ledger(
        self,
        skip: int = 0,
        limit: int = 20,
        status_list: list[str] | None = None,
        operation_type: str | None = None,
        operation_level: str | None = None,
        risk_level: str | None = None,
        department: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
        is_critical: bool | None = None,
    ) -> tuple[list[SpecialOperationReport], int]:
        """获取特殊作业台账列表（审批中+已审批的报备记录）"""
        if status_list is None:
            status_list = ["submitted", "approved"]

        query = select(SpecialOperationReport).where(
            SpecialOperationReport.is_deleted.is_(False),
            SpecialOperationReport.status.in_(status_list),
        )
        count_query = select(func.count(SpecialOperationReport.id)).where(
            SpecialOperationReport.is_deleted.is_(False),
            SpecialOperationReport.status.in_(status_list),
        )

        if operation_type:
            query = query.where(SpecialOperationReport.operation_type == operation_type)
            count_query = count_query.where(SpecialOperationReport.operation_type == operation_type)
        if operation_level:
            query = query.where(SpecialOperationReport.operation_level == operation_level)
            count_query = count_query.where(SpecialOperationReport.operation_level == operation_level)
        if risk_level:
            query = query.where(SpecialOperationReport.risk_level == risk_level)
            count_query = count_query.where(SpecialOperationReport.risk_level == risk_level)
        if department:
            query = query.where(SpecialOperationReport.department == department)
            count_query = count_query.where(SpecialOperationReport.department == department)
        if date_from:
            query = query.where(SpecialOperationReport.planned_start_time >= date_from)
            count_query = count_query.where(SpecialOperationReport.planned_start_time >= date_from)
        if date_to:
            query = query.where(SpecialOperationReport.planned_end_time <= date_to)
            count_query = count_query.where(SpecialOperationReport.planned_end_time <= date_to)
        if is_critical is not None:
            query = query.where(SpecialOperationReport.is_critical == is_critical)
            count_query = count_query.where(SpecialOperationReport.is_critical == is_critical)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                SpecialOperationReport.report_no.ilike(like)
                | SpecialOperationReport.work_description.ilike(like)
                | SpecialOperationReport.location.ilike(like)
            )
            count_query = count_query.where(
                SpecialOperationReport.report_no.ilike(like)
                | SpecialOperationReport.work_description.ilike(like)
                | SpecialOperationReport.location.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(
            SpecialOperationReport.planned_start_time.desc()
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_special_operation_ledger_stats(
        self, status_list: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """按作业类型统计台账数量和关键作业数量"""
        if status_list is None:
            status_list = ["submitted", "approved"]

        query = (
            select(
                SpecialOperationReport.operation_type,
                func.count(SpecialOperationReport.id).label("count"),
                func.sum(
                    func.cast(SpecialOperationReport.is_critical, Integer)
                ).label("critical_count"),
            )
            .where(
                SpecialOperationReport.is_deleted.is_(False),
                SpecialOperationReport.status.in_(status_list),
            )
            .group_by(SpecialOperationReport.operation_type)
            .order_by(func.count(SpecialOperationReport.id).desc())
        )
        result = await self.session.execute(query)
        return [{"operation_type": r[0], "count": r[1], "critical_count": r[2] or 0} for r in result.all()]

    # ==================== 关键风险作业报备（Bitable 只读） ====================

    async def get_key_risk_operation_reports(
        self,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        area: str | None = None,
        operation_content: str | None = None,
        apply_status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        keyword: str | None = None,
    ) -> tuple[list[KeyRiskOperationReport], int]:
        """获取关键风险作业报备列表（只读）"""
        query = select(KeyRiskOperationReport).where(
            KeyRiskOperationReport.is_deleted.is_(False),  # noqa: E712
            KeyRiskOperationReport.source == "bitable",
        )
        count_query = select(func.count(KeyRiskOperationReport.id)).where(
            KeyRiskOperationReport.is_deleted.is_(False),  # noqa: E712
            KeyRiskOperationReport.source == "bitable",
        )

        def _apply_filters(q: Any) -> Any:
            if department:
                q = q.where(KeyRiskOperationReport.department == department)
            if area:
                q = q.where(KeyRiskOperationReport.area == area)
            if operation_content:
                q = q.where(KeyRiskOperationReport.operation_content == operation_content)
            if apply_status:
                q = q.where(KeyRiskOperationReport.apply_status == apply_status)
            if date_from:
                q = q.where(KeyRiskOperationReport.start_time >= date_from)
            if date_to:
                q = q.where(KeyRiskOperationReport.start_time <= date_to)
            if keyword:
                like = f"%{keyword}%"
                q = q.where(
                    KeyRiskOperationReport.report_no.ilike(like)
                    | KeyRiskOperationReport.operation_content.ilike(like)
                    | KeyRiskOperationReport.area.ilike(like)
                    | KeyRiskOperationReport.department.ilike(like)
                )
            return q

        query = _apply_filters(query)
        count_query = _apply_filters(count_query)

        total = await self.session.scalar(count_query)
        query = query.order_by(KeyRiskOperationReport.start_time.desc().nullslast()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_key_risk_operation_report_by_id(
        self, report_id: uuid.UUID
    ) -> KeyRiskOperationReport | None:
        """获取关键风险作业报备详情"""
        query = select(KeyRiskOperationReport).where(
            KeyRiskOperationReport.id == report_id,
            KeyRiskOperationReport.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_key_risk_operation_report_by_record_id(
        self, record_id: str
    ) -> KeyRiskOperationReport | None:
        """按 feishu_record_id 获取未删除记录（同步用）"""
        query = select(KeyRiskOperationReport).where(
            KeyRiskOperationReport.feishu_record_id == record_id,
            KeyRiskOperationReport.source == "bitable",
            KeyRiskOperationReport.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_key_risk_operation_stats(
        self,
        today_start: datetime,
        today_end: datetime,
        month_start: datetime,
        month_end: datetime,
    ) -> dict[str, Any]:
        """关键风险作业 KPI 统计（bounds 为 UTC 时刻，北京时间口径由调用方换算）。"""
        base = (
            KeyRiskOperationReport.is_deleted.is_(False)  # noqa: E712
        ) & (KeyRiskOperationReport.source == "bitable")
        approved = KeyRiskOperationReport.apply_status == "已通过"

        today_approved = await self.session.scalar(
            select(func.count(KeyRiskOperationReport.id)).where(
                base, approved,
                KeyRiskOperationReport.start_time >= today_start,
                KeyRiskOperationReport.start_time < today_end,
            )
        )
        in_progress = await self.session.scalar(
            select(func.count(KeyRiskOperationReport.id)).where(
                base, KeyRiskOperationReport.apply_status == "审批中"
            )
        )
        month_approved = await self.session.scalar(
            select(func.count(KeyRiskOperationReport.id)).where(
                base, approved,
                KeyRiskOperationReport.start_time >= month_start,
                KeyRiskOperationReport.start_time < month_end,
            )
        )
        total = await self.session.scalar(
            select(func.count(KeyRiskOperationReport.id)).where(base)
        )
        return {
            "today_approved": today_approved or 0,
            "in_progress": in_progress or 0,
            "month_approved": month_approved or 0,
            "total": total or 0,
        }

    # ==================== EHS变更管理 (MOC) Operations ====================

    async def get_ehs_changes(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        change_type: str | None = None,
        change_grade: str | None = None,
        change_duration: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
        source: str | None = None,
        feishu_table_id: str | None = None,
        sort_by: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[EhsChange], int]:
        """获取EHS变更列表"""
        query = select(EhsChange).where(EhsChange.is_deleted.is_(False))
        count_query = select(func.count(EhsChange.id)).where(EhsChange.is_deleted.is_(False))

        if status:
            query = query.where(EhsChange.status == status)
            count_query = count_query.where(EhsChange.status == status)
        if change_type:
            query = query.where(EhsChange.change_type == change_type)
            count_query = count_query.where(EhsChange.change_type == change_type)
        if change_grade:
            query = query.where(EhsChange.change_grade == change_grade)
            count_query = count_query.where(EhsChange.change_grade == change_grade)
        if change_duration:
            query = query.where(EhsChange.change_duration == change_duration)
            count_query = count_query.where(EhsChange.change_duration == change_duration)
        if department:
            query = query.where(EhsChange.department == department)
            count_query = count_query.where(EhsChange.department == department)
        if source:
            query = query.where(EhsChange.source == source)
            count_query = count_query.where(EhsChange.source == source)
        if feishu_table_id:
            query = query.where(EhsChange.feishu_table_id == feishu_table_id)
            count_query = count_query.where(EhsChange.feishu_table_id == feishu_table_id)
        if keyword:
            keyword_filter = EhsChange.title.ilike(f"%{keyword}%")
            query = query.where(keyword_filter)
            count_query = count_query.where(keyword_filter)

        # 排序（支持 change_no / expected_start / acceptance_date / created_at）
        if sort_by == "change_no":
            order_col = EhsChange.change_no
        elif sort_by == "expected_start":
            order_col = EhsChange.expected_start
        elif sort_by == "acceptance_date":
            # acceptance_date 存于 bt_extra JSON（ISO 字符串，字典序=时间序）
            order_col = func.json_extract_path_text(EhsChange.bt_extra, "acceptance_date")
        else:
            order_col = EhsChange.created_at
        order_clause = order_col.desc() if sort_order == "desc" else order_col.asc()

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(order_clause.nulls_last())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_ehs_changes_for_stats(
        self,
        feishu_table_id: str | None = None,
        source: str | None = None,
    ) -> list[EhsChange]:
        """查询 EHS 变更全量（不分页，供统计用）。"""
        query = select(EhsChange).where(EhsChange.is_deleted.is_(False))
        if feishu_table_id:
            query = query.where(EhsChange.feishu_table_id == feishu_table_id)
        if source:
            query = query.where(EhsChange.source == source)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_ehs_change_by_id(self, change_id: uuid.UUID) -> EhsChange | None:
        """获取EHS变更详情"""
        query = select(EhsChange).where(
            EhsChange.id == change_id,
            EhsChange.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_ehs_change_by_no(self, change_no: str) -> EhsChange | None:
        """根据编号获取EHS变更"""
        query = select(EhsChange).where(
            EhsChange.change_no == change_no,
            EhsChange.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_ehs_change_by_feishu_id(self, feishu_record_id: str) -> EhsChange | None:
        """按飞书 Bitable 记录 ID 查询（同步主键）"""
        query = select(EhsChange).where(
            EhsChange.feishu_record_id == feishu_record_id,
            EhsChange.source == "bitable",
            EhsChange.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_ehs_change(self, data: dict[str, Any]) -> EhsChange:
        """创建EHS变更"""
        item = EhsChange(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(EhsChange).where(EhsChange.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_ehs_change(
        self, change_id: uuid.UUID, data: dict[str, Any]
    ) -> EhsChange | None:
        """更新EHS变更"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(EhsChange)
            .where(
                EhsChange.id == change_id,
                EhsChange.is_deleted.is_(False),
            )
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(EhsChange)
            .where(
                EhsChange.id == change_id,
                EhsChange.is_deleted.is_(False),
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_ehs_change(self, change_id: uuid.UUID) -> bool:
        """删除EHS变更（软删除）"""
        query = (
            update(EhsChange)
            .where(
                EhsChange.id == change_id,
                EhsChange.is_deleted.is_(False),
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== ContractorAdmission Operations ====================

    async def get_contractor_admission_by_feishu_id(
        self, feishu_record_id: str
    ) -> ContractorAdmission | None:
        """按飞书 Bitable 记录 ID 查询（同步主键）"""
        query = select(ContractorAdmission).where(
            ContractorAdmission.feishu_record_id == feishu_record_id,
            ContractorAdmission.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_contractor_admission(self, data: dict[str, Any]) -> ContractorAdmission:
        """创建相关方准入（INSERT flush 即可，PostgreSQL RETURNING 回填 id/created_at）"""
        item = ContractorAdmission(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(ContractorAdmission).where(ContractorAdmission.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_contractor_admission(
        self, admission_id: uuid.UUID, data: dict[str, Any]
    ) -> ContractorAdmission | None:
        """更新相关方准入"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(ContractorAdmission)
            .where(
                ContractorAdmission.id == admission_id,
                ContractorAdmission.is_deleted.is_(False),
            )
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(ContractorAdmission)
            .where(
                ContractorAdmission.id == admission_id,
                ContractorAdmission.is_deleted.is_(False),
            )
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def soft_delete_contractor_admission_by_feishu_id(
        self, feishu_record_id: str
    ) -> bool:
        """按 feishu_record_id 软删除 Bitable 来源记录（仅 source='bitable'）"""
        query = (
            update(ContractorAdmission)
            .where(
                ContractorAdmission.feishu_record_id == feishu_record_id,
                ContractorAdmission.source == "bitable",
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return (cast(CursorResult[Any], result).rowcount or 0) > 0

    # ==================== OhHealthExam Operations ====================

    async def get_health_exams(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        exam_type: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
        ai_conclusion: str | None = None,
        ai_parse_status: str | None = None,
    ) -> tuple[list[OhHealthExam], int]:
        """获取职业健康体检列表"""
        query = select(OhHealthExam).where(OhHealthExam.is_deleted.is_(False))

        if status:
            query = query.where(OhHealthExam.status == status)
        if exam_type:
            query = query.where(OhHealthExam.exam_type == exam_type)
        if department:
            query = query.where(OhHealthExam.department == department)
        if ai_conclusion:
            query = query.where(
                or_(
                    OhHealthExam.ai_conclusion == ai_conclusion,
                    OhHealthExam.override_conclusion == ai_conclusion,
                )
            )
        if ai_parse_status:
            query = query.where(OhHealthExam.ai_parse_status == ai_parse_status)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                OhHealthExam.exam_no.ilike(like)
                | OhHealthExam.employee_name.ilike(like)
                | OhHealthExam.department.ilike(like)
                | OhHealthExam.id_card_no.ilike(like)
            )

        count_query = select(func.count(OhHealthExam.id)).where(OhHealthExam.is_deleted.is_(False))
        if status:
            count_query = count_query.where(OhHealthExam.status == status)
        if exam_type:
            count_query = count_query.where(OhHealthExam.exam_type == exam_type)
        if department:
            count_query = count_query.where(OhHealthExam.department == department)
        if ai_conclusion:
            count_query = count_query.where(
                or_(
                    OhHealthExam.ai_conclusion == ai_conclusion,
                    OhHealthExam.override_conclusion == ai_conclusion,
                )
            )
        if ai_parse_status:
            count_query = count_query.where(OhHealthExam.ai_parse_status == ai_parse_status)
        if keyword:
            like = f"%{keyword}%"
            count_query = count_query.where(
                OhHealthExam.exam_no.ilike(like)
                | OhHealthExam.employee_name.ilike(like)
                | OhHealthExam.department.ilike(like)
                | OhHealthExam.id_card_no.ilike(like)
            )

        query = query.order_by(OhHealthExam.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        items = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def get_health_exam_by_id(self, exam_id: uuid.UUID) -> OhHealthExam | None:
        """获取职业健康体检详情"""
        query = select(OhHealthExam).where(
            OhHealthExam.id == exam_id, OhHealthExam.is_deleted.is_(False)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_health_exam_by_no(self, exam_no: str) -> OhHealthExam | None:
        """按编号获取职业健康体检"""
        query = select(OhHealthExam).where(
            OhHealthExam.exam_no == exam_no, OhHealthExam.is_deleted.is_(False)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_health_exam(self, data: dict[str, Any]) -> OhHealthExam:
        """创建职业健康体检"""
        item = OhHealthExam(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OhHealthExam).where(OhHealthExam.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_health_exam(
        self, exam_id: uuid.UUID, data: dict[str, Any]
    ) -> OhHealthExam | None:
        """更新职业健康体检"""
        query = (
            update(OhHealthExam)
            .where(OhHealthExam.id == exam_id, OhHealthExam.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
            .returning(OhHealthExam)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_health_exam(self, exam_id: uuid.UUID) -> bool:
        """软删除职业健康体检（清空 exam_no/feishu_record_id 唯一键，防删→加重复）"""
        query = (
            update(OhHealthExam)
            .where(OhHealthExam.id == exam_id, OhHealthExam.is_deleted.is_(False))
            .values(is_deleted=True, exam_no=None, feishu_record_id=None)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    async def get_health_exam_by_feishu_id(self, feishu_record_id: str) -> OhHealthExam | None:
        """按 Bitable 记录 ID 获取体检记录（活行）"""
        query = select(OhHealthExam).where(
            OhHealthExam.feishu_record_id == feishu_record_id,
            OhHealthExam.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_health_exam_by_source(
        self, source_table: str, source_record_id: str
    ) -> OhHealthExam | None:
        """按来源表 + 来源记录 ID 获取体检记录（活行，D7 来源联动幂等键，走 uq_oh_exams_source）"""
        query = select(OhHealthExam).where(
            OhHealthExam.source_table == source_table,
            OhHealthExam.source_record_id == source_record_id,
            OhHealthExam.is_deleted.is_(False),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_latest_health_exam_by_person(
        self,
        name: str,
        id_card_no: str | None = None,
        person_id: uuid.UUID | None = None,
    ) -> OhHealthExam | None:
        """按姓名+身份证（或 person_id）取最近一次体检记录（供工作流②/总表回填）"""
        query = select(OhHealthExam).where(
            OhHealthExam.employee_name == name,
            OhHealthExam.is_deleted.is_(False),
        )
        if person_id is not None:
            query = query.where(OhHealthExam.person_id == person_id)
        elif id_card_no:
            query = query.where(OhHealthExam.id_card_no == id_card_no)
        query = query.order_by(
            OhHealthExam.exam_date.desc().nulls_last(), OhHealthExam.created_at.desc()
        ).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_pending_health_exams_by_name(
        self, name: str, limit: int = 20,
    ) -> list[OhHealthExam]:
        """按姓名取「未体检」体检记录（最新在前；供报告归档匹配，设计 §13.6.3）"""
        query = (
            select(OhHealthExam)
            .where(
                OhHealthExam.employee_name == name,
                OhHealthExam.is_deleted.is_(False),  # noqa: E712
                OhHealthExam.status == "pending",
            )
            .order_by(
                OhHealthExam.scheduled_date.desc().nulls_last(),
                OhHealthExam.created_at.desc(),
            )
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_oh_exams_by_person(self, person_id: uuid.UUID) -> list[OhHealthExam]:
        """按人员获取体检记录链"""
        query = (
            select(OhHealthExam)
            .where(OhHealthExam.person_id == person_id, OhHealthExam.is_deleted.is_(False))
            .order_by(OhHealthExam.exam_date.desc().nulls_last(), OhHealthExam.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ==================== OhPerson Operations ====================

    async def get_oh_persons(
        self,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        position: str | None = None,
        hazard_exposure: str | None = None,
        last_exam_conclusion: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhPerson], int]:
        """获取人员汇总台账列表"""
        filters = [OhPerson.is_deleted.is_(False)]  # noqa: E712
        if department:
            filters.append(OhPerson.department == department)
        if position:
            filters.append(OhPerson.position == position)
        if last_exam_conclusion:
            filters.append(OhPerson.last_exam_conclusion == last_exam_conclusion)
        if hazard_exposure in ("yes", "true", "1"):
            # JSON 列不支持 != 比较（PG json 无等值运算符），只用数值 + 非空判断
            filters.append(
                or_(
                    OhPerson.hazard_exposure_years > 0,
                    OhPerson.hazard_factors.is_not(None),
                )
            )
        if keyword:
            like = f"%{keyword}%"
            filters.append(
                OhPerson.name.ilike(like)
                | OhPerson.id_card_no.ilike(like)
                | OhPerson.employee_no.ilike(like)
                | OhPerson.department.ilike(like)
                | OhPerson.phone.ilike(like)
            )

        total = await self.session.scalar(
            select(func.count(OhPerson.id)).where(*filters)
        )
        query = (
            select(OhPerson)
            .where(*filters)
            .order_by(OhPerson.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all()), int(total or 0)

    async def get_oh_person_by_id(self, person_id: uuid.UUID) -> OhPerson | None:
        query = select(OhPerson).where(
            OhPerson.id == person_id, OhPerson.is_deleted.is_(False)  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_oh_person_by_name_idcard(
        self, name: str, id_card_no: str | None
    ) -> OhPerson | None:
        """按姓名+身份证匹配人员（关联主键，98% 覆盖）"""
        query = select(OhPerson).where(
            OhPerson.name == name, OhPerson.is_deleted.is_(False)  # noqa: E712
        )
        if id_card_no:
            query = query.where(OhPerson.id_card_no == id_card_no)
        query = query.order_by(OhPerson.created_at.desc()).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_oh_person_by_feishu_id(self, feishu_record_id: str) -> OhPerson | None:
        query = select(OhPerson).where(
            OhPerson.feishu_record_id == feishu_record_id,
            OhPerson.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_oh_person(self, data: dict[str, Any]) -> OhPerson:
        item = OhPerson(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OhPerson).where(OhPerson.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_oh_person(
        self, person_id: uuid.UUID, data: dict[str, Any]
    ) -> OhPerson | None:
        query = (
            update(OhPerson)
            .where(OhPerson.id == person_id, OhPerson.is_deleted.is_(False))  # noqa: E712
            .values(**data, updated_at=func.now())
            .returning(OhPerson)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_oh_person(self, person_id: uuid.UUID) -> bool:
        """软删除人员（清空 id_card_no/employee_no/feishu_record_id 唯一键）"""
        query = (
            update(OhPerson)
            .where(OhPerson.id == person_id, OhPerson.is_deleted.is_(False))  # noqa: E712
            .values(is_deleted=True, id_card_no=None, employee_no=None, feishu_record_id=None)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== OhPosition Operations ====================

    async def get_oh_positions(
        self,
        skip: int = 0,
        limit: int = 20,
        department: str | None = None,
        hazard_factors_status: str | None = None,
    ) -> tuple[list[OhPosition], int]:
        filters = [OhPosition.is_deleted.is_(False)]  # noqa: E712
        if department:
            filters.append(OhPosition.department == department)
        if hazard_factors_status:
            filters.append(OhPosition.hazard_factors_status == hazard_factors_status)

        total = await self.session.scalar(
            select(func.count(OhPosition.id)).where(*filters)
        )
        query = (
            select(OhPosition)
            .where(*filters)
            .order_by(OhPosition.department.asc().nulls_last(), OhPosition.position.asc().nulls_last())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all()), int(total or 0)

    async def get_oh_position_by_id(self, position_id: uuid.UUID) -> OhPosition | None:
        query = select(OhPosition).where(
            OhPosition.id == position_id, OhPosition.is_deleted.is_(False)  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_oh_position_by_dept_position(
        self, department: str, position: str
    ) -> OhPosition | None:
        query = select(OhPosition).where(
            OhPosition.department == department,
            OhPosition.position == position,
            OhPosition.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_oh_position_by_feishu_id(self, feishu_record_id: str) -> OhPosition | None:
        query = select(OhPosition).where(
            OhPosition.feishu_record_id == feishu_record_id,
            OhPosition.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_oh_position(self, data: dict[str, Any]) -> OhPosition:
        item = OhPosition(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OhPosition).where(OhPosition.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_oh_position(
        self, position_id: uuid.UUID, data: dict[str, Any]
    ) -> OhPosition | None:
        query = (
            update(OhPosition)
            .where(OhPosition.id == position_id, OhPosition.is_deleted.is_(False))  # noqa: E712
            .values(**data, updated_at=func.now())
            .returning(OhPosition)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_oh_position(self, position_id: uuid.UUID) -> bool:
        query = (
            update(OhPosition)
            .where(OhPosition.id == position_id, OhPosition.is_deleted.is_(False))  # noqa: E712
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== OhHazardFactor Operations ====================

    async def get_oh_hazard_factors(
        self, skip: int = 0, limit: int = 50
    ) -> tuple[list[OhHazardFactor], int]:
        filters = [OhHazardFactor.is_deleted.is_(False)]  # noqa: E712
        total = await self.session.scalar(
            select(func.count(OhHazardFactor.id)).where(*filters)
        )
        query = (
            select(OhHazardFactor)
            .where(*filters)
            .order_by(OhHazardFactor.factor_name.asc())
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all()), int(total or 0)

    async def get_all_oh_hazard_factors(self) -> list[OhHazardFactor]:
        """全部活行危害因素（供 PPE 对照表）"""
        query = select(OhHazardFactor).where(
            OhHazardFactor.is_deleted.is_(False)  # noqa: E712
        ).order_by(OhHazardFactor.factor_name.asc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_oh_hazard_factor_by_id(self, factor_id: uuid.UUID) -> OhHazardFactor | None:
        query = select(OhHazardFactor).where(
            OhHazardFactor.id == factor_id, OhHazardFactor.is_deleted.is_(False)  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_oh_hazard_factor_by_name(self, factor_name: str) -> OhHazardFactor | None:
        query = select(OhHazardFactor).where(
            OhHazardFactor.factor_name == factor_name,
            OhHazardFactor.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_oh_hazard_factor_by_feishu_id(self, feishu_record_id: str) -> OhHazardFactor | None:
        query = select(OhHazardFactor).where(
            OhHazardFactor.feishu_record_id == feishu_record_id,
            OhHazardFactor.is_deleted.is_(False),  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_oh_hazard_factor(self, data: dict[str, Any]) -> OhHazardFactor:
        item = OhHazardFactor(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OhHazardFactor).where(OhHazardFactor.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_oh_hazard_factor(
        self, factor_id: uuid.UUID, data: dict[str, Any]
    ) -> OhHazardFactor | None:
        query = (
            update(OhHazardFactor)
            .where(OhHazardFactor.id == factor_id, OhHazardFactor.is_deleted.is_(False))  # noqa: E712
            .values(**data, updated_at=func.now())
            .returning(OhHazardFactor)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_oh_hazard_factor(self, factor_id: uuid.UUID) -> bool:
        """软删除危害因素字典项（清 factor_name 唯一键）"""
        query = (
            update(OhHazardFactor)
            .where(OhHazardFactor.id == factor_id, OhHazardFactor.is_deleted.is_(False))  # noqa: E712
            .values(is_deleted=True, factor_name=None)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== OhFollowup Operations ====================

    async def get_oh_followups(
        self,
        *,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        category: str | None = None,
        person_id: uuid.UUID | None = None,
        due_order: bool = True,
    ) -> tuple[list[OhFollowup], int]:
        """异常随访列表（status/category/person_id 筛选 + 到期排序）。

        status='expired' 为到期派生筛选（status=open 且 followup_date < today）；
        status='open' 排除已到期记录（到期后由 service 派生展示为 expired）。
        due_order=True 按 followup_date 升序（过期优先），False 按创建时间倒序。
        """
        filters = [OhFollowup.is_deleted.is_(False)]  # noqa: E712
        today = date.today()
        if status == "expired":
            filters.append(OhFollowup.status == "open")
            filters.append(OhFollowup.followup_date < today)
        elif status == "open":
            filters.append(OhFollowup.status == "open")
            filters.append(
                or_(OhFollowup.followup_date.is_(None), OhFollowup.followup_date >= today)
            )
        elif status:
            filters.append(OhFollowup.status == status)
        if category:
            filters.append(OhFollowup.category == category)
        if person_id:
            filters.append(OhFollowup.person_id == person_id)

        total = await self.session.scalar(
            select(func.count(OhFollowup.id)).where(*filters)
        )
        query = select(OhFollowup).where(*filters)
        if due_order:
            query = query.order_by(
                OhFollowup.followup_date.asc().nulls_last(),
                OhFollowup.created_at.desc(),
            )
        else:
            query = query.order_by(OhFollowup.created_at.desc())
        result = await self.session.execute(query.offset(skip).limit(limit))
        return list(result.scalars().all()), int(total or 0)

    async def get_oh_followup_by_exam_indicator(
        self, exam_id: uuid.UUID, indicator_name: str
    ) -> OhFollowup | None:
        """按体检+指标查活随访（唯一键 exam_id+indicator_name 去重用）"""
        result = await self.session.execute(
            select(OhFollowup).where(
                OhFollowup.exam_id == exam_id,
                OhFollowup.indicator_name == indicator_name,
                OhFollowup.is_deleted.is_(False),  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def get_oh_followups_by_exam(self, exam_id: uuid.UUID) -> list[OhFollowup]:
        query = (
            select(OhFollowup)
            .where(OhFollowup.exam_id == exam_id, OhFollowup.is_deleted.is_(False))  # noqa: E712
            .order_by(OhFollowup.followup_date.asc().nulls_last(), OhFollowup.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_oh_followups_by_person(self, person_id: uuid.UUID) -> list[OhFollowup]:
        query = (
            select(OhFollowup)
            .where(OhFollowup.person_id == person_id, OhFollowup.is_deleted.is_(False))  # noqa: E712
            .order_by(OhFollowup.followup_date.asc().nulls_last(), OhFollowup.created_at.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create_oh_followup(self, data: dict[str, Any]) -> OhFollowup:
        item = OhFollowup(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OhFollowup).where(OhFollowup.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_oh_followup(
        self, followup_id: uuid.UUID, data: dict[str, Any]
    ) -> OhFollowup | None:
        query = (
            update(OhFollowup)
            .where(OhFollowup.id == followup_id, OhFollowup.is_deleted.is_(False))  # noqa: E712
            .values(**data, updated_at=func.now())
            .returning(OhFollowup)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_oh_followup(self, followup_id: uuid.UUID) -> bool:
        """软删除随访（清空 exam_id/indicator_name 唯一键）"""
        query = (
            update(OhFollowup)
            .where(OhFollowup.id == followup_id, OhFollowup.is_deleted.is_(False))  # noqa: E712
            .values(is_deleted=True, exam_id=None, indicator_name=None)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== Contractor Operations ====================

    async def get_contractors(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        qualification_type: str | None = None,
        training_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Contractor], int]:
        """获取承包商列表"""
        query = select(Contractor).where(Contractor.is_deleted.is_(False))
        count_query = select(func.count(Contractor.id)).where(Contractor.is_deleted.is_(False))

        if status:
            query = query.where(Contractor.status == status)
            count_query = count_query.where(Contractor.status == status)
        if qualification_type:
            query = query.where(Contractor.qualification_type == qualification_type)
            count_query = count_query.where(Contractor.qualification_type == qualification_type)
        if training_status:
            query = query.where(Contractor.training_status == training_status)
            count_query = count_query.where(Contractor.training_status == training_status)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                Contractor.company_name.ilike(like)
                | Contractor.contractor_no.ilike(like)
                | Contractor.contact_person.ilike(like)
            )
            count_query = count_query.where(
                Contractor.company_name.ilike(like)
                | Contractor.contractor_no.ilike(like)
                | Contractor.contact_person.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(Contractor.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_contractor_by_id(self, contractor_id: uuid.UUID) -> Contractor | None:
        """获取承包商详情"""
        query = (
            select(Contractor)
            .options(selectinload(Contractor.work_records))
            .where(Contractor.id == contractor_id, Contractor.is_deleted.is_(False))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_contractor(self, data: dict[str, Any]) -> Contractor:
        """创建承包商"""
        item = Contractor(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(Contractor).where(Contractor.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_contractor(
        self, contractor_id: uuid.UUID, data: dict[str, Any]
    ) -> Contractor | None:
        """更新承包商"""
        query = (
            update(Contractor)
            .where(Contractor.id == contractor_id, Contractor.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
            .returning(Contractor)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_contractor(self, contractor_id: uuid.UUID) -> bool:
        """删除承包商（软删除）"""
        query = (
            update(Contractor)
            .where(Contractor.id == contractor_id, Contractor.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0

    # ==================== ContractorWorkRecord Operations ====================

    async def get_work_records_by_contractor(
        self, contractor_id: uuid.UUID
    ) -> list[ContractorWorkRecord]:
        """获取承包商的施工记录列表"""
        query = select(ContractorWorkRecord).where(
            ContractorWorkRecord.contractor_id == contractor_id,
            ContractorWorkRecord.is_deleted.is_(False),
        ).order_by(ContractorWorkRecord.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_work_record_by_id(self, record_id: uuid.UUID) -> ContractorWorkRecord | None:
        """获取施工记录详情"""
        query = select(ContractorWorkRecord).where(
            ContractorWorkRecord.id == record_id, ContractorWorkRecord.is_deleted.is_(False)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_work_record(self, data: dict[str, Any]) -> ContractorWorkRecord:
        """创建施工记录"""
        item = ContractorWorkRecord(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(ContractorWorkRecord).where(ContractorWorkRecord.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_work_record(
        self, record_id: uuid.UUID, data: dict[str, Any]
    ) -> ContractorWorkRecord | None:
        """更新施工记录"""
        query = (
            update(ContractorWorkRecord)
            .where(ContractorWorkRecord.id == record_id, ContractorWorkRecord.is_deleted.is_(False))
            .values(**data, updated_at=func.now())
            .returning(ContractorWorkRecord)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_work_record(self, record_id: uuid.UUID) -> bool:
        """删除施工记录（软删除）"""
        query = (
            update(ContractorWorkRecord)
            .where(ContractorWorkRecord.id == record_id, ContractorWorkRecord.is_deleted.is_(False))
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return cast(CursorResult[Any], result).rowcount > 0


    # ==================== 危化品库存管理 Operations ====================

    async def list_inventory_records(
        self,
        skip: int = 0,
        limit: int = 50,
        *,
        department: str | None = None,
        material_name: str | None = None,
    ) -> tuple[list[ChemicalInventoryRecord], int]:
        """危化品库存记录列表（当前固定行台账，分页 + 筛选）。"""
        filters = [ChemicalInventoryRecord.is_deleted.is_(False)]  # noqa: E712
        if department:
            filters.append(ChemicalInventoryRecord.department == department)
        if material_name:
            filters.append(ChemicalInventoryRecord.material_name.ilike(f"%{material_name}%"))

        total = await self.session.scalar(
            select(func.count()).select_from(ChemicalInventoryRecord).where(*filters)
        )
        stmt = (
            select(ChemicalInventoryRecord)
            .where(*filters)
            .order_by(ChemicalInventoryRecord.department, ChemicalInventoryRecord.material_name)
            .offset(skip)
            .limit(limit)
        )
        items = (await self.session.scalars(stmt)).all()
        return list(items), int(total or 0)

    async def list_all_inventory_records(self) -> list[ChemicalInventoryRecord]:
        """当前全部库存记录（规则扫描/汇总提取用）。"""
        stmt = select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.is_deleted.is_(False),  # noqa: E712
        )
        return list((await self.session.scalars(stmt)).all())

    async def list_inventory_records_by_location(
        self, department: str, storage_location: str | None
    ) -> list[ChemicalInventoryRecord]:
        """同 部门+存放部位 的全部记录（变更触发的混存判断用）。"""
        stmt = select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.department == department,
            ChemicalInventoryRecord.storage_location == storage_location,
            ChemicalInventoryRecord.is_deleted.is_(False),  # noqa: E712
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_inventory_record_by_id(
        self, record_id: uuid.UUID
    ) -> ChemicalInventoryRecord | None:
        return await self.session.get(ChemicalInventoryRecord, record_id)

    async def get_inventory_record_by_feishu_id(
        self, feishu_record_id: str
    ) -> ChemicalInventoryRecord | None:
        stmt = select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.feishu_record_id == feishu_record_id,
            ChemicalInventoryRecord.is_deleted.is_(False),  # noqa: E712
        )
        return cast(ChemicalInventoryRecord | None, await self.session.scalar(stmt))

    async def get_inventory_record_by_key(
        self, department: str, storage_location: str | None, material_name: str
    ) -> ChemicalInventoryRecord | None:
        """按 部门+存放部位+物料名称 找固定行。"""
        stmt = select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.department == department,
            ChemicalInventoryRecord.storage_location == storage_location,
            ChemicalInventoryRecord.material_name == material_name,
            ChemicalInventoryRecord.is_deleted.is_(False),  # noqa: E712
        )
        return cast(ChemicalInventoryRecord | None, await self.session.scalar(stmt))

    async def create_inventory_record(
        self, values: dict[str, Any]
    ) -> ChemicalInventoryRecord:
        row = ChemicalInventoryRecord(**values)
        self.session.add(row)
        await self.session.flush()
        return row

    async def update_inventory_record(
        self, record_id: uuid.UUID, values: dict[str, Any]
    ) -> None:
        await self.session.execute(
            update(ChemicalInventoryRecord)
            .where(ChemicalInventoryRecord.id == record_id)
            .values(**values)
        )

    async def soft_delete_inventory_record(self, record_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            update(ChemicalInventoryRecord)
            .where(
                ChemicalInventoryRecord.id == record_id,
                ChemicalInventoryRecord.is_deleted.is_(False),  # noqa: E712
            )
            .values(is_deleted=True)
        )
        return (cast(CursorResult[Any], result).rowcount or 0) > 0

    async def count_inventory_records_by_flag(self) -> dict[str, int]:
        """当前各风险标记计数（stats 用）。"""
        rows = (
            await self.session.execute(
                select(
                    ChemicalInventoryRecord.risk_flag,
                    func.count().label("cnt"),
                )
                .where(ChemicalInventoryRecord.is_deleted.is_(False))  # noqa: E712
                .group_by(ChemicalInventoryRecord.risk_flag)
            )
        ).all()
        return {row.risk_flag: int(row.cnt) for row in rows}

