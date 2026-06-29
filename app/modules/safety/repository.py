"""Safety database queries."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.safety.models import (
    Accident,
    AIWorkflowConfig,
    Contractor,
    ContractorWorkRecord,
    DailyRiskReport,
    EhsChange,
    HazardIdentification,
    HazardReport,
    OhHazardMonitor,
    OhHealthExam,
    OperationRegulation,
    RegulationRevision,
    SafetyCheck,
    SafetyKnowledgeArticle,
    SafetyTraining,
    ScheduledTask,
    ScheduledTaskLog,
    SpecialOperationPermit,
    SpecialOperationPersonnel,
    SpecialOperationReport,
    TrainingRecord,
)


class SafetyRepository:
    """Safety module repository"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ==================== SafetyCheck Operations ====================

    async def get_checks(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        check_type: str | None = None,
        department: str | None = None,
    ) -> tuple[list[SafetyCheck], int]:
        """获取安全检查列表"""
        query = select(SafetyCheck).where(SafetyCheck.is_deleted == False)

        if status:
            query = query.where(SafetyCheck.status == status)
        if check_type:
            query = query.where(SafetyCheck.check_type == check_type)
        if department:
            query = query.where(SafetyCheck.department == department)

        count_query = select(func.count(SafetyCheck.id)).where(SafetyCheck.is_deleted == False)
        if status:
            count_query = count_query.where(SafetyCheck.status == status)
        if check_type:
            count_query = count_query.where(SafetyCheck.check_type == check_type)
        if department:
            count_query = count_query.where(SafetyCheck.department == department)

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(SafetyCheck.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_check_by_id(self, check_id: uuid.UUID) -> SafetyCheck | None:
        """获取安全检查详情"""
        query = (
            select(SafetyCheck)
            .options(selectinload(SafetyCheck.hazards))
            .where(SafetyCheck.id == check_id, SafetyCheck.is_deleted == False)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_check(self, data: dict[str, Any]) -> SafetyCheck:
        """创建安全检查"""
        item = SafetyCheck(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(SafetyCheck).where(SafetyCheck.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_check(self, check_id: uuid.UUID, data: dict[str, Any]) -> SafetyCheck | None:
        """更新安全检查"""
        query = (
            update(SafetyCheck)
            .where(SafetyCheck.id == check_id, SafetyCheck.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(SafetyCheck)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_check(self, check_id: uuid.UUID) -> bool:
        """删除安全检查（软删除）"""
        query = (
            update(SafetyCheck)
            .where(SafetyCheck.id == check_id, SafetyCheck.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
    ) -> tuple[list[HazardReport], int]:
        """获取隐患列表"""
        query = select(HazardReport).where(HazardReport.is_deleted == False)

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

        count_query = select(func.count(HazardReport.id)).where(HazardReport.is_deleted == False)
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
        ).where(HazardReport.is_deleted == False)

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

    async def get_hazard_by_id(self, hazard_id: uuid.UUID) -> HazardReport | None:
        """获取隐患详情"""
        query = select(HazardReport).where(
            HazardReport.id == hazard_id, HazardReport.is_deleted == False
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
            .where(HazardReport.id == hazard_id, HazardReport.is_deleted == False)
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)

        stmt_select = (
            select(HazardReport)
            .where(HazardReport.id == hazard_id, HazardReport.is_deleted == False)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_hazard(self, hazard_id: uuid.UUID) -> bool:
        """删除隐患（软删除）"""
        query = (
            update(HazardReport)
            .where(HazardReport.id == hazard_id, HazardReport.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    async def count_hazards_today(self, date_prefix: str) -> int:
        """统计指定日期前缀的隐患编号数量（含软删除），用于自动生成序号。"""
        query = select(func.count(HazardReport.id)).where(
            HazardReport.hazard_no.like(f"HZ-{date_prefix}-%"),
        )
        result = await self.session.execute(query)
        return result.scalar() or 0

    # ==================== Accident Operations ====================

    async def get_accidents(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        accident_type: str | None = None,
        accident_level: str | None = None,
        department: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        keyword: str | None = None,
    ) -> tuple[list[Accident], int]:
        """获取事故列表"""
        query = select(Accident).where(Accident.is_deleted == False)
        count_query = select(func.count(Accident.id)).where(Accident.is_deleted == False)

        if status:
            query = query.where(Accident.status == status)
            count_query = count_query.where(Accident.status == status)
        if accident_type:
            query = query.where(Accident.accident_type == accident_type)
            count_query = count_query.where(Accident.accident_type == accident_type)
        if accident_level:
            query = query.where(Accident.accident_level == accident_level)
            count_query = count_query.where(Accident.accident_level == accident_level)
        if department:
            query = query.where(Accident.department == department)
            count_query = count_query.where(Accident.department == department)
        if date_from:
            query = query.where(Accident.happened_at >= date_from)
            count_query = count_query.where(Accident.happened_at >= date_from)
        if date_to:
            query = query.where(Accident.happened_at <= date_to)
            count_query = count_query.where(Accident.happened_at <= date_to)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                Accident.description.ilike(like)
                | Accident.location.ilike(like)
                | Accident.accident_no.ilike(like)
                | Accident.handling_measures.ilike(like)
            )
            count_query = count_query.where(
                Accident.description.ilike(like)
                | Accident.location.ilike(like)
                | Accident.accident_no.ilike(like)
                | Accident.handling_measures.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(Accident.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_accident_by_id(self, accident_id: uuid.UUID) -> Accident | None:
        """获取事故详情"""
        query = select(Accident).where(
            Accident.id == accident_id, Accident.is_deleted == False
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_accident(self, data: dict[str, Any]) -> Accident:
        """创建事故"""
        item = Accident(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(Accident).where(Accident.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_accident(
        self, accident_id: uuid.UUID, data: dict[str, Any]
    ) -> Accident | None:
        """更新事故"""
        # 两步模式：先 UPDATE，再 SELECT + populate_existing 强制刷新 identity map 缓存
        stmt_update = (
            update(Accident)
            .where(Accident.id == accident_id, Accident.is_deleted == False)
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(Accident)
            .where(Accident.id == accident_id, Accident.is_deleted == False)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_accident(self, accident_id: uuid.UUID) -> bool:
        """删除事故（软删除）"""
        query = (
            update(Accident)
            .where(Accident.id == accident_id, Accident.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
        query = select(SafetyTraining).where(SafetyTraining.is_deleted == False)

        if status:
            query = query.where(SafetyTraining.status == status)
        if training_type:
            query = query.where(SafetyTraining.training_type == training_type)
        if department:
            query = query.where(SafetyTraining.department == department)

        count_query = select(func.count(SafetyTraining.id)).where(
            SafetyTraining.is_deleted == False
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
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted == False)
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
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted == False)
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(SafetyTraining)
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted == False)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_training(self, training_id: uuid.UUID) -> bool:
        """删除安全培训（软删除）"""
        query = (
            update(SafetyTraining)
            .where(SafetyTraining.id == training_id, SafetyTraining.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ==================== TrainingRecord Operations ====================

    async def get_records_by_training(self, training_id: uuid.UUID) -> list[TrainingRecord]:
        """获取培训记录列表"""
        query = select(TrainingRecord).where(
            TrainingRecord.training_id == training_id, TrainingRecord.is_deleted == False
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
            .where(TrainingRecord.id == record_id, TrainingRecord.is_deleted == False)
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(TrainingRecord)
            .where(TrainingRecord.id == record_id, TrainingRecord.is_deleted == False)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_training_record(self, record_id: uuid.UUID) -> bool:
        """删除培训记录（软删除）"""
        query = (
            update(TrainingRecord)
            .where(TrainingRecord.id == record_id, TrainingRecord.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
            TrainingRecord.is_deleted == False,
            TrainingRecord.certificate_no.isnot(None),
        )
        count_query = select(func.count(TrainingRecord.id)).where(
            TrainingRecord.is_deleted == False,
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
            TrainingRecord.is_deleted == False,
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
    ) -> tuple[list["HazardIdentification"], int]:
        """获取危险源辨识列表"""
        from datetime import datetime as dt_module



        query = select(HazardIdentification).where(HazardIdentification.is_deleted == False)
        count_query = select(func.count(HazardIdentification.id)).where(
            HazardIdentification.is_deleted == False
        )

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


        base = select(HazardIdentification).where(HazardIdentification.is_deleted == False)
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
                HazardIdentification.is_deleted == False,
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
            HazardIdentification.is_deleted == False,
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
            HazardIdentification.is_deleted == False,
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
            HazardIdentification.id == hid, HazardIdentification.is_deleted == False
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
            .where(HazardIdentification.id == hid, HazardIdentification.is_deleted == False)
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(HazardIdentification)
            .where(HazardIdentification.id == hid, HazardIdentification.is_deleted == False)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_hazard_identification(self, hid: uuid.UUID) -> bool:
        """删除危险源辨识记录（软删除）"""


        query = (
            update(HazardIdentification)
            .where(HazardIdentification.id == hid, HazardIdentification.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
                HazardIdentification.is_deleted == False,
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
        query = select(OperationRegulation).where(OperationRegulation.is_deleted == False)
        count_query = select(func.count(OperationRegulation.id)).where(
            OperationRegulation.is_deleted == False
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
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted == False)
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
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted == False)
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(OperationRegulation)
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted == False)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt_select)
        return result.scalar_one_or_none()

    async def delete_regulation(self, regulation_id: uuid.UUID) -> bool:
        """删除安全操作规程（软删除）"""
        query = (
            update(OperationRegulation)
            .where(OperationRegulation.id == regulation_id, OperationRegulation.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
        query = select(RegulationRevision).where(RegulationRevision.is_deleted == False)
        count_query = select(func.count(RegulationRevision.id)).where(
            RegulationRevision.is_deleted == False
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
            .where(RegulationRevision.id == revision_id, RegulationRevision.is_deleted == False)
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
            .where(RegulationRevision.id == revision_id, RegulationRevision.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(RegulationRevision)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_revision(self, revision_id: uuid.UUID) -> bool:
        """删除修订记录（软删除）"""
        query = (
            update(RegulationRevision)
            .where(RegulationRevision.id == revision_id, RegulationRevision.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ==================== AI 工作流配置 Operations ====================

    async def get_ai_workflow_configs(
        self,
        skip: int = 0,
        limit: int = 100,
        module_code: str | None = None,
        is_enabled: bool | None = None,
    ) -> tuple[list[AIWorkflowConfig], int]:
        """获取 AI 工作流配置列表"""
        query = select(AIWorkflowConfig).where(AIWorkflowConfig.is_deleted == False)

        if module_code:
            query = query.where(AIWorkflowConfig.module_code == module_code)
        if is_enabled is not None:
            query = query.where(AIWorkflowConfig.is_enabled == is_enabled)

        count_query = select(func.count(AIWorkflowConfig.id)).where(
            AIWorkflowConfig.is_deleted == False
        )
        if module_code:
            count_query = count_query.where(AIWorkflowConfig.module_code == module_code)
        if is_enabled is not None:
            count_query = count_query.where(AIWorkflowConfig.is_enabled == is_enabled)

        total = (await self.session.execute(count_query)).scalar_one()

        query = query.order_by(AIWorkflowConfig.sort_order, AIWorkflowConfig.created_at)
        query = query.offset(skip).limit(limit)
        result = await self.session.execute(query)
        items = list(result.scalars().all())

        return items, total or 0

    async def get_ai_workflow_config_by_id(
        self, config_id: uuid.UUID
    ) -> AIWorkflowConfig | None:
        """获取 AI 工作流配置详情"""
        query = select(AIWorkflowConfig).where(
            AIWorkflowConfig.id == config_id,
            AIWorkflowConfig.is_deleted == False,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_ai_workflow_config_by_module(
        self, module_code: str
    ) -> AIWorkflowConfig | None:
        """按模块代码获取 AI 工作流配置"""
        query = select(AIWorkflowConfig).where(
            AIWorkflowConfig.module_code == module_code,
            AIWorkflowConfig.is_deleted == False,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_ai_workflow_config(
        self, data: dict[str, Any]
    ) -> AIWorkflowConfig:
        """创建 AI 工作流配置"""
        item = AIWorkflowConfig(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(AIWorkflowConfig).where(AIWorkflowConfig.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_ai_workflow_config(
        self, config_id: uuid.UUID, data: dict[str, Any]
    ) -> AIWorkflowConfig | None:
        """更新 AI 工作流配置"""
        query = (
            update(AIWorkflowConfig)
            .where(
                AIWorkflowConfig.id == config_id,
                AIWorkflowConfig.is_deleted == False,
            )
            .values(**data, updated_at=func.now())
            .returning(AIWorkflowConfig)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_ai_workflow_config(self, config_id: uuid.UUID) -> bool:
        """删除 AI 工作流配置（软删除）"""
        query = (
            update(AIWorkflowConfig)
            .where(
                AIWorkflowConfig.id == config_id,
                AIWorkflowConfig.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
            SpecialOperationPersonnel.is_deleted == False
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
            SpecialOperationPersonnel.is_deleted == False
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
            SpecialOperationPersonnel.is_deleted == False,
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
                SpecialOperationPersonnel.is_deleted == False,
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
                SpecialOperationPersonnel.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
            SpecialOperationPermit.is_deleted == False
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
            SpecialOperationPermit.is_deleted == False
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
            SpecialOperationPermit.is_deleted == False,
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
                SpecialOperationPermit.is_deleted == False,
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
                SpecialOperationPermit.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
        query = select(SafetyKnowledgeArticle).where(SafetyKnowledgeArticle.is_deleted == False)

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
            )

        count_query = select(func.count(SafetyKnowledgeArticle.id)).where(
            SafetyKnowledgeArticle.is_deleted == False
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
            SafetyKnowledgeArticle.is_deleted == False,
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
                SafetyKnowledgeArticle.is_deleted == False,
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
                SafetyKnowledgeArticle.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
        query = select(SpecialOperationReport).where(SpecialOperationReport.is_deleted == False)
        count_query = select(func.count(SpecialOperationReport.id)).where(
            SpecialOperationReport.is_deleted == False
        )

        def _apply_filters(q):
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
            SpecialOperationReport.created_at.desc()
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
            SpecialOperationReport.is_deleted == False,
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
                SpecialOperationReport.is_deleted == False,
            )
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(SpecialOperationReport)
            .where(
                SpecialOperationReport.id == report_id,
                SpecialOperationReport.is_deleted == False,
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
                SpecialOperationReport.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
            SpecialOperationReport.is_deleted == False,
            SpecialOperationReport.status.in_(status_list),
        )
        count_query = select(func.count(SpecialOperationReport.id)).where(
            SpecialOperationReport.is_deleted == False,
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
            SpecialOperationReport.created_at.desc()
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_special_operation_ledger_stats(
        self, status_list: list[str] | None = None
    ) -> list[dict]:
        """按作业类型统计台账数量和关键作业数量"""
        if status_list is None:
            status_list = ["submitted", "approved"]

        query = (
            select(
                SpecialOperationReport.operation_type,
                func.count(SpecialOperationReport.id).label("count"),
                func.sum(
                    func.cast(SpecialOperationReport.is_critical, type_=func.integer())
                ).label("critical_count"),
            )
            .where(
                SpecialOperationReport.is_deleted == False,
                SpecialOperationReport.status.in_(status_list),
            )
            .group_by(SpecialOperationReport.operation_type)
            .order_by(func.count(SpecialOperationReport.id).desc())
        )
        result = await self.session.execute(query)
        return [{"operation_type": r[0], "count": r[1], "critical_count": r[2] or 0} for r in result.all()]

    # ==================== 每日风险作业报备 Operations ====================

    async def get_daily_risk_reports(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        department: str | None = None,
        report_date: datetime | None = None,
        keyword: str | None = None,
    ) -> tuple[list[DailyRiskReport], int]:
        """获取每日风险作业报备列表"""
        query = select(DailyRiskReport).where(DailyRiskReport.is_deleted == False)

        if status:
            query = query.where(DailyRiskReport.status == status)
        if department:
            query = query.where(DailyRiskReport.department == department)
        if report_date:
            query = query.where(
                func.date(DailyRiskReport.report_date) == report_date.date()
            )
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                DailyRiskReport.report_no.ilike(like)
                | DailyRiskReport.operation_description.ilike(like)
                | DailyRiskReport.department.ilike(like)
            )

        count_query = select(func.count(DailyRiskReport.id)).where(
            DailyRiskReport.is_deleted == False
        )
        if status:
            count_query = count_query.where(DailyRiskReport.status == status)
        if department:
            count_query = count_query.where(DailyRiskReport.department == department)
        if report_date:
            count_query = count_query.where(
                func.date(DailyRiskReport.report_date) == report_date.date()
            )
        if keyword:
            like = f"%{keyword}%"
            count_query = count_query.where(
                DailyRiskReport.report_no.ilike(like)
                | DailyRiskReport.operation_description.ilike(like)
                | DailyRiskReport.department.ilike(like)
            )

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(
            DailyRiskReport.report_date.desc(), DailyRiskReport.created_at.desc()
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_daily_risk_report_by_id(
        self, report_id: uuid.UUID
    ) -> DailyRiskReport | None:
        """获取每日风险作业报备详情"""
        query = select(DailyRiskReport).where(
            DailyRiskReport.id == report_id,
            DailyRiskReport.is_deleted == False,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_daily_risk_report(
        self, data: dict[str, Any]
    ) -> DailyRiskReport:
        """创建每日风险作业报备"""
        item = DailyRiskReport(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(DailyRiskReport).where(DailyRiskReport.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_daily_risk_report(
        self, report_id: uuid.UUID, data: dict[str, Any]
    ) -> DailyRiskReport | None:
        """更新每日风险作业报备"""
        query = (
            update(DailyRiskReport)
            .where(
                DailyRiskReport.id == report_id,
                DailyRiskReport.is_deleted == False,
            )
            .values(**data, updated_at=func.now())
            .returning(DailyRiskReport)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_daily_risk_report(self, report_id: uuid.UUID) -> bool:
        """删除每日风险作业报备（软删除）"""
        query = (
            update(DailyRiskReport)
            .where(
                DailyRiskReport.id == report_id,
                DailyRiskReport.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
    ) -> tuple[list[EhsChange], int]:
        """获取EHS变更列表"""
        query = select(EhsChange).where(EhsChange.is_deleted == False)
        count_query = select(func.count(EhsChange.id)).where(EhsChange.is_deleted == False)

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
        if keyword:
            keyword_filter = EhsChange.title.ilike(f"%{keyword}%")
            query = query.where(keyword_filter)
            count_query = count_query.where(keyword_filter)

        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(EhsChange.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_ehs_change_by_id(self, change_id: uuid.UUID) -> EhsChange | None:
        """获取EHS变更详情"""
        query = select(EhsChange).where(
            EhsChange.id == change_id,
            EhsChange.is_deleted == False,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_ehs_change_by_no(self, change_no: str) -> EhsChange | None:
        """根据编号获取EHS变更"""
        query = select(EhsChange).where(
            EhsChange.change_no == change_no,
            EhsChange.is_deleted == False,
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
                EhsChange.is_deleted == False,
            )
            .values(**data, updated_at=func.now())
        )
        await self.session.execute(stmt_update)
        stmt_select = (
            select(EhsChange)
            .where(
                EhsChange.id == change_id,
                EhsChange.is_deleted == False,
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
                EhsChange.is_deleted == False,
            )
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ==================== OhHazardMonitor Operations ====================

    async def get_hazard_monitors(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        detection_type: str | None = None,
        workplace: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhHazardMonitor], int]:
        """获取职业危害因素监测列表"""
        query = select(OhHazardMonitor).where(OhHazardMonitor.is_deleted == False)

        if status:
            query = query.where(OhHazardMonitor.status == status)
        if detection_type:
            query = query.where(OhHazardMonitor.detection_type == detection_type)
        if workplace:
            query = query.where(OhHazardMonitor.workplace == workplace)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                OhHazardMonitor.monitor_no.ilike(like)
                | OhHazardMonitor.workplace.ilike(like)
                | OhHazardMonitor.location.ilike(like)
            )

        count_query = select(func.count(OhHazardMonitor.id)).where(OhHazardMonitor.is_deleted == False)
        if status:
            count_query = count_query.where(OhHazardMonitor.status == status)
        if detection_type:
            count_query = count_query.where(OhHazardMonitor.detection_type == detection_type)
        if workplace:
            count_query = count_query.where(OhHazardMonitor.workplace == workplace)
        if keyword:
            count_query = count_query.where(
                OhHazardMonitor.monitor_no.ilike(like)
                | OhHazardMonitor.workplace.ilike(like)
                | OhHazardMonitor.location.ilike(like)
            )

        query = query.order_by(OhHazardMonitor.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(query)
        items = list(result.scalars().all())

        count_result = await self.session.execute(count_query)
        total = count_result.scalar() or 0

        return items, total

    async def get_hazard_monitor_by_id(self, monitor_id: uuid.UUID) -> OhHazardMonitor | None:
        """获取职业危害因素监测详情"""
        query = select(OhHazardMonitor).where(
            OhHazardMonitor.id == monitor_id, OhHazardMonitor.is_deleted == False
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_hazard_monitor_by_no(self, monitor_no: str) -> OhHazardMonitor | None:
        """按编号获取职业危害因素监测"""
        query = select(OhHazardMonitor).where(
            OhHazardMonitor.monitor_no == monitor_no, OhHazardMonitor.is_deleted == False
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_hazard_monitor(self, data: dict[str, Any]) -> OhHazardMonitor:
        """创建职业危害因素监测"""
        item = OhHazardMonitor(**data)
        self.session.add(item)
        await self.session.flush()
        stmt = select(OhHazardMonitor).where(OhHazardMonitor.id == item.id)
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def update_hazard_monitor(
        self, monitor_id: uuid.UUID, data: dict[str, Any]
    ) -> OhHazardMonitor | None:
        """更新职业危害因素监测"""
        query = (
            update(OhHazardMonitor)
            .where(OhHazardMonitor.id == monitor_id, OhHazardMonitor.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(OhHazardMonitor)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_hazard_monitor(self, monitor_id: uuid.UUID) -> bool:
        """软删除职业危害因素监测"""
        query = (
            update(OhHazardMonitor)
            .where(OhHazardMonitor.id == monitor_id, OhHazardMonitor.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ==================== OhHealthExam Operations ====================

    async def get_health_exams(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        exam_type: str | None = None,
        department: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[OhHealthExam], int]:
        """获取职业健康体检列表"""
        query = select(OhHealthExam).where(OhHealthExam.is_deleted == False)

        if status:
            query = query.where(OhHealthExam.status == status)
        if exam_type:
            query = query.where(OhHealthExam.exam_type == exam_type)
        if department:
            query = query.where(OhHealthExam.department == department)
        if keyword:
            like = f"%{keyword}%"
            query = query.where(
                OhHealthExam.exam_no.ilike(like)
                | OhHealthExam.employee_name.ilike(like)
                | OhHealthExam.department.ilike(like)
            )

        count_query = select(func.count(OhHealthExam.id)).where(OhHealthExam.is_deleted == False)
        if status:
            count_query = count_query.where(OhHealthExam.status == status)
        if exam_type:
            count_query = count_query.where(OhHealthExam.exam_type == exam_type)
        if department:
            count_query = count_query.where(OhHealthExam.department == department)
        if keyword:
            count_query = count_query.where(
                OhHealthExam.exam_no.ilike(like)
                | OhHealthExam.employee_name.ilike(like)
                | OhHealthExam.department.ilike(like)
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
            OhHealthExam.id == exam_id, OhHealthExam.is_deleted == False
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_health_exam_by_no(self, exam_no: str) -> OhHealthExam | None:
        """按编号获取职业健康体检"""
        query = select(OhHealthExam).where(
            OhHealthExam.exam_no == exam_no, OhHealthExam.is_deleted == False
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
            .where(OhHealthExam.id == exam_id, OhHealthExam.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(OhHealthExam)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_health_exam(self, exam_id: uuid.UUID) -> bool:
        """软删除职业健康体检"""
        query = (
            update(OhHealthExam)
            .where(OhHealthExam.id == exam_id, OhHealthExam.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

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
        query = select(Contractor).where(Contractor.is_deleted == False)
        count_query = select(func.count(Contractor.id)).where(Contractor.is_deleted == False)

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
            .where(Contractor.id == contractor_id, Contractor.is_deleted == False)
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
            .where(Contractor.id == contractor_id, Contractor.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(Contractor)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_contractor(self, contractor_id: uuid.UUID) -> bool:
        """删除承包商（软删除）"""
        query = (
            update(Contractor)
            .where(Contractor.id == contractor_id, Contractor.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ==================== ContractorWorkRecord Operations ====================

    async def get_work_records_by_contractor(
        self, contractor_id: uuid.UUID
    ) -> list[ContractorWorkRecord]:
        """获取承包商的施工记录列表"""
        query = select(ContractorWorkRecord).where(
            ContractorWorkRecord.contractor_id == contractor_id,
            ContractorWorkRecord.is_deleted == False,
        ).order_by(ContractorWorkRecord.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_work_record_by_id(self, record_id: uuid.UUID) -> ContractorWorkRecord | None:
        """获取施工记录详情"""
        query = select(ContractorWorkRecord).where(
            ContractorWorkRecord.id == record_id, ContractorWorkRecord.is_deleted == False
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
            .where(ContractorWorkRecord.id == record_id, ContractorWorkRecord.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(ContractorWorkRecord)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_work_record(self, record_id: uuid.UUID) -> bool:
        """删除施工记录（软删除）"""
        query = (
            update(ContractorWorkRecord)
            .where(ContractorWorkRecord.id == record_id, ContractorWorkRecord.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ==================== Scheduled Task Operations ====================

    async def get_scheduled_tasks(
        self,
        skip: int = 0,
        limit: int = 20,
        is_enabled: bool | None = None,
        search: str | None = None,
    ) -> tuple[list[ScheduledTask], int]:
        """获取定时任务列表"""
        conditions = [ScheduledTask.is_deleted == False]
        if is_enabled is not None:
            conditions.append(ScheduledTask.is_enabled == is_enabled)
        if search:
            conditions.append(ScheduledTask.name.ilike(f"%{search}%"))

        query = select(ScheduledTask).where(*conditions)
        count_query = select(func.count()).select_from(ScheduledTask).where(*conditions)
        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(ScheduledTask.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0

    async def get_scheduled_task_by_id(self, task_id: uuid.UUID) -> ScheduledTask | None:
        """获取单个定时任务"""
        query = select(ScheduledTask).where(
            ScheduledTask.id == task_id, ScheduledTask.is_deleted == False
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_due_scheduled_tasks(self) -> list[ScheduledTask]:
        """获取到期需要执行的定时任务"""
        from datetime import datetime as dt
        now = dt.now()
        query = select(ScheduledTask).where(
            ScheduledTask.is_deleted == False,
            ScheduledTask.is_enabled == True,
            ScheduledTask.next_run_at <= now,
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create_scheduled_task(self, data: dict[str, Any]) -> ScheduledTask:
        """创建定时任务"""
        item = ScheduledTask(**data)
        self.session.add(item)
        await self.session.flush()
        # eager re-fetch
        query = select(ScheduledTask).where(ScheduledTask.id == item.id)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def update_scheduled_task(
        self, task_id: uuid.UUID, data: dict[str, Any]
    ) -> ScheduledTask | None:
        """更新定时任务"""
        query = (
            update(ScheduledTask)
            .where(ScheduledTask.id == task_id, ScheduledTask.is_deleted == False)
            .values(**data, updated_at=func.now())
            .returning(ScheduledTask)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def delete_scheduled_task(self, task_id: uuid.UUID) -> bool:
        """删除定时任务（软删除）"""
        query = (
            update(ScheduledTask)
            .where(ScheduledTask.id == task_id, ScheduledTask.is_deleted == False)
            .values(is_deleted=True)
        )
        result = await self.session.execute(query)
        return result.rowcount > 0

    # ── Execution Logs ──

    async def create_task_log(self, data: dict[str, Any]) -> ScheduledTaskLog:
        """创建执行日志"""
        item = ScheduledTaskLog(**data)
        self.session.add(item)
        await self.session.flush()
        query = select(ScheduledTaskLog).where(ScheduledTaskLog.id == item.id)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def update_task_log(
        self, log_id: uuid.UUID, data: dict[str, Any]
    ) -> ScheduledTaskLog | None:
        """更新执行日志"""
        query = (
            update(ScheduledTaskLog)
            .where(ScheduledTaskLog.id == log_id)
            .values(**data, updated_at=func.now())
            .returning(ScheduledTaskLog)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_task_logs(
        self, task_id: uuid.UUID, skip: int = 0, limit: int = 20
    ) -> tuple[list[ScheduledTaskLog], int]:
        """获取任务执行日志"""
        conditions = [ScheduledTaskLog.task_id == task_id, ScheduledTaskLog.is_deleted == False]
        query = select(ScheduledTaskLog).where(*conditions)
        count_query = select(func.count()).select_from(ScheduledTaskLog).where(*conditions)
        total = await self.session.scalar(count_query)
        query = query.offset(skip).limit(limit).order_by(ScheduledTaskLog.started_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total or 0
