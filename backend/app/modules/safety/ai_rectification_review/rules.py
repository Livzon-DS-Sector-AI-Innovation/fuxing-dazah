"""AI 整改初审插件 — 规则引擎。

对 AI 输出进行后处理验证，确保：
1. 枚举值在合法范围内
2. 各分析字段不低于最小字数
3. 无泛泛表述
4. 各维度之间存在逻辑一致性
5. 输出与输入存在关键词关联
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_rectification_review.schemas import (
    ComplianceLevel,
    MeasureQualityLevel,
    PhotoMatchLevel,
    RectificationReviewInput,
    RectificationReviewOutput,
    ReviewConclusion,
    ValidationResult,
)

logger = logging.getLogger(__name__)


def _enum_value(val: object) -> str:
    """安全提取枚举值（兼容 model_construct 产生的裸字符串）。"""
    if isinstance(val, str):
        return val
    return getattr(val, "value", str(val))


# ═══════════════════════════════════════════════════════════════════════════
# 严禁出现的泛泛表述（复用 AI 隐患识别插件的禁止短语列表）
# ═══════════════════════════════════════════════════════════════════════════

BANNED_PHRASES = [
    "加强管理", "注意安全", "加强培训", "提高意识",
    "严格执行", "认真对待", "高度重视", "切实落实",
]

# 各维度逻辑一致性规则（v2 — 实效导向）
# 硬性错误:
# - photo_match_level=unmatched → review_conclusion ≠ 通过
# - measure_quality=inadequate → review_conclusion ≠ 通过
# 降级为 warning:
# - photo_match_level=no_photos + 通过 → warning（文字可能具体可信）
# - compliance=non_compliant + 通过 → warning（标准合规是参考维度）


class RuleEngine:
    """AI 整改初审输出规则验证器。

    用法:
        engine = RuleEngine()
        result = engine.validate(input_data, output)
        if not result.is_valid:
            for error in result.errors:
                logger.error("规则验证失败: %s", error)
    """

    def validate(
        self,
        input_data: RectificationReviewInput,
        output: RectificationReviewOutput,
    ) -> ValidationResult:
        """对 AI 输出执行全量规则验证。"""
        errors: list[str] = []
        warnings: list[str] = []

        # v2：无需整改结论时跳过严格校验（缺陷本身非实质，不需要照片/措施合规）
        is_no_need = _enum_value(output.review_conclusion) == "无需整改"

        # 1. 枚举值合法性
        self._validate_enums(output, errors)

        # 2. 文本长度和质量（无需整改时仅校验 review_comments 非空）
        self._validate_text_fields(output, errors, warnings, skip_strict=is_no_need)

        # 3. 泛泛表述检测
        self._validate_banned_phrases(output, warnings)

        # 4. 逻辑一致性（无需整改时跳过）
        if not is_no_need:
            self._check_consistency(output, errors, warnings)

        # 5. 输入-输出关联性
        if input_data.original_description:
            self._check_relevance(input_data, output, warnings)

        is_valid = len(errors) == 0

        if warnings:
            logger.debug("Validation warnings: %s", warnings)
        if not is_valid:
            logger.warning("Validation errors: %s", errors)

        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

    # ── 子校验 ──

    def _validate_enums(
        self, output: RectificationReviewOutput, errors: list[str]
    ) -> None:
        """验证 5 个枚举值在合法范围内。"""
        valid_photo = {e.value for e in PhotoMatchLevel}
        photo_val = _enum_value(output.photo_match_level)
        if photo_val not in valid_photo:
            errors.append(
                f"无效的图片比对结论: {photo_val}，合法值: {valid_photo}"
            )

        valid_quality = {e.value for e in MeasureQualityLevel}
        quality_val = _enum_value(output.measure_quality_level)
        if quality_val not in valid_quality:
            errors.append(
                f"无效的措施质量等级: {quality_val}，合法值: {valid_quality}"
            )

        valid_compliance = {e.value for e in ComplianceLevel}
        compliance_val = _enum_value(output.standard_compliance_level)
        if compliance_val not in valid_compliance:
            errors.append(
                f"无效的合规等级: {compliance_val}，合法值: {valid_compliance}"
            )

        valid_conclusion = {e.value for e in ReviewConclusion}
        conclusion_val = _enum_value(output.review_conclusion)
        if conclusion_val not in valid_conclusion:
            errors.append(
                f"无效的审核结论: {conclusion_val}，合法值: {valid_conclusion}"
            )

    def _validate_text_fields(
        self,
        output: RectificationReviewOutput,
        errors: list[str],
        warnings: list[str],
        skip_strict: bool = False,
    ) -> None:
        """验证各文本字段的长度下限。

        skip_strict: 无需整改时跳过图片/措施/合规的长度校验，仅校验 review_comments。
        """
        if skip_strict:
            # 无需整改：仅要求 review_comments 非空
            text_checks = [
                ("AI初审结果", output.review_comments, 1),
            ]
        else:
            text_checks = [
                ("图片比对分析", output.photo_match_analysis, 50),
                ("措施有效性评估", output.measure_quality_assessment, 50),
                ("标准合规评估", output.standard_compliance, 30),
                ("AI初审结果", output.review_comments, 1),
            ]
        for field_name, text, min_len in text_checks:
            actual_len = len(text.strip())
            if actual_len < min_len:
                errors.append(
                    f"{field_name}过短（{actual_len}字），最少{min_len}字"
                )

    def _validate_banned_phrases(
        self,
        output: RectificationReviewOutput,
        warnings: list[str],
    ) -> None:
        """检测各文本字段中是否包含泛泛表述。"""
        text_fields = [
            ("整改回复文本", output.measure_quality_assessment),
            ("AI初审结果", output.review_comments),
        ]
        for field_name, text in text_fields:
            for phrase in BANNED_PHRASES:
                if phrase in text:
                    warnings.append(
                        f"{field_name}包含泛泛表述: '{phrase}'"
                    )

    def _check_consistency(
        self,
        output: RectificationReviewOutput,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """检查各维度之间的逻辑一致性。

        核心规则（硬性错误 — 无法消除隐患的情况）：
        - unmatched → 不能 通过（照片显示隐患仍存在）
        - inadequate → 不能 通过（无具体操作、逻辑上无法消除隐患）

        降级为 warning（允许有一定灵活度）：
        - no_photos + 通过 → warning（无照片但文字描述可能具体可信）
        - non_compliant + 通过 → warning（标准合规是参考维度，轻微偏差不影响判定）
        """
        conclusion = _enum_value(output.review_conclusion)
        photo = _enum_value(output.photo_match_level)
        quality = _enum_value(output.measure_quality_level)
        compliance = _enum_value(output.standard_compliance_level)

        if conclusion == ReviewConclusion.PASS.value:
            # 照片显示隐患仍存在 → 硬性不通过
            if photo == PhotoMatchLevel.UNMATCHED.value:
                errors.append(
                    "图片比对为 unmatched（缺陷仍存在或整改明显不到位）时评审判定不能为 通过"
                )

            # 措施无效（仅有空话）→ 硬性不通过
            if quality == MeasureQualityLevel.INADEQUATE.value:
                errors.append(
                    "措施有效性为 inadequate（无具体操作、逻辑上无法消除隐患）时评审判定不能为 通过"
                )

            # 无照片但文字描述可能具体可信 → 降级为 warning
            if photo == PhotoMatchLevel.NO_PHOTOS.value:
                warnings.append(
                    "无整改后图片但判定为通过，请确认文字描述足够具体可信以支撑判定"
                )

            # 标准不合规但其他维度可接受 → 降级为 warning（标准合规是参考维度）
            if compliance == ComplianceLevel.NON_COMPLIANT.value:
                warnings.append(
                    "标准合规为 non_compliant 但判定为通过，请确认不合规项不构成安全底线问题"
                )

        # 如果图片匹配且措施有效但结论为不通过，给出 warning
        if photo == PhotoMatchLevel.MATCHED.value and conclusion == ReviewConclusion.FAIL.value:
            if quality == MeasureQualityLevel.ADEQUATE.value:
                warnings.append(
                    "图片匹配且措施有效但判定为不通过，请确认驳回理由是否充分"
                )

    def _check_relevance(
        self,
        input_data: RectificationReviewInput,
        output: RectificationReviewOutput,
        warnings: list[str],
    ) -> None:
        """检查输出与输入的相关性。"""
        desc = input_data.original_description
        # 简单关键词重叠检测
        desc_words = set(desc.replace("，", " ").replace("、", " ").split())
        review_words = set(
            (output.review_comments + output.photo_match_analysis)
            .replace("，", " ").replace("、", " ").split()
        )

        if desc_words and review_words:
            overlap = desc_words & review_words
            overlap_ratio = len(overlap) / len(desc_words) if desc_words else 0
            if overlap_ratio < 0.05:
                warnings.append(
                    f"输出与原始隐患描述关键词重叠率仅 {overlap_ratio:.0%}，"
                    f"可能存在理解偏差"
                )


# ═══════════════════════════════════════════════════════════════════════════
# 输出自动修正器
# ═══════════════════════════════════════════════════════════════════════════


def auto_correct(
    output: RectificationReviewOutput,
) -> RectificationReviewOutput:
    """对 AI 输出进行自动修正（不改变语义，只修正格式问题）。

    - 去除各文本字段首尾空白
    - 保障关键字段非空
    """
    # 清理所有文本字段的首尾空白
    output.photo_match_analysis = output.photo_match_analysis.strip()
    output.measure_quality_assessment = output.measure_quality_assessment.strip()
    output.standard_compliance = output.standard_compliance.strip()
    output.review_comments = output.review_comments.strip()

    # 保障关键字段非空
    if not output.photo_match_analysis:
        output.photo_match_analysis = "未提供整改后图片，无法进行图片比对分析"

    if not output.measure_quality_assessment:
        output.measure_quality_assessment = "整改回复文本为空，无法评估措施有效性"

    if not output.standard_compliance:
        output.standard_compliance = "参照知识库标准，信息不足以进行合规判定"

    if not output.review_comments:
        output.review_comments = "不通过"

    return output
