"""AI隐患识别插件 — 核心引擎。

将设计方案中的四阶段流程实现为可独立运行、可测试的插件：
  阶段一：输入采集与预处理
  阶段二：多模态AI分析
  阶段三：规则匹配与推理
  阶段四：输出生成

用法:
    from app.modules.safety.ai_hazard_identification import AIHazardIdentifier
    from app.platform.integrations.ai.client import AIService

    ai_service = AIService(api_key="...", base_url="...", model="...")
    plugin = AIHazardIdentifier(ai_service)

    input_data = HazardIdentificationInput(
        description="防爆电箱堵头缺失",
        department="生产部",
        location="合成车间一楼",
        defect_photos=["https://..."],
    )

    output = await plugin.identify(input_data)
    logger.debug("识别结果: key_defect=%s hazard_level=%s", output.key_defect, output.hazard_level)
"""

from __future__ import annotations

import json as _json
import logging
import time
from typing import Any

from app.modules.safety.ai_hazard_identification.prompts import (
    SYSTEM_ROLE,
    build_context_text,
    build_full_prompt,
    build_vision_context_text,
    get_expected_keys,
)
from app.modules.safety.ai_hazard_identification.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_hazard_identification.schemas import (
    HazardIdentificationInput,
    HazardIdentificationOutput,
    PluginConfig,
    RectificationSuggestion,
)

logger = logging.getLogger(__name__)


class IdentificationError(Exception):
    """AI 识别失败异常。"""
    pass


class AIHazardIdentifier:
    """AI隐患识别插件 — 稳定、可复现、可独立测试。

    设计原则：
    - 低温度（0.05）保证输出可复现
    - DB-first 配置 + 硬编码 fallback
    - 规则引擎后处理确保质量
    - 法规知识库注入（RAG-lite）
    - 完整的日志记录用于审计

    Args:
        ai_service: AI 服务实例（已配置 API key / base_url / model）
        config: 插件运行时配置（可选，使用默认值）
        knowledge_context: 法规知识库上下文文本（可选，注入到 prompt 中）

    Example:
        >>> ai_service = AIService(api_key="sk-xxx", model="deepseek-v4-flash")
        >>> plugin = AIHazardIdentifier(ai_service, knowledge_context="...")
        >>> output = await plugin.identify(HazardIdentificationInput(
        ...     description="防爆电箱堵头缺失",
        ...     department="生产部",
        ... ))
    """

    def __init__(
        self,
        ai_service: Any,  # AIService from app.platform.integrations.ai.client
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        self.ai_service = ai_service
        self.config = config or PluginConfig()
        self.rule_engine = RuleEngine()
        self.knowledge_context = knowledge_context

    # ── 公共 API ──

    async def identify(
        self,
        input_data: HazardIdentificationInput,
    ) -> HazardIdentificationOutput:
        """执行完整的 AI 隐患识别流程。

        Args:
            input_data: 标准化输入（含描述、图片、部门等上下文）

        Returns:
            经过规则验证和自动修正的识别结果

        Raises:
            IdentificationError: 识别失败（AI 调用失败或输出不合法）
        """
        start_time = time.monotonic()

        # ── 阶段一：输入预处理 ──
        logger.info("阶段一：输入预处理 — hazard_no=%s", input_data.hazard_no)
        has_photos = bool(input_data.defect_photos)

        # ── 阶段1.5：加载知识库 ──
        if not self.knowledge_context and self.config.enable_knowledge:
            logger.info("阶段1.5：知识库未提供，使用空上下文（集成层应在调用前注入）")

        # ── 阶段二：AI 分析 ──
        logger.info("阶段二：AI 分析 — has_photos=%s has_knowledge=%s",
                     has_photos, bool(self.knowledge_context))

        if has_photos and self.config.enable_vision:
            raw_output = await self._call_vision_ai(input_data)
        else:
            raw_output = await self._call_text_ai(input_data)

        # ── 阶段三：解析 & 验证 ──
        logger.info("阶段三：解析输出并规则验证")
        output = self._parse_output(raw_output)

        # 自动修正
        output = auto_correct(output)

        # 规则验证
        validation = self.rule_engine.validate(input_data, output)
        if not validation.is_valid:
            error_detail = "; ".join(validation.errors)
            if self.config.strict_mode:
                raise IdentificationError(
                    f"AI 输出验证失败: {error_detail}\n"
                    f"原始输出: {_json.dumps(raw_output, ensure_ascii=False, default=str)[:500]}"
                )
            else:
                logger.warning("AI 输出验证失败（非严格模式，继续返回）: %s", error_detail)

        # ── 阶段四：返回结果 ──
        elapsed = time.monotonic() - start_time
        logger.info(
            "识别完成 — hazard_no=%s type=%s category=%s level=%s elapsed=%.2fs",
            input_data.hazard_no,
            output.hazard_type.value,
            output.hazard_category.value,
            output.hazard_level.value,
            elapsed,
        )

        return output

    async def identify_batch(
        self,
        inputs: list[HazardIdentificationInput],
    ) -> list[HazardIdentificationOutput]:
        """批量识别（顺序执行，不并发以避免 API 限流）。

        Args:
            inputs: 多条隐患记录的输入

        Returns:
            与输入顺序对应的识别结果列表
        """
        results: list[HazardIdentificationOutput] = []
        for i, input_data in enumerate(inputs):
            logger.info("批量识别 [%d/%d]: %s", i + 1, len(inputs), input_data.hazard_no)
            try:
                result = await self.identify(input_data)
                results.append(result)
            except IdentificationError as e:
                logger.error("批量识别 [%d/%d] 失败: %s", i + 1, len(inputs), e)
                raise
        return results

    # ── 内部方法 ──

    async def _call_text_ai(self, input_data: HazardIdentificationInput) -> dict:
        """纯文本模式 AI 调用。"""
        context = build_context_text(
            hazard_no=input_data.hazard_no,
            description=input_data.description,
            department=input_data.department,
            location=input_data.location,
            discovered_by_name=input_data.discovered_by_name,
            discovered_at=(
                input_data.discovered_at.strftime("%Y-%m-%d %H:%M")
                if input_data.discovered_at else None
            ),
        )

        prompt = build_full_prompt(
            context, vision_mode=False, include_fewshot=True,
            knowledge_context=self.knowledge_context,
        )
        expected_keys = get_expected_keys()

        messages = [
            {"role": "system", "content": SYSTEM_ROLE},
            {"role": "user", "content": prompt},
        ]

        try:
            return await self.ai_service.chat_parsed(
                messages=messages,
                expected_keys=expected_keys,
                temperature=self.config.temperature,
            )
        except Exception as e:
            logger.error("文本 AI 调用失败: %s", e)
            raise IdentificationError(f"AI 文本分析失败: {e}") from e

    async def _call_vision_ai(self, input_data: HazardIdentificationInput) -> dict:
        """多模态 AI 调用（带图片）。"""
        context = build_vision_context_text(
            hazard_no=input_data.hazard_no,
            description=input_data.description,
            department=input_data.department,
            location=input_data.location,
        )

        expected_keys = get_expected_keys()

        try:
            # 检查 AI 服务是否支持 vision
            if hasattr(self.ai_service, "chat_vision_parsed"):
                return await self.ai_service.chat_vision_parsed(
                    text_prompt=build_full_prompt(
                        context, vision_mode=True, include_fewshot=True,
                        knowledge_context=self.knowledge_context,
                    ),
                    image_urls=input_data.defect_photos,
                    expected_keys=expected_keys,
                    temperature=self.config.temperature,
                )

            # Fallback: 将图片信息嵌入文本 prompt
            logger.warning("AI 服务不支持 vision，降级为纯文本模式")
            fallback_desc = input_data.description
            if input_data.defect_photos:
                fallback_desc += (
                    f"\n（附缺陷照片 {len(input_data.defect_photos)} 张，"
                    f"因当前模型不支持视觉分析，请基于文本描述进行判断）"
                )
            fallback_input = HazardIdentificationInput(
                hazard_no=input_data.hazard_no,
                description=fallback_desc,
                department=input_data.department,
                location=input_data.location,
                discovered_by_name=input_data.discovered_by_name,
                discovered_at=input_data.discovered_at,
                defect_photos=[],  # 清空图片，走纯文本
            )
            return await self._call_text_ai(fallback_input)

        except Exception as e:
            logger.error("多模态 AI 调用失败: %s", e)
            raise IdentificationError(f"AI 视觉分析失败: {e}") from e

    def _parse_output(self, raw: dict) -> HazardIdentificationOutput:
        """将 AI 返回的字典解析为强类型输出。"""
        try:
            # 解析枚举
            from app.modules.safety.ai_hazard_identification.schemas import (
                HazardCategoryEnum,
                HazardLevelEnum,
                HazardTypeEnum,
            )

            # 如果 rectification_suggestion 是字符串（某些模型可能这样返回），做兼容处理
            rs = raw.get("rectification_suggestion", {})
            if isinstance(rs, str):
                # 尝试 JSON 解析
                try:
                    rs = _json.loads(rs)
                except (_json.JSONDecodeError, TypeError):
                    rs = {"corrective": rs, "preventive": ""}

            return HazardIdentificationOutput(
                key_defect=raw.get("key_defect", ""),
                hazard_type=HazardTypeEnum(raw.get("hazard_type", "")),
                hazard_category=HazardCategoryEnum(raw.get("hazard_category", "")),
                hazard_level=HazardLevelEnum(raw.get("hazard_level", "")),
                rectification_suggestion=RectificationSuggestion(
                    corrective=rs.get("corrective", ""),
                    preventive=rs.get("preventive", ""),
                ),
                major_hazard_basis=raw.get("major_hazard_basis", ""),
                confidence=raw.get("confidence") if self.config.enable_reasoning else None,
                reasoning=raw.get("reasoning") if self.config.enable_reasoning else None,
            )
        except (ValueError, KeyError, TypeError) as e:
            raise IdentificationError(
                f"AI 输出解析失败: {e}\n"
                f"原始输出: {_json.dumps(raw, ensure_ascii=False, default=str)[:500]}"
            ) from e
