"""AI 整改初审插件 — 核心引擎。

将审核流程实现为可独立运行、可测试的插件：
  阶段一：输入采集与预处理
  阶段二：多模态 AI 分析（对比 before/after 图片）
  阶段三：解析与规则验证
  阶段四：输出生成

用法:
    from app.modules.safety.ai_rectification_review import AIRectificationReviewer
    from app.platform.integrations.ai.client import AIService

    ai_service = AIService(api_key="...", base_url="...", model="...")
    plugin = AIRectificationReviewer(ai_service)

    input_data = RectificationReviewInput(
        original_description="防爆电箱堵头缺失",
        rectification_reply="已加装防爆堵头并用密封胶固定",
        rectification_photos=["https://..."],
    )

    output = await plugin.review(input_data)
    logger.debug("审查结论: %s", output.review_conclusion)
"""

from __future__ import annotations

import json as _json
import logging
import time
from typing import Any

from app.modules.safety.ai_rectification_review.prompts import (
    SYSTEM_ROLE,
    build_context_text,
    build_full_prompt,
    build_reply_context_text,
    get_expected_keys,
)
from app.modules.safety.ai_rectification_review.rules import (
    RuleEngine,
    auto_correct,
)
from app.modules.safety.ai_rectification_review.schemas import (
    PluginConfig,
    RectificationReviewInput,
    RectificationReviewOutput,
)

logger = logging.getLogger(__name__)


class ReviewError(Exception):
    """AI 初审失败异常。"""
    pass


class AIRectificationReviewer:
    """AI 整改初审插件 — 稳定、可复现、可独立测试。

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
        >>> plugin = AIRectificationReviewer(ai_service, knowledge_context="...")
        >>> output = await plugin.review(RectificationReviewInput(
        ...     original_description="防爆电箱堵头缺失",
        ...     rectification_reply="已加装防爆堵头并用密封胶固定",
        ... ))
    """

    def __init__(
        self,
        ai_service: Any,
        config: PluginConfig | None = None,
        knowledge_context: str | None = None,
    ):
        self.ai_service = ai_service
        self.config = config or PluginConfig()
        self.rule_engine = RuleEngine()
        self.knowledge_context = knowledge_context

    # ── 公共 API ──

    async def review(
        self,
        input_data: RectificationReviewInput,
    ) -> RectificationReviewOutput:
        """执行完整的 AI 整改初审流程。

        Args:
            input_data: 标准化输入（原始隐患信息 + 整改回复）

        Returns:
            经过规则验证和自动修正的审核结果

        Raises:
            ReviewError: 审核失败（AI 调用失败或输出不合法）
        """
        start_time = time.monotonic()

        # ── 阶段一：输入预处理 ──
        has_defect_photos = bool(input_data.original_defect_photos)
        has_rectification_photos = bool(input_data.rectification_photos)
        has_knowledge = bool(self.knowledge_context)

        logger.info(
            "阶段一：输入预处理 — defect_photos=%d rectification_photos=%d has_knowledge=%s",
            len(input_data.original_defect_photos),
            len(input_data.rectification_photos),
            has_knowledge,
        )

        # ── 阶段1.5：加载知识库 ──
        if not self.knowledge_context and self.config.enable_knowledge:
            logger.info("阶段1.5：知识库未提供，使用空上下文（集成层应在调用前注入）")

        # ── 阶段二：AI 分析 ──
        use_vision = (
            has_rectification_photos
            and self.config.enable_vision
        )

        logger.info(
            "阶段二：AI 分析 — use_vision=%s has_defect_photos=%s",
            use_vision, has_defect_photos,
        )

        if use_vision:
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
                raise ReviewError(
                    f"AI 输出验证失败: {error_detail}\n"
                    f"原始输出: {_json.dumps(raw_output, ensure_ascii=False, default=str)[:500]}"
                )
            else:
                logger.warning(
                    "AI 输出验证失败（非严格模式，继续返回）: %s", error_detail
                )

        # ── 阶段四：返回结果 ──
        elapsed = time.monotonic() - start_time
        logger.info(
            "初审完成 — conclusion=%s photo=%s quality=%s compliance=%s elapsed=%.2fs",
            output.review_conclusion.value,
            output.photo_match_level.value,
            output.measure_quality_level.value,
            output.standard_compliance_level.value,
            elapsed,
        )

        return output

    async def review_batch(
        self,
        inputs: list[RectificationReviewInput],
    ) -> list[RectificationReviewOutput]:
        """批量审核（顺序执行，不并发以避免 API 限流）。

        Args:
            inputs: 多条整改回复的输入

        Returns:
            与输入顺序对应的审核结果列表
        """
        results: list[RectificationReviewOutput] = []
        for i, input_data in enumerate(inputs):
            logger.info("批量审核 [%d/%d]", i + 1, len(inputs))
            try:
                result = await self.review(input_data)
                results.append(result)
            except ReviewError as e:
                logger.error("批量审核 [%d/%d] 失败: %s", i + 1, len(inputs), e)
                raise
        return results

    # ── 内部方法 ──

    async def _call_text_ai(self, input_data: RectificationReviewInput) -> dict:
        """纯文本模式 AI 调用（无整改后图片或 vision 不可用时）。"""
        context = build_context_text(
            original_description=input_data.original_description,
            key_defect=input_data.key_defect,
            hazard_type=input_data.hazard_type,
            hazard_category=input_data.hazard_category,
            hazard_level=input_data.hazard_level,
            department=input_data.department,
            ai_rectification_suggestion=input_data.ai_rectification_suggestion,
        )

        reply_context = build_reply_context_text(
            rectification_reply=input_data.rectification_reply,
            has_photos=False,
        )

        prompt = build_full_prompt(
            context=context,
            reply_context=reply_context,
            vision_mode=False,
            include_fewshot=True,
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
            raise ReviewError(f"AI 文本分析失败: {e}") from e

    async def _call_vision_ai(self, input_data: RectificationReviewInput) -> dict:
        """多模态 AI 调用（带整改后图片，进行 before/after 对比）。"""
        context = build_context_text(
            original_description=input_data.original_description,
            key_defect=input_data.key_defect,
            hazard_type=input_data.hazard_type,
            hazard_category=input_data.hazard_category,
            hazard_level=input_data.hazard_level,
            department=input_data.department,
            ai_rectification_suggestion=input_data.ai_rectification_suggestion,
        )

        reply_context = build_reply_context_text(
            rectification_reply=input_data.rectification_reply,
            has_photos=True,
        )

        expected_keys = get_expected_keys()

        try:
            # 组装图片列表：原始缺陷图片 + 整改后图片
            all_images = list(input_data.original_defect_photos) + list(
                input_data.rectification_photos
            )

            # 检查 AI 服务是否支持 vision
            if hasattr(self.ai_service, "chat_vision_parsed"):
                return await self.ai_service.chat_vision_parsed(
                    text_prompt=build_full_prompt(
                        context=context,
                        reply_context=reply_context,
                        vision_mode=True,
                        include_fewshot=True,
                        knowledge_context=self.knowledge_context,
                    ),
                    image_urls=all_images,
                    expected_keys=expected_keys,
                    temperature=self.config.temperature,
                )

            # Fallback: 将图片信息嵌入文本 prompt
            logger.warning("AI 服务不支持 vision，降级为纯文本模式")
            fallback_reply = input_data.rectification_reply
            defect_count = len(input_data.original_defect_photos)
            rect_count = len(input_data.rectification_photos)
            if rect_count > 0:
                fallback_reply += (
                    f"\n（附整改后现场照片 {rect_count} 张"
                    + (f"、原始缺陷照片 {defect_count} 张" if defect_count > 0 else "")
                    + "，因当前模型不支持视觉分析，请基于文本描述进行判断）"
                )
            fallback_input = RectificationReviewInput(
                hazard_id=input_data.hazard_id,
                original_description=input_data.original_description,
                original_defect_photos=[],  # 清空图片，走纯文本
                key_defect=input_data.key_defect,
                hazard_type=input_data.hazard_type,
                hazard_category=input_data.hazard_category,
                hazard_level=input_data.hazard_level,
                ai_rectification_suggestion=input_data.ai_rectification_suggestion,
                rectification_reply=fallback_reply,
                rectification_photos=[],  # 清空图片
                department=input_data.department,
            )
            return await self._call_text_ai(fallback_input)

        except Exception as e:
            logger.error("多模态 AI 调用失败: %s", e)
            raise ReviewError(f"AI 视觉分析失败: {e}") from e

    @staticmethod
    def _sanitize_enum_value(value: str | None) -> str:
        """清洗 AI 返回的枚举字符串：去除首尾空白和常见的尾部标点符号。

        AI 模型有时会在枚举值末尾附加标点（如 "不通过。"、"通过，"），
        导致 StrEnum 构造失败。此方法确保值在传入枚举前是干净的。
        """
        if not value:
            return ""
        # 去除首尾空白
        cleaned = value.strip()
        # 去除末尾常见的中英文标点符号（AI 模型容易附加的）
        trailing_punctuation = "。，！？,.!?;；：:"
        cleaned = cleaned.rstrip(trailing_punctuation)
        return cleaned.strip()

    def _parse_output(self, raw: dict) -> RectificationReviewOutput:
        """将 AI 返回的字典解析为强类型输出。

        对枚举字段做 sanitize 处理，避免因 AI 附加标点符号（如「不通过。」）
        导致枚举解析失败，进而触发异常链路将流程错误路由到人工复核。
        """
        try:
            from app.modules.safety.ai_rectification_review.schemas import (
                ComplianceLevel,
                MeasureQualityLevel,
                PhotoMatchLevel,
                ReviewConclusion,
            )

            return RectificationReviewOutput(
                defect_reassessment=raw.get("defect_reassessment", ""),
                defect_reassessment_level=raw.get("defect_reassessment_level", ""),
                photo_match_analysis=raw.get("photo_match_analysis", ""),
                photo_match_level=PhotoMatchLevel(
                    self._sanitize_enum_value(
                        raw.get("photo_match_level", "no_photos")
                    )
                ),
                measure_quality_assessment=raw.get(
                    "measure_quality_assessment", ""
                ),
                measure_quality_level=MeasureQualityLevel(
                    self._sanitize_enum_value(
                        raw.get("measure_quality_level", "basic")
                    )
                ),
                standard_compliance=raw.get("standard_compliance", ""),
                standard_compliance_level=ComplianceLevel(
                    self._sanitize_enum_value(
                        raw.get("standard_compliance_level", "basically_compliant")
                    )
                ),
                review_conclusion=ReviewConclusion(
                    self._sanitize_enum_value(
                        raw.get("review_conclusion", "不通过")
                    )
                ),
                review_comments=raw.get("review_comments", ""),
                confidence=(
                    raw.get("confidence")
                    if self.config.enable_reasoning
                    else None
                ),
                reasoning=(
                    raw.get("reasoning")
                    if self.config.enable_reasoning
                    else None
                ),
            )
        except (ValueError, KeyError, TypeError) as e:
            raise ReviewError(
                f"AI 输出解析失败: {e}\n"
                f"原始输出: {_json.dumps(raw, ensure_ascii=False, default=str)[:500]}"
            ) from e
