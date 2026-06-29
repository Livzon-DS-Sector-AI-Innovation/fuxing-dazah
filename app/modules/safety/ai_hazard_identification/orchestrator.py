"""危险源辨识编排器 — 桥接 Service 层与 7 个独立 Plugin。

职责：
1. DB 记录 → Plugin Input 构建（_build_input）
2. Plugin 选择与调用（_get_plugin + plugin.identify）
3. Plugin Output → DB update_data 映射（_map_output_to_db）
4. LEC 计算兜底（_calculate_lec_fallback）
5. 知识上下文加载（_load_knowledge_context）

用法:
    orchestrator = HazardIdentificationOrchestrator(ai_service, session)
    update_data = await orchestrator.run_script(db_record, script_number=1)
    # update_data 可直接传给 repo.update()
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.modules.safety.ai_hazard_identification._base import PluginError
from app.modules.safety.ai_hazard_identification.schemas import PluginConfig

logger = logging.getLogger(__name__)


class OrchestratorError(Exception):
    """编排器错误。"""
    pass


class HazardIdentificationOrchestrator:
    """危险源辨识 AI 工作流编排器。

    桥接 Service 层（DB 记录）与 Plugin 层（Pydantic Input/Output）：
    - 6 步编排：知识加载 → Input构建 → Plugin选择 → 调用 → 映射 → LEC兜底
    - 每个 Plugin 独立可测试，只需注入 AIService
    - DB mapping 集中管理，避免散落在 Service 层
    """

    # ── 状态机映射（与 SafetyService.SCRIPT_NODE_MAP 一致）──
    SCRIPT_NODE_MAP: dict[int, tuple[str, str, str]] = {
        1: ("pending_script1", "pending_script2", "script1_review_status"),
        2: ("pending_script2", "pending_script3", "script2_review_status"),
        3: ("pending_script3", "pending_script4", "script3_review_status"),
        4: ("pending_script4", "pending_script5", "script4_review_status"),
        5: ("pending_script5", "pending_script6", "script5_review_status"),
        6: ("pending_script6", "pending_script7", "script6_review_status"),
        7: ("pending_script7", "completed",     "script7_review_status"),
    }

    def __init__(
        self,
        ai_service: Any,
        session: Any = None,
        config: PluginConfig | None = None,
    ):
        self.ai_service = ai_service
        self.session = session
        self.config = config or PluginConfig()

    # ═══════════════════════════════════════════════════════════
    # 公共 API
    # ═══════════════════════════════════════════════════════════

    async def run_script(
        self,
        item: Any,  # HazardIdentification ORM object
        script_number: int,
    ) -> dict[str, Any]:
        """执行指定脚本，返回 update_data dict。

        Args:
            item: DB 中的 HazardIdentification 记录
            script_number: 1-7

        Returns:
            可直接传给 repo.update() 的字段字典

        Raises:
            OrchestratorError: 状态不允许或 AI 调用失败
        """
        if script_number < 1 or script_number > 7:
            raise OrchestratorError(f"无效的脚本编号: {script_number}")

        # 1. 加载知识上下文
        knowledge_context = await self._load_knowledge_context(script_number, item)

        # 2. 构建 Plugin Input
        input_data = await self._build_input(script_number, item)

        # 3. 获取 Plugin 实例
        plugin = self._get_plugin(script_number, knowledge_context)

        # 4. 调用 Plugin（4-phase pipeline）
        try:
            output = await plugin.identify(input_data)
        except PluginError as e:
            logger.error("脚本 %d 执行失败: %s", script_number, e)
            raise OrchestratorError(str(e)) from e

        # 5. 映射 Output → update_data（含状态机推进）
        update_data = self._map_output_to_db(script_number, output)

        # 6. LEC 兜底计算（脚本3/5/7）
        if script_number in (3, 5, 7):
            self._calculate_lec_fallback(script_number, update_data)

        return update_data

    # ═══════════════════════════════════════════════════════════
    # Input 构建（DB ORM → Pydantic Input）
    # ═══════════════════════════════════════════════════════════

    async def _build_input(self, script_number: int, item: Any) -> Any:
        """从 DB 记录构建 Plugin Input 模型。

        每个脚本的 Input 模型是其前置步骤输出的累积：
        - 脚本1: 仅基础信息 + 附件文本
        - 脚本2: + 脚本1输出
        - 脚本3: + 脚本2输出
        - ...以此类推
        """
        if script_number == 1:
            from app.modules.safety.ai_hazard_identification.script1_attachment.schemas import (
                AttachmentInput,
            )

            # 优先使用引用的安全操作规程内容（替代附件上传）
            attachment_text: str | None = None
            if item.regulation_id and self.session:
                from app.modules.safety.models import OperationRegulation

                # 多工段模式：优先使用 chapter7_context（仅该工段的节选内容）
                if getattr(item, "chapter7_context", None):
                    attachment_text = item.chapter7_context
                    logger.info(
                        "脚本1 使用工段特化操规内容: %s (%d 字符)",
                        getattr(item, "stage_name", "?"), len(attachment_text),
                    )
                else:
                    stmt = select(OperationRegulation).where(
                        OperationRegulation.id == item.regulation_id,
                        OperationRegulation.is_deleted.is_(False),
                    )
                    result = await self.session.execute(stmt)
                    reg = result.scalar_one_or_none()
                    if reg:
                        # 单条模式：使用完整 Markdown 内容，回退到原始文档解析
                        if reg.content:
                            attachment_text = reg.content
                            logger.info(
                                "脚本1 使用完整操规内容: %s (%d 字符)",
                                reg.regulation_name, len(reg.content),
                            )
                        elif reg.document_path:
                            try:
                                from app.modules.safety.ai_hazard_identification.script1_attachment.plugin import (
                                    DocumentParser,
                                )
                                attachment_text = DocumentParser.extract_text(
                                    reg.document_path, max_chars=30000,
                                )
                                logger.info(
                                    "脚本1 解析引用操规文档: %s (%d 字符)",
                                    reg.regulation_name, len(attachment_text or ""),
                                )
                            except Exception as e:
                                logger.warning("引用操规文档解析失败: %s", e)

            # 回退：使用上传的附件文本（旧模式兼容）
            if not attachment_text:
                attachment_text = getattr(item, '_attachment_text', None)

            return AttachmentInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                attachment_text=attachment_text,
            )

        elif script_number == 2:
            from app.modules.safety.ai_hazard_identification.script2_hazard_id.schemas import (
                HazardIdInput,
            )
            return HazardIdInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                specific_activity=item.specific_activity or "",
                equipment_facilities=item.equipment_facilities or "",
                raw_auxiliary_materials=item.raw_auxiliary_materials or "",
                operation_frequency=item.operation_frequency,
                operator_count=item.operator_count,
            )

        elif script_number == 3:
            from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
                InherentRiskInput,
            )
            return InherentRiskInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                specific_activity=item.specific_activity or "",
                equipment_facilities=item.equipment_facilities or "",
                raw_auxiliary_materials=item.raw_auxiliary_materials or "",
                operation_frequency=item.operation_frequency,
                hazard_type=item.hazard_type or "",
                possible_accident=item.possible_accident or "",
                unsafe_behavior=item.unsafe_behavior or "",
            )

        elif script_number == 4:
            from app.modules.safety.ai_hazard_identification.script4_controls.schemas import (
                ControlsInput,
            )
            return ControlsInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                specific_activity=item.specific_activity or "",
                equipment_facilities=item.equipment_facilities or "",
                raw_auxiliary_materials=item.raw_auxiliary_materials or "",
                hazard_type=item.hazard_type or "",
                possible_accident=item.possible_accident or "",
                unsafe_behavior=item.unsafe_behavior or "",
                l_inherent=item.l_inherent,
                e_inherent=item.e_inherent,
                c_inherent=item.c_inherent,
                d_inherent=item.d_inherent,
                inherent_risk_level=item.inherent_risk_level,
                inherent_risk_label=item.inherent_risk_label,
            )

        elif script_number == 5:
            from app.modules.safety.ai_hazard_identification.script5_residual_risk.schemas import (
                ResidualRiskInput,
            )
            return ResidualRiskInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                specific_activity=item.specific_activity or "",
                equipment_facilities=item.equipment_facilities or "",
                raw_auxiliary_materials=item.raw_auxiliary_materials or "",
                operation_frequency=item.operation_frequency,
                hazard_type=item.hazard_type or "",
                possible_accident=item.possible_accident or "",
                unsafe_behavior=item.unsafe_behavior or "",
                l_inherent=item.l_inherent,
                e_inherent=item.e_inherent,
                c_inherent=item.c_inherent,
                d_inherent=item.d_inherent,
                inherent_risk_level=item.inherent_risk_level,
                inherent_risk_label=item.inherent_risk_label,
                existing_engineering_controls=item.existing_engineering_controls or "",
                existing_management_controls=item.existing_management_controls or "",
                existing_ppe=item.existing_ppe or "",
                existing_emergency_measures=item.existing_emergency_measures or "",
            )

        elif script_number == 6:
            from app.modules.safety.ai_hazard_identification.script6_recommendations.schemas import (
                RecommendationInput,
            )
            return RecommendationInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                specific_activity=item.specific_activity or "",
                equipment_facilities=item.equipment_facilities or "",
                raw_auxiliary_materials=item.raw_auxiliary_materials or "",
                hazard_type=item.hazard_type or "",
                possible_accident=item.possible_accident or "",
                unsafe_behavior=item.unsafe_behavior or "",
                l_inherent=item.l_inherent,
                e_inherent=item.e_inherent,
                c_inherent=item.c_inherent,
                d_inherent=item.d_inherent,
                inherent_risk_level=item.inherent_risk_level,
                inherent_risk_label=item.inherent_risk_label,
                existing_engineering_controls=item.existing_engineering_controls or "",
                existing_management_controls=item.existing_management_controls or "",
                existing_ppe=item.existing_ppe or "",
                existing_emergency_measures=item.existing_emergency_measures or "",
                l_residual=item.l_residual,
                e_residual=item.e_residual,
                c_residual=item.c_residual,
                d_residual=item.d_residual,
                residual_risk_level=item.residual_risk_level,
                residual_risk_label=item.residual_risk_label,
                control_level=item.control_level,
            )

        elif script_number == 7:
            from app.modules.safety.ai_hazard_identification.script7_post_risk.schemas import (
                PostRiskInput,
            )
            return PostRiskInput(
                department=item.department or "",
                position=item.position or "",
                production_step=item.production_step or "",
                specific_activity=item.specific_activity or "",
                equipment_facilities=item.equipment_facilities or "",
                raw_auxiliary_materials=item.raw_auxiliary_materials or "",
                operation_frequency=item.operation_frequency,
                hazard_type=item.hazard_type or "",
                possible_accident=item.possible_accident or "",
                unsafe_behavior=item.unsafe_behavior or "",
                l_inherent=item.l_inherent,
                e_inherent=item.e_inherent,
                c_inherent=item.c_inherent,
                d_inherent=item.d_inherent,
                inherent_risk_level=item.inherent_risk_level,
                inherent_risk_label=item.inherent_risk_label,
                existing_engineering_controls=item.existing_engineering_controls or "",
                existing_management_controls=item.existing_management_controls or "",
                existing_ppe=item.existing_ppe or "",
                existing_emergency_measures=item.existing_emergency_measures or "",
                l_residual=item.l_residual,
                e_residual=item.e_residual,
                c_residual=item.c_residual,
                d_residual=item.d_residual,
                residual_risk_level=item.residual_risk_level,
                residual_risk_label=item.residual_risk_label,
                control_level=item.control_level,
                recommendation_content=item.recommendation_content,
                recommendation_type=item.recommendation_type,
            )

        raise OrchestratorError(f"未知脚本编号: {script_number}")

    # ═══════════════════════════════════════════════════════════
    # Plugin 工厂
    # ═══════════════════════════════════════════════════════════

    def _get_plugin(self, script_number: int, knowledge_context: str | None):
        """获取对应脚本的 Plugin 实例（工厂方法）。

        每个 Plugin 在构造时注入：
        - ai_service: AI 调用接口
        - config: 运行时配置（temperature=0.05 等）
        - knowledge_context: 法规知识库文本
        """
        if script_number == 1:
            from app.modules.safety.ai_hazard_identification.script1_attachment.plugin import (
                AttachmentParser,
            )
            return AttachmentParser(self.ai_service, self.config, knowledge_context)
        elif script_number == 2:
            from app.modules.safety.ai_hazard_identification.script2_hazard_id.plugin import (
                HazardIdentifier,
            )
            return HazardIdentifier(self.ai_service, self.config, knowledge_context)
        elif script_number == 3:
            from app.modules.safety.ai_hazard_identification.script3_inherent_risk.plugin import (
                InherentRiskAssessor,
            )
            return InherentRiskAssessor(self.ai_service, self.config, knowledge_context)
        elif script_number == 4:
            from app.modules.safety.ai_hazard_identification.script4_controls.plugin import (
                ControlMeasureExtractor,
            )
            return ControlMeasureExtractor(self.ai_service, self.config, knowledge_context)
        elif script_number == 5:
            from app.modules.safety.ai_hazard_identification.script5_residual_risk.plugin import (
                ResidualRiskAssessor,
            )
            return ResidualRiskAssessor(self.ai_service, self.config, knowledge_context)
        elif script_number == 6:
            from app.modules.safety.ai_hazard_identification.script6_recommendations.plugin import (
                RecommendationGenerator,
            )
            return RecommendationGenerator(self.ai_service, self.config, knowledge_context)
        elif script_number == 7:
            from app.modules.safety.ai_hazard_identification.script7_post_risk.plugin import (
                PostMeasureAssessor,
            )
            return PostMeasureAssessor(self.ai_service, self.config, knowledge_context)
        raise OrchestratorError(f"未知脚本编号: {script_number}")

    # ═══════════════════════════════════════════════════════════
    # Output → DB 映射
    # ═══════════════════════════════════════════════════════════

    def _map_output_to_db(
        self, script_number: int, output: Any,
    ) -> dict[str, Any]:
        """将 Plugin Output（Pydantic 对象）映射为 DB update_data dict。

        同时推进状态机：ai_node_progress → next_node。
        """
        update: dict[str, Any] = {}

        # 推进状态机
        _, next_node, _ = self.SCRIPT_NODE_MAP[script_number]
        update["ai_node_progress"] = next_node
        update["ai_error_message"] = None

        if script_number == 1:
            update["specific_activity"] = output.specific_activity
            update["equipment_facilities"] = output.equipment_facilities
            update["raw_auxiliary_materials"] = output.raw_auxiliary_materials

        elif script_number == 2:
            update["hazard_type"] = output.hazard_type
            update["possible_accident"] = output.possible_accident
            update["unsafe_behavior"] = output.unsafe_behavior

        elif script_number == 3:
            lec = output.lec
            if lec.l_value is not None:
                update["l_inherent"] = lec.l_value
            if lec.e_value is not None:
                update["e_inherent"] = lec.e_value
            if lec.c_value is not None:
                update["c_inherent"] = lec.c_value
            if lec.d_value is not None:
                update["d_inherent"] = lec.d_value
            if lec.risk_level is not None:
                update["inherent_risk_level"] = lec.risk_level
            if lec.risk_label is not None:
                update["inherent_risk_label"] = lec.risk_label

        elif script_number == 4:
            update["existing_engineering_controls"] = output.engineering_controls
            update["existing_management_controls"] = output.management_controls
            update["existing_ppe"] = output.ppe
            update["existing_emergency_measures"] = output.emergency_measures

        elif script_number == 5:
            lec = output.lec
            if lec.l_value is not None:
                update["l_residual"] = lec.l_value
            if lec.e_value is not None:
                update["e_residual"] = lec.e_value
            if lec.c_value is not None:
                update["c_residual"] = lec.c_value
            if lec.d_value is not None:
                update["d_residual"] = lec.d_value
            if lec.risk_level is not None:
                update["residual_risk_level"] = lec.risk_level
            if lec.risk_label is not None:
                update["residual_risk_label"] = lec.risk_label

        elif script_number == 6:
            update["needs_recommendation"] = output.needs_recommendation
            update["recommendation_type"] = output.recommendation_type
            update["recommendation_content"] = output.recommendation_content
            update["recommendation_priority"] = output.recommendation_priority

        elif script_number == 7:
            lec = output.lec
            if lec.l_value is not None:
                update["l_post"] = lec.l_value
            if lec.e_value is not None:
                update["e_post"] = lec.e_value
            if lec.c_value is not None:
                update["c_post"] = lec.c_value
            if lec.d_value is not None:
                update["d_post"] = lec.d_value
            if lec.risk_level is not None:
                update["post_risk_level"] = lec.risk_level
            if lec.risk_label is not None:
                update["post_risk_label"] = lec.risk_label

        return update

    # ═══════════════════════════════════════════════════════════
    # LEC 兜底计算
    # ═══════════════════════════════════════════════════════════

    def _calculate_lec_fallback(
        self, script_number: int, update_data: dict[str, Any],
    ) -> None:
        """当 AI 未输出 D 值或风险等级时，用 L×E×C 兜底计算。

        仅对脚本3/5/7 执行：
        1. D = L × E × C（若 L/E/C 均有值且 D 为空）
        2. 根据 D 值查 RISK_LEVELS 表填充 risk_level + risk_label
        3. 脚本3额外补全 control_level 和 responsible_person
        """
        from app.modules.safety.schemas.hazard_identifications import (
            RISK_LEVELS,
            get_risk_level,
        )

        # 确定当前脚本对应的字段前缀
        if script_number == 3:
            l_key, e_key, c_key = "l_inherent", "e_inherent", "c_inherent"
            d_key, level_key, label_key = (
                "d_inherent", "inherent_risk_level", "inherent_risk_label",
            )
        elif script_number == 5:
            l_key, e_key, c_key = "l_residual", "e_residual", "c_residual"
            d_key, level_key, label_key = (
                "d_residual", "residual_risk_level", "residual_risk_label",
            )
        elif script_number == 7:
            l_key, e_key, c_key = "l_post", "e_post", "c_post"
            d_key, level_key, label_key = (
                "d_post", "post_risk_level", "post_risk_label",
            )
        else:
            return

        l_val = update_data.get(l_key)
        e_val = update_data.get(e_key)
        c_val = update_data.get(c_key)

        if all(v is not None for v in (l_val, e_val, c_val)):
            # 兜底计算 D = L × E × C
            if update_data.get(d_key) is None:
                update_data[d_key] = l_val * e_val * c_val

            # 兜底风险等级映射
            if update_data.get(level_key) is None:
                d_val = update_data[d_key]
                level = get_risk_level(d_val)
                update_data[level_key] = level["key"]
                update_data[label_key] = level["label"]

            # 脚本3额外补全管控层级 + 责任人
            if script_number == 3:
                for rl in RISK_LEVELS:
                    if rl["key"] == update_data.get(level_key):
                        if "control_level" not in update_data or update_data["control_level"] is None:
                            update_data["control_level"] = rl["control_level"]
                        if "responsible_person" not in update_data or update_data["responsible_person"] is None:
                            update_data["responsible_person"] = rl["responsible_person"]
                        break

    # ═══════════════════════════════════════════════════════════
    # 知识上下文加载
    # ═══════════════════════════════════════════════════════════

    async def _load_knowledge_context(
        self, script_number: int, item: Any,
    ) -> str | None:
        """从 knowledge_articles 表加载与当前脚本相关的知识上下文。

        不同脚本加载不同类型的知识卡片：
        - 脚本 1,2: laws_regulations, standards（法规标准原文）
        - 脚本 3,5,7: risk_assessment_standards（LEC 评分标准）
        - 脚本 4: management_systems（管理制度汇编）
        - 脚本 6: industry_best_practices（行业最佳实践）
        """
        if not self.session:
            return None

        try:
            from app.modules.safety.knowledge import KnowledgeInjector
            injector = KnowledgeInjector(self.session)

            # 根据脚本类型筛选知识卡片类别
            if script_number in (1, 2):
                categories = ["laws_regulations", "standards"]
            elif script_number in (3, 5, 7):
                categories = ["risk_assessment_standards", "standards"]
            elif script_number == 4:
                categories = ["management_systems"]
            elif script_number == 6:
                categories = ["industry_best_practices", "standards"]
            else:
                categories = ["standards"]

            context = await injector.build_context(
                categories=categories,
                max_cards=3,
                ai_service=self.ai_service,
                hazard_description=getattr(item, "description", "") or "",
            )
            return context if context else None
        except Exception as e:
            logger.warning("知识上下文加载失败（非致命）: %s", e)
            return None
