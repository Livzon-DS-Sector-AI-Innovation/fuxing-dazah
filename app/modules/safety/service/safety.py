"""Safety business workflows."""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.models import (
    Accident,
    Contractor,
    ContractorWorkRecord,
    SafetyCheck,
    SafetyTraining,
    TrainingRecord,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    AccidentCreate,
    AccidentUpdate,
    ContractorCreate,
    ContractorUpdate,
    ContractorWorkRecordCreate,
    ContractorWorkRecordUpdate,
    SafetyCheckCreate,
    SafetyCheckUpdate,
    SafetyTrainingCreate,
    SafetyTrainingUpdate,
    TrainingRecordCreate,
    TrainingRecordUpdate,
)
from app.modules.safety.service._helpers import audit_log
from app.platform.integrations.ai.client import AIService
from app.platform.integrations.ai.document_parser import DocumentParser
from app.platform.integrations.ai.prompts import (
    SCRIPT_CONFIG,
    build_prompt,
)

logger = logging.getLogger(__name__)

# ── AI 配置默认值（仅用于自动种子和 temperature fallback）──


class SafetyService:
    """Safety module service — delegates to per-domain sub-services.

    Sub-services are exposed as attributes for gradual migration:
        svc = SafetyService(session)
        svc.hazard.get_hazards(...)       # → HazardService
        svc.ehs.get_ehs_changes(...)      # → EhsChangeService
        svc.special_op.get_personnel(...)  # → SpecialOperationService
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

        # Per-domain sub-services (lazy init to avoid circular imports)
        self._hazard = None
        self._ehs = None
        self._regulation = None
        self._special_op = None
        self._special_op_report = None
        self._daily_risk = None
        self._oh_monitor = None
        self._oh_exam = None
        self._knowledge = None
        self._sop = None

    # ── Lazy-loading accessors for per-domain sub-services ──

    @property
    def hazard(self):
        if self._hazard is None:
            from app.modules.safety.service.hazard import HazardService
            self._hazard = HazardService(self.session)
        return self._hazard

    @property
    def ehs(self):
        if self._ehs is None:
            from app.modules.safety.service.ehs_change import EhsChangeService
            self._ehs = EhsChangeService(self.session)
        return self._ehs

    @property
    def regulation(self):
        if self._regulation is None:
            from app.modules.safety.service.regulation import RegulationService
            self._regulation = RegulationService(self.session)
        return self._regulation

    @property
    def special_op(self):
        if self._special_op is None:
            from app.modules.safety.service.special_operation import (
                SpecialOperationService,
            )
            self._special_op = SpecialOperationService(self.session)
        return self._special_op

    @property
    def special_op_report(self):
        if self._special_op_report is None:
            from app.modules.safety.service.special_operation_report import (
                SpecialOperationReportService,
            )
            self._special_op_report = SpecialOperationReportService(self.session)
        return self._special_op_report

    @property
    def daily_risk(self):
        if self._daily_risk is None:
            from app.modules.safety.service.daily_risk_report import (
                DailyRiskReportService,
            )
            self._daily_risk = DailyRiskReportService(self.session)
        return self._daily_risk

    @property
    def oh_monitor(self):
        if self._oh_monitor is None:
            from app.modules.safety.service.oh_hazard_monitor import (
                OhHazardMonitorService,
            )
            self._oh_monitor = OhHazardMonitorService(self.session)
        return self._oh_monitor

    @property
    def oh_exam(self):
        if self._oh_exam is None:
            from app.modules.safety.service.oh_health_exam import OhHealthExamService
            self._oh_exam = OhHealthExamService(self.session)
        return self._oh_exam

    @property
    def knowledge(self):
        if self._knowledge is None:
            from app.modules.safety.service.knowledge import KnowledgeService
            self._knowledge = KnowledgeService(self.session)
        return self._knowledge

    @property
    def sop(self):
        if self._sop is None:
            from app.modules.safety.service.sop_generator import SopGeneratorService
            self._sop = SopGeneratorService(self.session)
        return self._sop

    # ── Audit helper ──

    async def _audit(
        self,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await audit_log(
            self.session,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )

    @staticmethod
    def _cleanup_file(file_path: str | None) -> None:
        """Delete a single file from MinIO or local disk."""
        if not file_path:
            return
        try:
            if minio_enabled():
                try:
                    delete_object("safety", file_path)
                except Exception:
                    pass
            else:
                abs_path = os.path.abspath(file_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
        except OSError:
            pass

    @staticmethod
    def _cleanup_json_array_files(json_str: str | None) -> None:
        """Parse a JSON array of file paths and delete each file."""
        if not json_str:
            return
        try:
            paths = json.loads(json_str)
            if isinstance(paths, list):
                for p in paths:
                    if isinstance(p, str):
                        SafetyService._cleanup_file(p)
        except (json.JSONDecodeError, TypeError):
            pass

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
        return await self.repo.get_checks(skip, limit, status, check_type, department)

    async def get_check(self, check_id: uuid.UUID) -> SafetyCheck | None:
        """获取安全检查详情"""
        return await self.repo.get_check_by_id(check_id)

    async def create_check(self, data: SafetyCheckCreate) -> SafetyCheck:
        """创建安全检查"""
        check_data = data.model_dump()
        item = await self.repo.create_check(check_data)
        await self._audit("create", "safety_check", resource_id=item.id)
        return item

    async def update_check(
        self, check_id: uuid.UUID, data: SafetyCheckUpdate
    ) -> SafetyCheck | None:
        """更新安全检查"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_check(check_id, update_data)
        if item:
            await self._audit("update", "safety_check", resource_id=check_id)
        return item

    async def submit_check(self, check_id: uuid.UUID) -> SafetyCheck | None:
        """提交安全检查（草稿→已提交）"""
        check = await self.repo.get_check_by_id(check_id)
        if not check or check.status != "draft":
            return None
        item = await self.repo.update_check(check_id, {"status": "submitted"})
        if item:
            await self._audit("submit", "safety_check", resource_id=check_id)
        return item

    async def review_check(
        self, check_id: uuid.UUID, result: str
    ) -> SafetyCheck | None:
        """审核安全检查"""
        check = await self.repo.get_check_by_id(check_id)
        if not check or check.status not in ("submitted",):
            return None
        return await self.repo.update_check(
            check_id, {"status": "reviewed", "result": result}
        )

    async def close_check(self, check_id: uuid.UUID) -> SafetyCheck | None:
        """关闭安全检查"""
        check = await self.repo.get_check_by_id(check_id)
        if not check or check.status not in ("reviewed",):
            return None
        item = await self.repo.update_check(check_id, {"status": "closed"})
        if item:
            await self._audit("close", "safety_check", resource_id=check_id)
        return item

    async def confirm_check(
        self, check_id: uuid.UUID, role: str
    ) -> SafetyCheck | None:
        """确认安全检查（检查人员 / 安全办）"""
        check = await self.repo.get_check_by_id(check_id)
        if not check:
            return None
        if role == "inspector":
            return await self.repo.update_check(
                check_id, {"inspector_confirmed": True}
            )
        elif role == "safety_officer":
            return await self.repo.update_check(
                check_id, {"safety_officer_confirmed": True}
            )
        return None

    async def delete_check(self, check_id: uuid.UUID) -> bool:
        """删除安全检查"""
        result = await self.repo.delete_check(check_id)
        if result:
            await self._audit("delete", "safety_check", resource_id=check_id)
        return result

    # ==================== HazardIdentification Operations ====================

    # ── 批量危险源辨识 + 工段预览 ──

    async def create_hazard_identification_batch(self, data) -> dict:
        """批量创建危险源辨识记录（一个操规 → 多工艺阶段）。

        流程:
        1. 查询 regulation，校验 content 非空
        2. 解析 Chapter 7 → 提取工艺阶段列表
        3. 校验 stage_names ⊆ 解析结果
        4. 生成 batch_id，对每个 stage 生成 hazard_id_no + chapter7_context
        5. 批量 INSERT
        6. 可选 auto_submit
        """
        from app.modules.safety.document_parser import parse_chapter7_stages

        batch_id = uuid.uuid4()

        # 1. 查询操规
        reg = await self.repo.get_regulation_by_id(data.regulation_id)
        if not reg:
            raise ValueError(f"安全操作规程不存在: {data.regulation_id}")
        if not reg.content:
            raise ValueError(
                f"安全操作规程「{reg.regulation_name}」尚无标准化内容，"
                "请先生成操规后再创建危险源辨识"
            )

        # 2. 解析工艺阶段
        all_stages = parse_chapter7_stages(reg.content)
        if not all_stages:
            raise ValueError(
                f"安全操作规程「{reg.regulation_name}」第7章未找到工艺阶段，"
                "请确认操规包含完整的生产工艺流程（第7章应为 H2 标题的工艺阶段）"
            )

        # 3. 校验 stage_names
        valid_names = {s["stage_name"] for s in all_stages}
        for sn in data.stage_names:
            if sn not in valid_names:
                raise ValueError(
                    f"工艺阶段「{sn}」不在操规第7章中。"
                    f"可用阶段: {', '.join(sorted(valid_names))}"
                )

        # 4. 生成编号 & 构建记录
        today = datetime.now().strftime("%Y%m%d")
        existing = await self.repo.count_hi_today(today)
        seq = existing + 1

        records_data: list[dict[str, Any]] = []
        for sn in data.stage_names:
            stage_info = next(s for s in all_stages if s["stage_name"] == sn)
            records_data.append({
                "hazard_id_no": f"HI-{today}-{seq:03d}",
                "department": data.department,
                "position": data.position,
                "production_step": sn,
                "regulation_id": data.regulation_id,
                "regulation_name": reg.regulation_name,
                "batch_id": batch_id,
                "stage_name": sn,
                "chapter7_context": stage_info["markdown"],
                "notes": data.notes,
                "ai_node_progress": "pending_input",
                "overall_status": "draft",
            })
            seq += 1

        # 5. 批量 INSERT
        items = await self.repo.create_hazard_identifications_batch(records_data)
        logger.info(
            "批量创建危险源辨识: batch_id=%s, regulation=%s, stages=%d",
            batch_id, reg.regulation_name, len(items),
        )
        await self._audit("create_batch", "hazard_identification", resource_id=batch_id)

        # 6. 可选自动提交
        if data.auto_submit:
            for item in items:
                await self.repo.update_hazard_identification(
                    item.id,
                    {"ai_node_progress": "pending_script1", "overall_status": "in_progress"},
                )

        from app.modules.safety.schemas.hazard_identifications import (
            HazardIdentificationResponse,
        )
        return {
            "batch_id": str(batch_id),
            "regulation_id": str(data.regulation_id),
            "regulation_name": reg.regulation_name,
            "records": [HazardIdentificationResponse.model_validate(r) for r in items],
            "total_stages": len(all_stages),
            "created_count": len(items),
        }

    async def get_regulation_stages(self, regulation_id: uuid.UUID) -> dict | None:
        """获取操规 Chapter 7 的工艺阶段列表（供前端批量辨识预览）。"""
        from app.modules.safety.document_parser import parse_chapter7_stages

        reg = await self.repo.get_regulation_by_id(regulation_id)
        if not reg or not reg.content:
            return None

        all_stages = parse_chapter7_stages(reg.content)
        if not all_stages:
            return None

        return {
            "regulation_id": str(regulation_id),
            "regulation_name": reg.regulation_name,
            "stages": [
                {
                    "stage_name": s["stage_name"],
                    "safety_count": len(s["safety_items"]),
                    "operation_count": len(s["operation_items"]),
                }
                for s in all_stages
            ],
        }

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
        return await self.repo.get_accidents(
            skip, limit, status, accident_type, accident_level,
            department, date_from, date_to, keyword,
        )

    async def get_accident(self, accident_id: uuid.UUID) -> Accident | None:
        """获取事故详情"""
        return await self.repo.get_accident_by_id(accident_id)

    async def create_accident(self, data: AccidentCreate) -> Accident:
        """创建事故"""
        accident_data = data.model_dump()
        item = await self.repo.create_accident(accident_data)
        await self._audit("create", "accident", resource_id=item.id)
        return item

    async def update_accident(
        self, accident_id: uuid.UUID, data: AccidentUpdate
    ) -> Accident | None:
        """更新事故"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_accident(accident_id, update_data)
        if item:
            await self._audit("update", "accident", resource_id=accident_id)
        return item

    async def investigate_accident(
        self,
        accident_id: uuid.UUID,
        investigator: uuid.UUID,
        investigator_name: str,
    ) -> Accident | None:
        """开始调查事故"""
        accident = await self.repo.get_accident_by_id(accident_id)
        if not accident or accident.status != "reported":
            return None
        return await self.repo.update_accident(
            accident_id,
            {
                "status": "investigating",
                "investigator": investigator,
                "investigator_name": investigator_name,
            },
        )

    async def resolve_accident(
        self,
        accident_id: uuid.UUID,
        direct_cause: str,
        root_cause: str,
        handling_measures: str,
        corrective_actions: str | None = None,
        investigation_findings: str | None = None,
        investigation_method: str | None = None,
        investigation_team: list | None = None,
    ) -> Accident | None:
        """完成调查事故"""
        accident = await self.repo.get_accident_by_id(accident_id)
        if not accident or accident.status != "investigating":
            return None
        update_data: dict[str, Any] = {
            "status": "investigated",
            "direct_cause": direct_cause,
            "root_cause": root_cause,
            "handling_measures": handling_measures,
            "corrective_actions": corrective_actions,
            "investigation_findings": investigation_findings,
            "investigation_method": investigation_method,
        }
        if investigation_team is not None:
            update_data["investigation_team"] = investigation_team
        return await self.repo.update_accident(accident_id, update_data)

    async def start_capa(
        self,
        accident_id: uuid.UUID,
        corrective_action_deadline: datetime,
        corrective_action_responsible: str,
    ) -> Accident | None:
        """启动 CAPA"""
        accident = await self.repo.get_accident_by_id(accident_id)
        if not accident or accident.status != "investigated":
            return None
        return await self.repo.update_accident(
            accident_id,
            {
                "status": "capa_in_progress",
                "corrective_action_deadline": corrective_action_deadline,
                "corrective_action_responsible": corrective_action_responsible,
                "corrective_action_status": "in_progress",
            },
        )

    async def verify_capa(
        self,
        accident_id: uuid.UUID,
        verified_by: uuid.UUID,
        verified_by_name: str,
    ) -> Accident | None:
        """验证 CAPA 并关闭事故"""
        accident = await self.repo.get_accident_by_id(accident_id)
        if not accident or accident.status != "capa_in_progress":
            return None
        return await self.repo.update_accident(
            accident_id,
            {
                "status": "closed",
                "corrective_action_status": "verified",
                "verified_by": verified_by,
                "verified_by_name": verified_by_name,
                "verified_at": datetime.now(),
            },
        )

    async def close_accident(self, accident_id: uuid.UUID) -> Accident | None:
        """直接关闭事故（无CAPA时）"""
        accident = await self.repo.get_accident_by_id(accident_id)
        if not accident or accident.status != "investigated":
            return None
        return await self.repo.update_accident(accident_id, {"status": "closed"})

    async def delete_accident(self, accident_id: uuid.UUID) -> bool:
        """删除事故"""
        accident = await self.repo.get_accident_by_id(accident_id)
        result = await self.repo.delete_accident(accident_id)
        if result:
            if accident:
                self._cleanup_file(accident.investigation_report_path)
            await self._audit("delete", "accident", resource_id=accident_id)
        return result

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
        return await self.repo.get_contractors(
            skip, limit, status, qualification_type, training_status, keyword,
        )

    async def get_contractor(self, contractor_id: uuid.UUID) -> Contractor | None:
        """获取承包商详情"""
        return await self.repo.get_contractor_by_id(contractor_id)

    async def create_contractor(self, data: "ContractorCreate") -> Contractor:
        """创建承包商"""
        contractor_data = data.model_dump()
        item = await self.repo.create_contractor(contractor_data)
        await self._audit("create", "contractor", resource_id=item.id)
        return item

    async def update_contractor(
        self, contractor_id: uuid.UUID, data: "ContractorUpdate"
    ) -> Contractor | None:
        """更新承包商"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_contractor(contractor_id, update_data)
        if item:
            await self._audit("update", "contractor", resource_id=contractor_id)
        return item

    async def blacklist_contractor(self, contractor_id: uuid.UUID) -> Contractor | None:
        """将承包商加入黑名单"""
        contractor = await self.repo.get_contractor_by_id(contractor_id)
        if not contractor:
            return None
        return await self.repo.update_contractor(
            contractor_id, {"status": "blacklisted", "blacklisted": True}
        )

    async def activate_contractor(self, contractor_id: uuid.UUID) -> Contractor | None:
        """激活承包商"""
        contractor = await self.repo.get_contractor_by_id(contractor_id)
        if not contractor:
            return None
        return await self.repo.update_contractor(
            contractor_id, {"status": "active", "blacklisted": False}
        )

    async def update_contractor_training(
        self, contractor_id: uuid.UUID, training_status: str
    ) -> Contractor | None:
        """更新承包商培训状态"""
        contractor = await self.repo.get_contractor_by_id(contractor_id)
        if not contractor:
            return None
        return await self.repo.update_contractor(
            contractor_id,
            {
                "training_status": training_status,
                "training_date": datetime.now(),
            },
        )

    async def delete_contractor(self, contractor_id: uuid.UUID) -> bool:
        """删除承包商"""
        result = await self.repo.delete_contractor(contractor_id)
        if result:
            await self._audit("delete", "contractor", resource_id=contractor_id)
        return result

    # ── 施工记录 ──

    async def get_work_records(
        self, contractor_id: uuid.UUID
    ) -> list[ContractorWorkRecord]:
        """获取承包商的施工记录"""
        return await self.repo.get_work_records_by_contractor(contractor_id)

    async def create_work_record(
        self, contractor_id: uuid.UUID, data: "ContractorWorkRecordCreate"
    ) -> ContractorWorkRecord:
        """创建施工记录"""
        record_data = data.model_dump()
        record_data["contractor_id"] = str(contractor_id)
        return await self.repo.create_work_record(record_data)

    async def update_work_record(
        self, record_id: uuid.UUID, data: "ContractorWorkRecordUpdate"
    ) -> ContractorWorkRecord | None:
        """更新施工记录"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        return await self.repo.update_work_record(record_id, update_data)

    async def evaluate_work_record(
        self, record_id: uuid.UUID, score: int, comments: str | None = None,
        evaluator: str | None = None,
    ) -> ContractorWorkRecord | None:
        """评价施工记录"""
        record = await self.repo.get_work_record_by_id(record_id)
        if not record:
            return None
        return await self.repo.update_work_record(
            record_id,
            {
                "status": "evaluated",
                "evaluation": {
                    "score": score,
                    "comments": comments,
                    "evaluator": evaluator,
                    "date": datetime.now().isoformat(),
                },
            },
        )

    async def delete_work_record(self, record_id: uuid.UUID) -> bool:
        """删除施工记录"""
        return await self.repo.delete_work_record(record_id)

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
        return await self.repo.get_trainings(skip, limit, status, training_type, department)

    async def get_training(self, training_id: uuid.UUID) -> SafetyTraining | None:
        """获取安全培训详情"""
        return await self.repo.get_training_by_id(training_id)

    async def create_training(self, data: SafetyTrainingCreate) -> SafetyTraining:
        """创建安全培训"""
        training_data = data.model_dump()
        item = await self.repo.create_training(training_data)
        await self._audit("create", "safety_training", resource_id=item.id)
        return item

    async def update_training(
        self, training_id: uuid.UUID, data: SafetyTrainingUpdate
    ) -> SafetyTraining | None:
        """更新安全培训"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_training(training_id, update_data)
        if item:
            await self._audit("update", "safety_training", resource_id=training_id)
        return item

    async def start_training(self, training_id: uuid.UUID) -> SafetyTraining | None:
        """开始培训（草稿→进行中）"""
        training = await self.repo.get_training_by_id(training_id)
        if not training or training.status != "draft":
            return None
        return await self.repo.update_training(training_id, {"status": "in_progress"})

    async def complete_training(self, training_id: uuid.UUID) -> SafetyTraining | None:
        """完成培训"""
        training = await self.repo.get_training_by_id(training_id)
        if not training or training.status != "in_progress":
            return None
        return await self.repo.update_training(training_id, {"status": "completed"})

    async def archive_training(self, training_id: uuid.UUID) -> SafetyTraining | None:
        """归档培训"""
        training = await self.repo.get_training_by_id(training_id)
        if not training or training.status != "completed":
            return None
        return await self.repo.update_training(training_id, {"status": "archived"})

    async def delete_training(self, training_id: uuid.UUID) -> bool:
        """删除安全培训"""
        training = await self.repo.get_training_by_id(training_id)
        result = await self.repo.delete_training(training_id)
        if result:
            if training:
                self._cleanup_file(training.course_material_path)
            await self._audit("delete", "safety_training", resource_id=training_id)
        return result

    # ==================== TrainingRecord Operations ====================

    async def get_training_records(self, training_id: uuid.UUID) -> list[TrainingRecord]:
        """获取培训记录列表"""
        return await self.repo.get_records_by_training(training_id)

    async def create_training_record(self, data: TrainingRecordCreate) -> TrainingRecord:
        """创建培训记录"""
        record_data = data.model_dump()
        return await self.repo.create_training_record(record_data)

    async def update_training_record(
        self, record_id: uuid.UUID, data: TrainingRecordUpdate
    ) -> TrainingRecord | None:
        """更新培训记录"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        return await self.repo.update_training_record(record_id, update_data)

    async def batch_create_records(
        self, training_id: uuid.UUID, records: list[TrainingRecordCreate]
    ) -> list[TrainingRecord]:
        """批量创建培训签到记录"""
        result = []
        for record in records:
            record_data = record.model_dump()
            record_data["training_id"] = training_id
            item = await self.repo.create_training_record(record_data)
            result.append(item)
        return result

    async def delete_training_record(self, record_id: uuid.UUID) -> bool:
        """删除培训记录"""
        return await self.repo.delete_training_record(record_id)

    # ── 培训证书 ──

    async def get_training_certificates(
        self,
        skip: int = 0,
        limit: int = 20,
        certificate_status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[TrainingRecord], int]:
        """获取培训证书列表"""
        return await self.repo.get_training_certificates(
            skip, limit, certificate_status, keyword,
        )

    async def get_expiring_certificates(self) -> list[TrainingRecord]:
        """获取即将过期的证书（30天内）"""
        return await self.repo.get_expiring_certificates()

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
    ) -> tuple[list, int]:
        """获取危险源辨识列表"""
        return await self.repo.get_hazard_identifications(
            skip, limit, department, overall_status, ai_node_progress, keyword,
            position, risk_level, date_from, date_to, batch_id,
        )

    async def get_hazard_identification_stats(self) -> dict[str, int]:
        """获取危险源辨识工作流统计"""
        return await self.repo.get_hazard_identification_stats()

    async def get_hazard_identification_ledger_stats(
        self,
        department: str | None = None,
        position: str | None = None,
        risk_level: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, int]:
        """获取危险源辨识台账统计"""
        return await self.repo.get_hazard_identification_ledger_stats(
            department, position, risk_level, date_from, date_to,
        )

    async def get_hazard_identification(self, hid: uuid.UUID):
        """获取危险源辨识详情"""
        return await self.repo.get_hazard_identification_by_id(hid)

    async def create_hazard_identification(self, data) -> Any:
        """创建危险源辨识记录（hazard_id_no 留空时自动生成 HI-年月日-序号）"""

        create_data = data.model_dump(exclude_none=True)
        if not create_data.get("hazard_id_no"):
            today = datetime.now().strftime("%Y%m%d")
            existing = await self.repo.count_hi_today(today)
            create_data["hazard_id_no"] = f"HI-{today}-{existing + 1:03d}"
        # production_step 已取消输入，设默认值以兼容 DB NOT NULL 约束
        create_data.setdefault("production_step", "")
        # 引用安全操作规程：从 regulation_id 回填 regulation_name
        if create_data.get("regulation_id") and not create_data.get("regulation_name"):
            reg = await self.repo.get_regulation_by_id(create_data["regulation_id"])
            if reg:
                create_data["regulation_name"] = reg.regulation_name
        create_data["ai_node_progress"] = "pending_input"
        create_data["overall_status"] = "draft"
        item = await self.repo.create_hazard_identification(create_data)
        await self._audit("create", "hazard_identification", resource_id=item.id)
        return item



    async def update_hazard_identification(self, hid: uuid.UUID, data) -> Any | None:
        """更新危险源辨识"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        item = await self.repo.update_hazard_identification(hid, update_data)
        if item:
            await self._audit("update", "hazard_identification", resource_id=hid)
        return item

    async def delete_hazard_identification(self, hid: uuid.UUID) -> bool:
        """删除危险源辨识"""
        hi = await self.repo.get_hazard_identification_by_id(hid)
        result = await self.repo.delete_hazard_identification(hid)
        if result:
            if hi:
                self._cleanup_file(hi.attachment_path)
            await self._audit("delete", "hazard_identification", resource_id=hid)
        return result

    async def submit_hazard_identification(self, hid: uuid.UUID) -> Any | None:
        """提交基础信息 → 进入脚本1（待AI解析附件）"""
        item = await self.repo.get_hazard_identification_by_id(hid)
        if not item or item.overall_status not in ("draft",):
            return None
        return await self.repo.update_hazard_identification(
            hid, {"ai_node_progress": "pending_script1", "overall_status": "in_progress"}
        )

    # ── 工作流状态机 ──

    SCRIPT_NODE_MAP = {
        1: ("pending_script1", "pending_script2", "script1_review_status"),
        2: ("pending_script2", "pending_script3", "script2_review_status"),
        3: ("pending_script3", "pending_script4", "script3_review_status"),
        4: ("pending_script4", "pending_script5", "script4_review_status"),
        5: ("pending_script5", "pending_script6", "script5_review_status"),
        6: ("pending_script6", "pending_script7", "script6_review_status"),
        7: ("pending_script7", "completed", "script7_review_status"),
    }

    # ── AI 集成 ──

    async def _get_ai_service(self) -> AIService:
        """获取文本模型 AIService（硬编码配置）"""
        from app.modules.safety.service.config import create_ai_service
        return create_ai_service("text")

    async def _get_vision_ai_service(self) -> AIService:
        """获取视觉模型 AIService（硬编码配置）"""
        from app.modules.safety.service.config import create_ai_service
        return create_ai_service("vision")

    def _build_context(self, script_number: int, item: Any) -> str:
        """从当前记录构建供 AI 使用的上下文字符串"""
        parts: list[str] = [
            f"部门：{item.department or '未知'}",
            f"岗位：{item.position or '未知'}",
            f"生产步骤：{item.production_step or '未知'}",
        ]

        # Script 1 基础字段
        if script_number >= 1:
            if item.specific_activity:
                parts.append(f"具体作业活动：{item.specific_activity}")
            if item.equipment_facilities:
                parts.append(f"设备设施：{item.equipment_facilities}")
            if item.raw_auxiliary_materials:
                parts.append(f"原辅料：{item.raw_auxiliary_materials}")
            if item.operation_frequency:
                parts.append(f"作业频次：{item.operation_frequency}")
            if item.operator_count is not None:
                parts.append(f"操作人数：{item.operator_count}")

        # Script 2 输出
        if script_number >= 3:
            if item.hazard_type:
                parts.append(f"危险类型：{item.hazard_type}")
            if item.possible_accident:
                parts.append(f"可能导致事故：{item.possible_accident}")
            if item.unsafe_behavior:
                parts.append(f"不规范作业行为表现：{item.unsafe_behavior}")

        # Script 3 输出
        if script_number >= 4:
            if item.l_inherent is not None:
                parts.append(f"可能性 L（固有）：{item.l_inherent}")
            if item.e_inherent is not None:
                parts.append(f"暴露频率 E（固有）：{item.e_inherent}")
            if item.c_inherent is not None:
                parts.append(f"严重性 C（固有）：{item.c_inherent}")
            if item.d_inherent is not None:
                parts.append(f"风险值 D（固有）：{item.d_inherent}")
            if item.inherent_risk_label:
                parts.append(f"固有风险等级：{item.inherent_risk_label}")

        # Script 4 输出
        if script_number >= 5:
            if item.existing_engineering_controls:
                parts.append(f"现有工程控制措施：{item.existing_engineering_controls}")
            if item.existing_management_controls:
                parts.append(f"现有管理控制措施：{item.existing_management_controls}")
            if item.existing_ppe:
                parts.append(f"现有个人防护措施：{item.existing_ppe}")
            if item.existing_emergency_measures:
                parts.append(f"现有应急措施：{item.existing_emergency_measures}")

        # Script 5 输出
        if script_number >= 6:
            if item.l_residual is not None:
                parts.append(f"可能性 L（残余）：{item.l_residual}")
            if item.e_residual is not None:
                parts.append(f"暴露频率 E（残余）：{item.e_residual}")
            if item.c_residual is not None:
                parts.append(f"严重性 C（残余）：{item.c_residual}")
            if item.d_residual is not None:
                parts.append(f"风险值 D（残余）：{item.d_residual}")
            if item.residual_risk_label:
                parts.append(f"残余风险等级：{item.residual_risk_label}")
            if item.control_level:
                parts.append(f"管控等级：{item.control_level}")

        # Script 6 输出
        if script_number >= 7:
            if item.recommendation_content:
                parts.append(f"建议措施内容：{item.recommendation_content}")
            if item.recommendation_type:
                parts.append(f"建议措施类型：{item.recommendation_type}")

        return "\n".join(parts)

    async def _generate_ai_output(
        self, script_number: int, item: Any
    ) -> dict:
        """[DEPRECATED v2.0] 调用 AI 服务生成工作流输出。

        已由 HazardIdentificationOrchestrator + 7 个独立 Plugin 替代。
        保留此方法作为 fallback，新代码请使用 Orchestrator。
        直接使用硬编码 SCRIPT_CONFIG。
        """
        config = SCRIPT_CONFIG[script_number]
        prompt_template = build_prompt(config)
        expected_keys = config["expected_keys"]
        logger.debug("使用硬编码工作流配置步骤 %d", script_number)

        context_text = self._build_context(script_number, item)

        # Script 1 特殊处理：解析附件
        if script_number == 1:
            attachment_text = ""
            if item.attachment_path:
                try:
                    attachment_text = DocumentParser.extract_text(
                        item.attachment_path, max_chars=30000
                    )
                except Exception as e:
                    logger.warning(f"附件解析失败: {e}")
            if attachment_text:
                context_text += f"\n\n### 附件文档内容\n{attachment_text}"
            else:
                context_text += "\n\n### 附件文档内容\n（未上传附件或附件无法解析）"

        # 使用 replace 而非 format()，避免 AI 输出示例中的花括号被误解析
        if '{context}' in prompt_template:
            prompt = prompt_template.replace('{context}', context_text)
        else:
            prompt = f"## 上下文信息\n{context_text}\n\n{prompt_template}"
        messages = [
            {"role": "system", "content": "你是一个专业的危险源辨识与风险评价专家助手，服务于原料药生产企业。"},
            {"role": "user", "content": prompt},
        ]

        ai_service = await self._get_ai_service()
        try:
            result = await ai_service.chat_parsed(
                messages=messages,
                expected_keys=expected_keys,
            )
            return result
        finally:
            await ai_service.close()

    async def run_script(
        self, hid: uuid.UUID, script_number: int, ai_output: dict | None = None
    ) -> Any | None:
        """执行 AI 脚本（状态机推进）。

        v2.0 重构：使用 HazardIdentificationOrchestrator 调用 7 个独立 Plugin。
        每个 Plugin 继承 BasePlugin 的 4-phase pipeline（对标 AIHazardIdentifier）。
        旧 _generate_ai_output() 保留为 fallback。
        """

        item = await self.repo.get_hazard_identification_by_id(hid)
        if not item:
            return None

        if script_number not in self.SCRIPT_NODE_MAP:
            return None

        current_node, next_node, review_field = self.SCRIPT_NODE_MAP[script_number]

        # 状态校验：当前节点必须匹配
        if item.ai_node_progress != current_node:
            return None

        # 前置审核校验（脚本2-7：上一步必须已审核通过）
        if script_number > 1:
            prev_review = getattr(item, f"script{script_number - 1}_review_status")
            if prev_review != "approved":
                return None

        # [增强] 关键字段非空校验（按标准文件要求）
        if not self._validate_prerequisites(item, script_number):
            return None

        update_data: dict[str, Any] = {}

        # ── 人工覆盖模式（demo / 手动填入）──
        if ai_output is not None:
            self._map_ai_output(script_number, ai_output, update_data)
            self._calculate_risk_levels(script_number, update_data)
            update_data["ai_node_progress"] = next_node
            update_data["ai_error_message"] = None
        else:
            # ── 方案B: 使用 Orchestrator 调用 Plugin ──
            try:
                from app.modules.safety.ai_hazard_identification.orchestrator import (
                    HazardIdentificationOrchestrator,
                    OrchestratorError,
                )
                from app.modules.safety.ai_hazard_identification.schemas import (
                    PluginConfig,
                )

                ai_service = await self._get_ai_service()

                orchestrator = HazardIdentificationOrchestrator(
                    ai_service,
                    session=self.db,
                    config=PluginConfig(temperature=0.05),
                )
                plugin_update = await orchestrator.run_script(item, script_number)
                update_data.update(plugin_update)

            except OrchestratorError as e:
                logger.error("脚本 %d Orchestrator 执行失败: %s", script_number, e)
                update_data[f"script{script_number}_review_status"] = "rejected"
                update_data["ai_error_message"] = str(e)
            except Exception as e:
                logger.error("脚本 %d 执行异常: %s", script_number, e)
                update_data[f"script{script_number}_review_status"] = "rejected"
                update_data["ai_error_message"] = f"AI 服务调用失败：{e}"
            finally:
                await ai_service.close()

        result = await self.repo.update_hazard_identification(hid, update_data)
        return result

    @staticmethod
    def _validate_prerequisites(item: Any, script_number: int) -> bool:
        """校验关键前置字段非空（增强触发条件）。

        参照标准文件：每步 AI 执行前，关键人工确认字段不能为空
        且不能为「待人工确认」。

        Returns:
            True 表示前置条件满足，False 表示阻断。
        """
        UNCONFIRMED = "待人工确认"

        checks: dict[int, list[tuple[str, str]]] = {
            1: [
                ("department", "部门"), ("position", "岗位"),
                ("production_step", "生产步骤"),
            ],
            2: [
                ("specific_activity", "具体作业活动"),
                ("equipment_facilities", "设备设施"),
                ("raw_auxiliary_materials", "原辅料"),
            ],
            3: [
                ("hazard_type", "危险类型"),
                ("possible_accident", "可能导致事故"),
                ("unsafe_behavior", "不规范作业行为表现"),
            ],
            4: [
                ("l_inherent", "可能性L（固有）"),
                ("e_inherent", "暴露频率E（固有）"),
                ("c_inherent", "严重性C（固有）"),
            ],
            5: [
                ("existing_engineering_controls", "现有工程控制措施"),
                ("existing_management_controls", "现有管理控制措施"),
                ("existing_ppe", "现有个人防护措施"),
                ("existing_emergency_measures", "现有应急措施"),
            ],
            6: [
                ("l_residual", "可能性L（残余）"),
                ("e_residual", "暴露频率E（残余）"),
                ("c_residual", "严重性C（残余）"),
            ],
            7: [
                ("recommendation_content", "建议措施内容"),
            ],
        }

        for field, label in checks.get(script_number, []):
            value = getattr(item, field, None)
            if value is None or (
                isinstance(value, str) and value.strip() in ("", UNCONFIRMED)
            ):
                logger.warning(
                    "脚本%d前置校验失败: %s 为空或待人工确认", script_number, label
                )
                return False
        return True

    async def review_script(
        self, hid: uuid.UUID, script_number: int, action: str
    ) -> Any | None:
        """审核确认或驳回脚本输出"""
        item = await self.repo.get_hazard_identification_by_id(hid)
        if not item:
            return None

        if script_number not in self.SCRIPT_NODE_MAP:
            return None

        current_node, next_node, review_field = self.SCRIPT_NODE_MAP[script_number]

        # Current node must match
        expected_current = current_node if action == "approved" else current_node

        update_data: dict[str, Any] = {
            f"script{script_number}_review_status": action,
        }

        if action == "approved":
            update_data["ai_node_progress"] = next_node

        # 当完成脚本7审核 → overall_status = completed
        if action == "approved" and script_number == 7:
            update_data["overall_status"] = "completed"
        elif action == "rejected":
            # 驳回：回退到之前节点，允许重新生成
            update_data["ai_node_progress"] = current_node

        result = await self.repo.update_hazard_identification(hid, update_data)
        return result

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        """将 AI 输出值转为 float；若为'待人工确认'等非数值字符串则返回 None"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "待人工确认":
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None

    def _map_ai_output(
        self, script_number: int, ai_output: dict, update_data: dict[str, Any]
    ) -> None:
        """将 AI 输出映射到模型字段。

        - 脚本1：仅输出 3 个字段（标准文件规定）
        - 脚本3/5/7：AI 同时输出 L/E/C/D 值和风险等级；若为"待人工确认"则存 None
        - 脚本6：needs_recommendation 为字符串三态（是/否/待人工确认）
        """
        if script_number == 1:
            for f in ("specific_activity", "equipment_facilities", "raw_auxiliary_materials"):
                if f in ai_output:
                    update_data[f] = ai_output[f]

        elif script_number == 2:
            for f in ("hazard_type", "possible_accident", "unsafe_behavior"):
                if f in ai_output:
                    update_data[f] = ai_output[f]

        elif script_number == 3:
            for f in ("l_inherent", "e_inherent", "c_inherent"):
                if f in ai_output:
                    update_data[f] = self._safe_float(ai_output[f])
            # AI 直接输出 D 值和风险等级
            if "d_inherent" in ai_output:
                update_data["d_inherent"] = self._safe_float(ai_output["d_inherent"])
            if "inherent_risk_level" in ai_output:
                update_data["inherent_risk_level"] = ai_output["inherent_risk_level"]

        elif script_number == 4:
            for f in ("existing_engineering_controls", "existing_management_controls",
                      "existing_ppe", "existing_emergency_measures"):
                if f in ai_output:
                    update_data[f] = ai_output[f]

        elif script_number == 5:
            for f in ("l_residual", "e_residual", "c_residual"):
                if f in ai_output:
                    update_data[f] = self._safe_float(ai_output[f])
            if "d_residual" in ai_output:
                update_data["d_residual"] = self._safe_float(ai_output["d_residual"])
            if "residual_risk_level" in ai_output:
                update_data["residual_risk_level"] = ai_output["residual_risk_level"]

        elif script_number == 6:
            for f in ("needs_recommendation", "recommendation_type",
                      "recommendation_content", "recommendation_priority"):
                if f in ai_output:
                    update_data[f] = ai_output[f]

        elif script_number == 7:
            for f in ("l_post", "e_post", "c_post"):
                if f in ai_output:
                    update_data[f] = self._safe_float(ai_output[f])
            if "d_post" in ai_output:
                update_data["d_post"] = self._safe_float(ai_output["d_post"])
            if "post_risk_level" in ai_output:
                update_data["post_risk_level"] = ai_output["post_risk_level"]

    def _calculate_risk_levels(
        self, script_number: int, update_data: dict[str, Any]
    ) -> None:
        """补全风险等级和管控信息。

        AI 在脚本3/5/7中直接输出 D 值和风险等级；此处仅在后端可计算且 AI
        未提供对应字段时做兜底计算，同时补充 label、control_level 等展示字段。
        """
        from app.modules.safety.schemas import RISK_LEVELS, get_risk_level

        if script_number == 3:
            l = update_data.get("l_inherent")
            e = update_data.get("e_inherent")
            c = update_data.get("c_inherent")
            if all(v is not None for v in (l, e, c)):
                # D 值：优先用 AI 输出，否则后端计算
                if update_data.get("d_inherent") is None:
                    update_data["d_inherent"] = l * e * c
                # 风险等级 key：优先用 AI 输出
                if update_data.get("inherent_risk_level") is None:
                    level = get_risk_level(update_data["d_inherent"])
                    update_data["inherent_risk_level"] = level["key"]
                # 补充 label / control_level / responsible_person（后端计算）
                for rl in RISK_LEVELS:
                    if rl["key"] == update_data.get("inherent_risk_level"):
                        update_data["inherent_risk_label"] = rl["label"]
                        update_data["control_level"] = rl["control_level"]
                        update_data["responsible_person"] = rl["responsible_person"]
                        break

        elif script_number == 5:
            l = update_data.get("l_residual")
            e = update_data.get("e_residual")
            c = update_data.get("c_residual")
            if all(v is not None for v in (l, e, c)):
                if update_data.get("d_residual") is None:
                    update_data["d_residual"] = l * e * c
                if update_data.get("residual_risk_level") is None:
                    level = get_risk_level(update_data["d_residual"])
                    update_data["residual_risk_level"] = level["key"]
                for rl in RISK_LEVELS:
                    if rl["key"] == update_data.get("residual_risk_level"):
                        update_data["residual_risk_label"] = rl["label"]
                        break

        elif script_number == 7:
            l = update_data.get("l_post")
            e = update_data.get("e_post")
            c = update_data.get("c_post")
            if all(v is not None for v in (l, e, c)):
                if update_data.get("d_post") is None:
                    update_data["d_post"] = l * e * c
                if update_data.get("post_risk_level") is None:
                    level = get_risk_level(update_data["post_risk_level"])
                    update_data["post_risk_level"] = level["key"]
                for rl in RISK_LEVELS:
                    if rl["key"] == update_data.get("post_risk_level"):
                        update_data["post_risk_label"] = rl["label"]
                        break

    # ==================== 附件上传 ====================

    async def upload_attachment(
        self, hid: uuid.UUID, file_name: str, file_path: str
    ) -> Any | None:
        """保存附件路径到记录"""
        return await self.repo.update_hazard_identification(
            hid,
            {
                "attachment_path": file_path,
                "attachment_original_name": file_name,
            },
        )

    # ── AI 导出 ──

    async def parse_hazard_export_query(self, natural_query: str) -> dict:
        """使用 AI 将自然语言筛选条件解析为结构化参数。

        支持的自然语言示例：
        - 「导出所有重大危险源」
        - 「原料药车间上月的记录」
        - 「合成岗位最近三个月一级和二级风险」
        """
        system_prompt = (
            "你是一个数据库查询助手，负责将用户的中文自然语言查询 "
            "转换为危险源辨识台账的结构化筛选条件。\n\n"
            "可用字段：\n"
            "- department: 部门名称（如「原料药车间」「生产部」）\n"
            "- position: 岗位名称（如「操作工」「合成岗位」）\n"
            "- risk_level: 风险等级（level_1/level_2/level_3/level_4）\n"
            "- date_from / date_to: 日期范围 YYYY-MM-DD\n"
            "- keyword: 关键词搜索（编号/部门/岗位/作业活动）\n\n"
            "只返回 JSON，不要任何其他文字。没有匹配的字段不返回。\n"
            '示例输出: {"department":"原料药车间","risk_level":"level_1"}'
        )
        try:
            ai = await self._get_ai_service()
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": natural_query},
            ]
            response_text = await ai.chat(messages, response_format="json_object")
            result = json.loads(response_text)
            return {k: v for k, v in result.items() if v is not None}
        except Exception as e:
            logger.warning("AI 自然语言解析失败(hazard-identification): %s", e)
            return {
                "explanation": f"AI 解析失败，将使用原始查询: {natural_query}",
                "keyword": natural_query,
            }

    async def export_hazard_ledger_pdf(
        self,
        natural_query: str | None = None,
        department: str | None = None,
        position: str | None = None,
        risk_level: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        keyword: str | None = None,
    ) -> bytes:
        """导出危险源辨识台账为 PDF。

        流程：
        1. AI 解析自然语言 → 筛选条件（如「导出所有重大危险源」）
        2. 按条件查询数据库
        3. Excel 标准化输出插件填表 → LibreOffice 转 PDF
        4. 回退：reportlab 固定模板
        """
        # 第一阶段：AI 解析自然语言 → 筛选条件
        if natural_query:
            parsed = await self.parse_hazard_export_query(natural_query)
            department = department or parsed.get("department")
            position = position or parsed.get("position")
            risk_level = risk_level or parsed.get("risk_level")
            date_from = date_from or parsed.get("date_from")
            date_to = date_to or parsed.get("date_to")
            keyword = keyword or parsed.get("keyword")

        # 第二阶段：按条件查询数据
        items, _ = await self.repo.get_hazard_identifications(
            skip=0,
            limit=10000,
            department=department,
            overall_status="completed",
            position=position,
            risk_level=risk_level,
            date_from=date_from,
            date_to=date_to,
            keyword=keyword,
        )

        filters = {
            k: v for k, v in {
                "department": department, "position": position,
                "risk_level": risk_level, "date_from": date_from,
                "date_to": date_to, "keyword": keyword,
            }.items() if v is not None
        }

        # ── 策略 1：Excel 标准化输出（最高优先级）──
        try:
            pdf_bytes = self._export_via_template_plugin(items, filters)
            if pdf_bytes and len(pdf_bytes) > 5000:
                logger.info("Excel标准化输出导出成功: %d records, %d bytes",
                            len(items), len(pdf_bytes))
                return pdf_bytes
        except Exception as exc:
            logger.warning("Excel标准化输出导出失败: %s，回退到固定模板", exc)

        # ── 回退：reportlab 固定模板 ──
        logger.debug("使用 reportlab 固定模板生成 PDF")
        return await self._export_hazard_ledger_pdf_fallback(items, filters)

    def _export_via_template_plugin(self, items, filters: dict) -> bytes:
        """使用 Excel 标准化输出插件填充模板并导出 PDF。

        流程：ORM 对象 → dict 列表 → openpyxl 填表 → LibreOffice → PDF bytes
        不依赖 AI，格式 100% 复刻 Excel 模板。
        """
        import tempfile

        from app.modules.safety.template_export import (
            HAZARD_TEMPLATE_CONFIG,
            ExcelTemplateFiller,
            ExcelToPdfConverter,
        )

        # ORM → dict
        data = [self._item_to_dict(item) for item in items]

        # 模板位置
        template_dir = Path(__file__).resolve().parent.parent / "templates"
        template_path = template_dir / "危险源辨识管控清单模板.xlsx"
        if not template_path.exists():
            raise FileNotFoundError(f"模板文件不存在: {template_path}")

        # 临时文件 → PDF bytes
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            xlsx_path = tmp / "hazard_ledger.xlsx"
            pdf_path = tmp / "hazard_ledger.pdf"

            filler = ExcelTemplateFiller(HAZARD_TEMPLATE_CONFIG)
            filler.fill_and_save(template_path, data, xlsx_path)
            ExcelToPdfConverter().convert(xlsx_path, pdf_path)

            return pdf_path.read_bytes()

    def _item_to_dict(self, item) -> dict:
        """将 HazardIdentification ORM 对象转为可 JSON 序列化的 dict"""
        return {
            "hazard_id_no": item.hazard_id_no,
            "department": item.department,
            "position": item.position,
            "production_step": item.production_step,
            "specific_activity": item.specific_activity,
            "equipment_facilities": item.equipment_facilities,
            "hazard_type": item.hazard_type,
            "possible_accident": item.possible_accident,
            "inherent_risk_level": item.inherent_risk_level,
            "inherent_risk_label": item.inherent_risk_label,
            "l_inherent": int(item.l_inherent) if item.l_inherent else None,
            "e_inherent": int(item.e_inherent) if item.e_inherent else None,
            "c_inherent": int(item.c_inherent) if item.c_inherent else None,
            "d_inherent": int(item.d_inherent) if item.d_inherent else None,
            "residual_risk_level": item.residual_risk_level,
            "residual_risk_label": item.residual_risk_label,
            "l_residual": int(item.l_residual) if item.l_residual else None,
            "e_residual": int(item.e_residual) if item.e_residual else None,
            "c_residual": int(item.c_residual) if item.c_residual else None,
            "d_residual": int(item.d_residual) if item.d_residual else None,
            "existing_engineering_controls": item.existing_engineering_controls,
            "existing_management_controls": item.existing_management_controls,
            "existing_ppe": item.existing_ppe,
            "existing_emergency_measures": item.existing_emergency_measures,
            "control_level": item.control_level,
            "responsible_person": item.responsible_person,
            "needs_recommendation": item.needs_recommendation,
            "recommendation_type": item.recommendation_type,
            "recommendation_content": item.recommendation_content,
            "overall_status": item.overall_status,
            "notes": item.notes,
        }

    # ── 固定模板 PDF 回退（reportlab）──

    async def _export_hazard_ledger_pdf_fallback(
        self, items, filters: dict
    ) -> bytes:
        """固定模板 PDF 生成（reportlab）—— AI 格式化失败时的回退方案"""
        import io
        from datetime import datetime as dt_module

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )

        # A4 横向
        page_w, page_h = landscape(A4)
        margin = 15 * mm
        buf = io.BytesIO()

        doc = SimpleDocTemplate(
            buf,
            pagesize=landscape(A4),
            leftMargin=margin,
            rightMargin=margin,
            topMargin=margin,
            bottomMargin=margin,
            title="危险源辨识台账",
        )

        # 字体注册
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        _font_name = "Helvetica"
        _font_name_bold = "Helvetica-Bold"
        _chinese_fonts = [
            ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
            ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
            ("C:/Windows/Fonts/msyh.ttc", "MicrosoftYaHei"),
        ]
        for font_path, font_alias in _chinese_fonts:
            try:
                pdfmetrics.registerFont(TTFont(font_alias, font_path))
                if font_alias == "SimSun":
                    _font_name = "SimSun"
                if font_alias == "SimHei":
                    _font_name_bold = "SimHei"
            except Exception:
                pass
        logger.debug("PDF fonts: body=%s, bold=%s", _font_name, _font_name_bold)

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "BodyCN", parent=styles["Normal"],
            fontName=_font_name, fontSize=8, leading=12,
        )
        title_style = ParagraphStyle(
            "TitleCN", parent=styles["Title"],
            fontName=_font_name_bold, fontSize=16, leading=22,
            alignment=TA_CENTER, spaceAfter=4,
        )
        subtitle_style = ParagraphStyle(
            "SubtitleCN", parent=styles["Normal"],
            fontName=_font_name, fontSize=9, leading=14,
            alignment=TA_CENTER, textColor=colors.grey,
        )

        elements: list = []

        # 标题
        elements.append(Paragraph("危险源辨识台账", title_style))

        # 副标题
        filter_parts: list[str] = []
        for k, v in filters.items():
            if k == "risk_level":
                level_map = {
                    "level_1": "一级/重大风险", "level_2": "二级/较大风险",
                    "level_3": "三级/一般风险", "level_4": "四级/低风险",
                }
                filter_parts.append(f"风险等级：{level_map.get(v, v)}")
            elif k in ("date_from", "date_to"):
                label = "起" if k == "date_from" else "止"
                filter_parts.append(f"{label}：{v}")
            elif k == "keyword":
                filter_parts.append(f"关键词：{v}")
            else:
                filter_parts.append(f"{k}：{v}")
        filter_text = "；".join(filter_parts) if filter_parts else "全部记录"
        export_time = dt_module.now().strftime("%Y-%m-%d %H:%M")
        elements.append(Paragraph(
            f"筛选条件：{filter_text}　|　导出时间：{export_time}　|　共 {len(items)} 条",
            subtitle_style,
        ))
        elements.append(Spacer(1, 6 * mm))

        # ── 数据表 ──
        level_label_map = {
            "level_1": "重大", "level_2": "较大",
            "level_3": "一般", "level_4": "低",
        }
        headers = [
            "序号", "编号", "部门", "岗位", "作业活动",
            "危险类型", "固有风险", "残余风险",
            "管控层级", "责任人", "控制措施摘要",
        ]
        col_widths = [25, 70, 50, 50, 80, 55, 55, 55, 45, 50, 160]

        table_data = [headers]
        for idx, item in enumerate(items, 1):
            inherent_label = item.inherent_risk_label or level_label_map.get(
                item.inherent_risk_level or "", ""
            )
            inherent_d = (
                f"{inherent_label}(D={int(item.d_inherent)})"
                if item.d_inherent and inherent_label
                else inherent_label or "-"
            )
            residual_label = item.residual_risk_label or level_label_map.get(
                item.residual_risk_level or "", ""
            )
            residual_d = (
                f"{residual_label}(D={int(item.d_residual)})"
                if item.d_residual and residual_label
                else residual_label or "-"
            )

            controls_parts = []
            if item.existing_engineering_controls:
                controls_parts.append(f"工程：{item.existing_engineering_controls[:60]}")
            if item.existing_management_controls:
                controls_parts.append(f"管理：{item.existing_management_controls[:60]}")
            if item.existing_ppe:
                controls_parts.append(f"PPE：{item.existing_ppe[:40]}")
            controls_summary = "；".join(controls_parts) if controls_parts else "-"

            table_data.append([
                str(idx),
                item.hazard_id_no or "",
                item.department or "",
                item.position or "",
                item.specific_activity or item.production_step or "",
                item.hazard_type or "",
                inherent_d,
                residual_d,
                item.control_level or "",
                item.responsible_person or "",
                controls_summary,
            ])

        table = Table(table_data, colWidths=[w * mm / 4 for w in col_widths], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#5645D4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), _font_name_bold),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, 0), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 1), (-1, -1), _font_name),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (1, 1), (1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
            ("LINEBELOW", (0, 0), (-1, 0), 1.5, colors.HexColor("#3D2DA6")),
            *[
                ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F7F6FB"))
                for i in range(2, len(table_data) + 1, 2)
            ],
        ]))
        elements.append(table)
        elements.append(Spacer(1, 10 * mm))

        # ── 签发栏 ──
        sign_style = ParagraphStyle(
            "SignCN", parent=body_style, fontSize=10, leading=16,
        )
        sign_table = Table(
            [[
                Paragraph("编制人：______________", sign_style),
                Paragraph("审核人：______________", sign_style),
                Paragraph("批准人：______________", sign_style),
            ]],
            colWidths=[page_w / 3 - 20, page_w / 3 - 20, page_w / 3 - 20],
        )
        sign_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), _font_name),
            ("LEFTPADDING", (0, 0), (-1, -1), 30),
            ("RIGHTPADDING", (0, 0), (-1, -1), 30),
        ]))
        sign_table2 = Table(
            [[
                Paragraph("日期：______________", sign_style),
                Paragraph("日期：______________", sign_style),
                Paragraph("日期：______________", sign_style),
            ]],
            colWidths=[page_w / 3 - 20, page_w / 3 - 20, page_w / 3 - 20],
        )
        sign_table2.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, -1), _font_name),
            ("LEFTPADDING", (0, 0), (-1, -1), 30),
            ("RIGHTPADDING", (0, 0), (-1, -1), 30),
        ]))
        elements.append(sign_table)
        elements.append(Spacer(1, 4 * mm))
        elements.append(sign_table2)

        def add_page_number(canvas, doc_obj):
            canvas.saveState()
            canvas.setFont(_font_name, 8)
            canvas.drawCentredString(
                page_w / 2, 10 * mm, f"第 {canvas.getPageNumber()} 页",
            )
            canvas.restoreState()

        doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
        buf.seek(0)
        return buf.getvalue()

# ==================== 操规修订 Service ====================


