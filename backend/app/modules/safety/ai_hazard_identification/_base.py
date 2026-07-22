"""危险源辨识 Plugin 基类 — 对标 AIHazardIdentifier 的 4-phase pipeline。

所有 7 个脚本 Plugin 继承此基类，共享已验证的 pipeline 模式：
  阶段一：输入预处理
  阶段二：AI 分析
  阶段三：解析 & 验证 & 自动修正
  阶段四：输出

设计原则（对标 AIHazardIdentifier）：
- 低温度（0.05）保证输出可复现
- 4-phase pipeline 确保流程一致性
- 规则引擎后处理确保质量
- 知识库注入（RAG-lite）
- 完整的日志记录用于审计

用法:
    class HazardIdentifier(BasePlugin[HazardIdInput, HazardIdOutput]):
        def _get_system_role(self) -> str: ...
        def _build_prompt(self, input_data, context_text) -> str: ...
        def _get_expected_keys(self) -> list[str]: ...
        def _parse_output(self, raw: dict) -> HazardIdOutput: ...
        def _validate(self, input_data, output) -> list[str]: ...

    plugin = HazardIdentifier(ai_service, config, knowledge_context)
    output = await plugin.identify(input_data)
"""

from __future__ import annotations

import json as _json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from app.modules.safety.ai_hazard_identification.schemas import PluginConfig

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Plugin 执行失败异常。"""
    pass


class UnknownValueError(PluginError):
    """AI 判定依据不足（信息不足→待人工确认）。不是真正的错误，但需要人工介入。"""
    pass


class BasePlugin[TInput: BaseModel, TOutput: BaseModel](ABC):
    """危险源辨识 Plugin 基类。

    设计原则（对标 AIHazardIdentifier）：
    - 低温度（0.05）保证输出可复现
    - 4-phase pipeline: 预处理 → AI分析 → 解析验证 → 输出
    - 规则引擎后处理确保质量
    - 知识库注入（RAG-lite）
    - 完整的日志记录用于审计

    Args:
        ai_service: AI 服务实例
        config: 插件运行时配置
        knowledge_context: 法规/标准知识库上下文文本

    子类必须实现:
        _get_system_role() → str
        _build_prompt(input_data, context_text) → str
        _get_expected_keys() → list[str]
        _parse_output(raw: dict) → TOutput
        _validate(input_data, output) → list[str]  # errors
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        self.ai_service = ai_service
        self.config = config or PluginConfig()
        self.knowledge_context = knowledge_context

    # ═══════════════════════════════════════════════════════════
    # 公共 API
    # ═══════════════════════════════════════════════════════════

    async def identify(self, input_data: TInput) -> TOutput:
        """执行完整的 AI 分析流程（4-phase pipeline）。

        Args:
            input_data: 标准化输入

        Returns:
            经过规则验证和自动修正的分析结果

        Raises:
            PluginError: AI 调用失败或输出不合法
        """
        start_time = time.monotonic()
        script_name = self.__class__.__name__

        # ── 阶段一：输入预处理 ──
        logger.info("[%s] 阶段一：输入预处理", script_name)
        await self._preprocess(input_data)

        # ── 阶段二：AI 分析 ──
        logger.info("[%s] 阶段二：AI 分析", script_name)
        raw_output = await self._call_ai(input_data)

        # ── 阶段三：解析 & 验证 ──
        logger.info("[%s] 阶段三：解析输出并规则验证", script_name)
        output = self._parse_output(raw_output)

        # 自动修正
        output = self._auto_correct(output)

        # 规则验证
        errors = self._validate(input_data, output)
        if errors:
            error_detail = "; ".join(errors)
            if self.config.strict_mode:
                raise PluginError(
                    f"[{script_name}] AI 输出验证失败: {error_detail}\n"
                    f"原始输出: "
                    f"{_json.dumps(raw_output, ensure_ascii=False, default=str)[:500]}"
                )
            else:
                logger.warning(
                    "[%s] AI 输出验证失败（非严格模式）: %s",
                    script_name, error_detail,
                )

        # ── 阶段四：返回结果 ──
        elapsed = time.monotonic() - start_time
        logger.info("[%s] 分析完成 — elapsed=%.2fs", script_name, elapsed)

        return output

    # ═══════════════════════════════════════════════════════════
    # 子类必须实现
    # ═══════════════════════════════════════════════════════════

    @abstractmethod
    def _get_system_role(self) -> str:
        """返回 system prompt 中的角色定义。"""
        ...

    @abstractmethod
    def _build_prompt(self, input_data: TInput, context_text: str) -> str:
        """构建完整的 user prompt。

        4 段式结构：input_info + work_rules + reference_docs + output_format。
        """
        ...

    @abstractmethod
    def _get_expected_keys(self) -> list[str]:
        """返回 AI 输出 JSON 必须包含的字段列表。"""
        ...

    @abstractmethod
    def _parse_output(self, raw: dict) -> TOutput:
        """将 AI 返回的字典解析为强类型 Output。"""
        ...

    @abstractmethod
    def _validate(self, input_data: TInput, output: TOutput) -> list[str]:
        """验证 AI 输出。返回错误列表，空列表 = 通过。"""
        ...

    # ═══════════════════════════════════════════════════════════
    # 子类可选覆盖
    # ═══════════════════════════════════════════════════════════

    async def _preprocess(self, input_data: TInput) -> None:
        """阶段一 hook：预处理（默认无操作）。子类覆盖以添加自定义预处理。"""
        pass

    def _auto_correct(self, output: TOutput) -> TOutput:
        """阶段三 hook：自动修正（默认无操作）。子类覆盖以添加修正逻辑。"""
        return output

    # ═══════════════════════════════════════════════════════════
    # 内部方法
    # ═══════════════════════════════════════════════════════════

    async def _call_ai(self, input_data: TInput) -> dict:
        """调用文本 AI 服务。

        组装 4 段式 prompt → 调用 AI → 返回解析后的 dict。
        """
        # 构建上下文字符串（用于 INPUT_INFO 段）
        context_text = self._build_context_text(input_data)
        # 构建完整 prompt（INPUT_INFO + WORK_RULES + REFERENCE_DOCS + OUTPUT_FORMAT）
        prompt = self._build_prompt(input_data, context_text)

        messages = [
            {"role": "system", "content": self._get_system_role()},
            {"role": "user", "content": prompt},
        ]

        try:
            return await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=self._get_expected_keys(),
                temperature=self.config.temperature,
            )
        except Exception as e:
            logger.error("[%s] AI 调用失败: %s", self.__class__.__name__, e)
            raise PluginError(f"AI 分析失败: {e}") from e

    def _build_context_text(self, input_data: TInput) -> str:
        """从 Input 模型构建上下文字符串。

        将 Pydantic 模型的所有非空字段格式化为 "中文标签：值" 的行列表，
        用于填充 prompt 的 INPUT_INFO 段。
        """
        parts: list[str] = []
        for field_name, value in input_data.model_dump().items():
            if value is not None and value != "" and value != []:
                label = self._field_label(field_name)
                parts.append(f"{label}：{value}")
        return "\n".join(parts)

    @staticmethod
    def _field_label(field_name: str) -> str:
        """字段名 → 中文标签映射。子类可覆盖以添加自定义字段标签。"""
        _field_labels: dict[str, str] = {
            # 基础信息
            "department": "部门",
            "position": "岗位",
            "production_step": "生产步骤",
            "notes": "备注",
            # 附件
            "attachment_text": "附件文档内容",
            # 脚本1 输出
            "operation_frequency": "作业频次",
            "operator_count": "操作人数",
            "specific_activity": "具体作业活动",
            "equipment_facilities": "设备设施",
            "raw_auxiliary_materials": "原辅料",
            # 脚本2 输出
            "hazard_type": "危险类型（GB 6441）",
            "possible_accident": "可能导致的事故",
            "unsafe_behavior": "人的不规范作业行为表现",
            # 脚本3 输出 — 固有风险 LEC
            "l_inherent": "可能性 L（固有）",
            "e_inherent": "暴露频率 E（固有）",
            "c_inherent": "严重性 C（固有）",
            "d_inherent": "风险值 D（固有）",
            "inherent_risk_level": "固有风险等级",
            "inherent_risk_label": "固有风险等级名",
            # 脚本4 输出
            "existing_engineering_controls": "现有工程控制措施",
            "existing_management_controls": "现有管理控制措施",
            "existing_ppe": "现有个人防护措施",
            "existing_emergency_measures": "现有应急措施",
            # 脚本5 输出 — 残余风险 LEC
            "l_residual": "可能性 L（残余）",
            "e_residual": "暴露频率 E（残余）",
            "c_residual": "严重性 C（残余）",
            "d_residual": "风险值 D（残余）",
            "residual_risk_level": "残余风险等级",
            "residual_risk_label": "残余风险等级名",
            # 管控
            "control_level": "管控等级",
            "responsible_person": "管控责任人",
            # 脚本6 输出
            "needs_recommendation": "是否需提出建议措施",
            "recommendation_type": "建议措施类型",
            "recommendation_content": "建议措施内容",
            "recommendation_priority": "建议措施优先级",
            # 脚本7 输出 — 措施后风险 LEC
            "l_post": "可能性 L（措施后）",
            "e_post": "暴露频率 E（措施后）",
            "c_post": "严重性 C（措施后）",
            "d_post": "风险值 D（措施后）",
            "post_risk_level": "措施后风险等级",
            "post_risk_label": "措施后风险等级名",
        }
        return _field_labels.get(field_name, field_name)
