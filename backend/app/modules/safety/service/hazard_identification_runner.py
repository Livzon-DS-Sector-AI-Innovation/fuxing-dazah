"""危险源辨识 Bitable 流 — 生产 run_script 适配器。

Ticket 06：把纯逻辑服务 `HazardIdentificationBitableService` 的注入接缝
（`run_script: async (script, effective) -> AI 输出对象`）接到真实的 8 个脚本 Plugin。

职责（全部是薄适配，业务逻辑仍由 Plugin / 服务层承担）：
- 脚本 → (Input 模型, Plugin 类) 映射
- effective dict（平台模型字段）→ Plugin Input 模型构建（按 Input 模型字段过滤 + None→"" 归一）
- 实例化 Plugin（注入 ai_service + config + 知识上下文）并调用 identify()
- 脚本2（危险源辨识）接入 RAG 知识库检索：以作业上下文为查询，召回企业法规/标准
  条款注入 Plugin，丰富 AI 的辨识依据。RAG 失败不阻断辨识（插件正常降级）。

设计要点：
- 与 orchestrator 的 DB 路径独立：Bitable 流无 ORM item，只有 effective dict。
- RAG 检索默认仅对脚本2 启用（其余脚本保持 knowledge_context=None 的既有行为）；
  `enable_rag=False` 或注入 `rag_loader` 可覆盖（测试用）。
- AI 审计：调用方（事件处理器）负责在入口开 `ai_audit_scope`，AuditedAIService 自动落表。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.modules.safety.ai_hazard_identification._base import PluginError
from app.modules.safety.ai_hazard_identification.schemas import PluginConfig

logger = logging.getLogger(__name__)

# 脚本 → (schemas 模块, Input 类名, plugin 模块, Plugin 类名)
# 惰性导入避免启动期重型依赖（模块级不 import 插件/模型）
# 注：dict 支持 float 键，3.5（福建固有风险评级）与 int 键 3 互不冲突
_SCRIPT_PLUGIN_MAP: dict[int | float, tuple[str, str, str, str]] = {
    1: ("app.modules.safety.ai_hazard_identification.script1_attachment.schemas", "AttachmentInput",
        "app.modules.safety.ai_hazard_identification.script1_attachment.plugin", "AttachmentParser"),
    2: ("app.modules.safety.ai_hazard_identification.script2_hazard_id.schemas", "HazardIdInput",
        "app.modules.safety.ai_hazard_identification.script2_hazard_id.plugin", "HazardIdentifier"),
    3: ("app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas", "InherentRiskInput",
        "app.modules.safety.ai_hazard_identification.script3_inherent_risk.plugin", "InherentRiskAssessor"),
    4: ("app.modules.safety.ai_hazard_identification.script4_controls.schemas", "ControlsInput",
        "app.modules.safety.ai_hazard_identification.script4_controls.plugin", "ControlMeasureExtractor"),
    5: ("app.modules.safety.ai_hazard_identification.script5_residual_risk.schemas", "ResidualRiskInput",
        "app.modules.safety.ai_hazard_identification.script5_residual_risk.plugin", "ResidualRiskAssessor"),
    6: ("app.modules.safety.ai_hazard_identification.script6_recommendations.schemas", "RecommendationInput",
        "app.modules.safety.ai_hazard_identification.script6_recommendations.plugin", "RecommendationGenerator"),
    7: ("app.modules.safety.ai_hazard_identification.script7_post_risk.schemas", "PostRiskInput",
        "app.modules.safety.ai_hazard_identification.script7_post_risk.plugin", "PostMeasureAssessor"),
    8: ("app.modules.safety.ai_hazard_identification.script8_inspection_items.schemas", "InspectionItemsInput",
        "app.modules.safety.ai_hazard_identification.script8_inspection_items.plugin", "InspectionItemGenerator"),
    # 脚本3.5: 福建固有风险评级（脚本3 附属评估，float 键）
    3.5: ("app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.schemas", "FujianRiskInput",
          "app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.plugin", "FujianRiskAssessor"),
}


class HazardIdentificationScriptRunner:
    """生产 run_script 适配器：effective dict → Plugin Input → Plugin.identify → 输出对象。

    用法:
        runner = HazardIdentificationScriptRunner()
        output = await runner(script_number=2, effective={...})   # → Pydantic 输出对象 | None
    """

    def __init__(
        self,
        ai_service: Any | None = None,
        config: PluginConfig | None = None,
        *,
        enable_rag: bool = True,
        rag_loader: Callable[[dict[str, Any]], Awaitable[str | None]] | None = None,
    ):
        # ai_service 惰性创建：只有真正执行脚本时才 `create_ai_service("text")`，
        # 避免 handler 模块 import 时因缺 API key 而失败。
        self._ai_service = ai_service
        self._config = config or PluginConfig(temperature=0.05)
        # RAG 知识增强（脚本2）：默认开启，可用注入的 rag_loader 覆盖（测试用）。
        self._enable_rag = enable_rag
        self._rag_loader = rag_loader

    async def __call__(self, script: int | float, effective: dict[str, Any]) -> Any | None:
        """执行指定脚本；AI 调用失败返回 None（节点保持等待，不产生部分写入）。"""
        try:
            from app.modules.safety.service.config import create_ai_service

            ai_service = self._ai_service or create_ai_service("text")
            input_model = self._build_input_model(script, effective)
            knowledge_context = await self._load_script_knowledge(script, effective)
            plugin = self._get_plugin(script, ai_service, knowledge_context)
            output = await plugin.identify(input_model)
            return output
        except PluginError as e:
            logger.error("危险源辨识 Bitable 流脚本 %d 执行失败: %s", script, e)
            return None
        except Exception as e:
            logger.error("危险源辨识 Bitable 流脚本 %d 异常: %s", script, e)
            return None

    async def _load_script_knowledge(
        self, script: int | float, effective: dict[str, Any],
    ) -> str | None:
        """加载脚本知识上下文（RAG）。当前仅脚本2（危险源辨识）启用。

        - 注入的 `rag_loader` 优先（测试可注入 fake，避免真实 DB/网络）。
        - 默认走 `_load_knowledge_context`：DB 会话检索知识库。
        - 任一路径失败均记录 warning 并返回 None —— RAG 是增强手段，
          绝不因检索失败阻断辨识（插件无知识上下文时正常降级）。
        """
        if script != 2 or not self._enable_rag:
            return None
        try:
            if self._rag_loader is not None:
                return await self._rag_loader(effective)
            return await self._load_knowledge_context(effective)
        except Exception as e:
            logger.warning("脚本2 RAG 知识加载失败，继续不使用知识增强: %s", e)
            return None

    async def _load_knowledge_context(self, effective: dict[str, Any]) -> str | None:
        """默认 RAG：以作业上下文为查询，检索法规/标准知识库，返回注入文本。

        检索本身为纯读取（规则实体提取 + 向量/全文混合检索），不产生额外 LLM 调用。
        任一步失败 → 记录 warning 并返回 None（插件无知识上下文时正常降级）。
        """
        query = self._build_rag_query(effective)
        if not query:
            return None
        try:
            from app.core.database import async_session_factory
            from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

            async with async_session_factory() as session:
                retriever = SafetyKnowledgeRetriever(session)
                context = await retriever.retrieve(description=query, target_chunks=8)
            injection = retriever.build_injection_context(context)
            if not injection:
                return None
            logger.info(
                "脚本2 RAG 知识增强: chunks=%d degradation=%s len=%d",
                len(context.chunks), context.degradation, len(injection),
            )
            return injection
        except Exception as e:
            logger.warning("脚本2 RAG 知识检索失败，继续不使用知识增强: %s", e)
            return None

    @staticmethod
    def _build_rag_query(effective: dict[str, Any]) -> str:
        """从 effective dict 构建 RAG 检索查询描述。

        拼接部门/岗位/生产步骤/具体作业活动/设备设施/原辅料，形成覆盖作业全貌的
        检索描述，供实体提取与混合检索召回相关法规/标准条款。
        """
        parts: list[str] = []
        for key in (
            "department", "position", "production_step", "specific_activity",
            "equipment_facilities", "raw_auxiliary_materials",
        ):
            val = effective.get(key)
            if val:
                text = str(val).strip()
                if text:
                    parts.append(text)
        return "。".join(parts)

    def _get_plugin(self, script: int | float, ai_service: Any, knowledge_context: str | None) -> Any:
        """实例化对应脚本的 Plugin。"""
        schemas_mod, input_cls, plugin_mod, plugin_cls = _SCRIPT_PLUGIN_MAP[script]
        import importlib

        plugin_cls_ = getattr(importlib.import_module(plugin_mod), plugin_cls)
        return plugin_cls_(ai_service, self._config, knowledge_context)

    def _build_input_model(self, script: int | float, effective: dict[str, Any]) -> Any:
        """effective dict（平台模型字段）→ Plugin Input 模型。

        只取 Input 模型声明的字段；None → ""（str 字段），保证必填 str 字段合法。
        """
        import importlib

        schemas_mod, input_cls_name, _, _ = _SCRIPT_PLUGIN_MAP[script]
        input_cls = getattr(importlib.import_module(schemas_mod), input_cls_name)

        kwargs: dict[str, Any] = {}
        for name, field in input_cls.model_fields.items():
            if name not in effective:
                continue
            value = effective[name]
            if value is None and field.annotation is str:
                value = ""
            kwargs[name] = value
        return input_cls(**kwargs)
