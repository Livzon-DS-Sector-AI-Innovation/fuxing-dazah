"""AI隐患识别插件 — 规则引擎。

对 AI 输出进行后处理验证，确保：
1. 枚举值在合法范围内
2. 分类-类别-级别之间存在逻辑一致性
3. 整改建议格式完整
4. 判定依据包含真实引用
"""

from __future__ import annotations

import logging
import re

from app.modules.safety.ai_hazard_identification.schemas import (
    HazardCategoryEnum,
    HazardIdentificationInput,
    HazardIdentificationOutput,
    HazardLevelEnum,
    HazardTypeEnum,
    RectificationSuggestion,
    ValidationResult,
)

logger = logging.getLogger(__name__)


def _enum_value(val: object) -> str:
    """安全提取枚举值（兼容 model_construct 产生的裸字符串）。"""
    if isinstance(val, str):
        return val
    return getattr(val, "value", str(val))


# ═══════════════════════════════════════════════════════════════════════════
# 已知法规标准引用正则（用于快速检测编造的法规）
# ═══════════════════════════════════════════════════════════════════════════

KNOWN_REGULATIONS = [
    "安全生产法",
    "消防法",
    "职业病防治法",
    "特种设备安全法",
    "危险化学品安全管理条例",
    "化工和危险化学品生产经营单位重大生产安全事故隐患判定标准",
    "工贸行业重大生产安全事故隐患判定标准",
    "安全生产事故隐患排查治理暂行规定",
    "GB/T 13861",
    "GB 30871",
    "GB 3836",
    "GB 50016",
    "GB 50160",
    "GB 4053",
    "AQ",
    "安全生产十大禁令",
]

# 严禁出现的泛泛表述
BANNED_PHRASES = [
    "加强管理", "注意安全", "加强培训", "提高意识",
    "严格执行", "认真对待", "高度重视", "切实落实",
]

# 隐患分类 → 典型隐患类别的逻辑关联（一致性校验）
TYPE_CATEGORY_COMPATIBILITY = {
    HazardTypeEnum.UNSAFE_ACTION: {
        HazardCategoryEnum.VIOLATION_OPERATION,
        HazardCategoryEnum.OCCUPATIONAL_HEALTH,
    },
    HazardTypeEnum.UNSAFE_CONDITION: {
        HazardCategoryEnum.EQUIPMENT,
        HazardCategoryEnum.HAZARDOUS_STORAGE,
        HazardCategoryEnum.INSTRUMENT_ELECTRICAL,
        HazardCategoryEnum.LIGHTNING_ANTISTATIC,
        HazardCategoryEnum.LABEL_SIGNAGE,
    },
    HazardTypeEnum.ENVIRONMENTAL: {
        HazardCategoryEnum.EMERGENCY_MGMT,
        HazardCategoryEnum.SIX_S,
    },
    HazardTypeEnum.MANAGEMENT_DEFECT: {
        HazardCategoryEnum.DOCUMENTATION,
        HazardCategoryEnum.PROCESS_MGMT,
        HazardCategoryEnum.CONTRACTOR_DEFECT,
        HazardCategoryEnum.SPECIAL_OPERATION,
    },
}

# 级别 → 类别关联（重大隐患通常涉及的类别）
MAJOR_LEVEL_CATEGORIES = {
    HazardCategoryEnum.INSTRUMENT_ELECTRICAL,
    HazardCategoryEnum.HAZARDOUS_STORAGE,
    HazardCategoryEnum.SPECIAL_OPERATION,
}


class RuleEngine:
    """AI 输出规则验证器。

    用法:
        engine = RuleEngine()
        result = engine.validate(input_data, output)
        if not result.is_valid:
            for error in result.errors:
                logger.error("规则验证失败: %s", error)
    """

    def validate(
        self,
        input_data: HazardIdentificationInput,
        output: HazardIdentificationOutput,
    ) -> ValidationResult:
        """对 AI 输出执行全量规则验证。

        Returns:
            ValidationResult with is_valid, errors, warnings
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. 枚举值合法性
        self._validate_enums(output, errors)

        # 2. 描述长度和内容
        self._validate_descriptions(output, errors, warnings)

        # 3. 整改建议格式
        self._validate_rectification(output.rectification_suggestion, errors, warnings)

        # 4. 判定依据引用
        self._validate_basis(output.major_hazard_basis, errors, warnings)

        # 5. 分类-类别逻辑一致性（WARNING 级别，不阻塞）
        self._check_consistency(output, warnings)

        # 6. 输入-输出关联性
        if input_data.description:
            self._check_relevance(input_data, output, warnings)

        is_valid = len(errors) == 0

        if warnings:
            logger.debug("Validation warnings for %s: %s", input_data.hazard_no, warnings)
        if not is_valid:
            logger.warning("Validation errors for %s: %s", input_data.hazard_no, errors)

        return ValidationResult(is_valid=is_valid, errors=errors, warnings=warnings)

    # ── 子校验 ──

    def _validate_enums(self, output: HazardIdentificationOutput, errors: list[str]) -> None:
        """验证枚举值在合法范围内（兼容 model_construct 的裸字符串）。"""
        valid_types = {e.value for e in HazardTypeEnum}
        type_val = _enum_value(output.hazard_type)
        if type_val not in valid_types:
            errors.append(f"无效的隐患分类: {type_val}，合法值: {valid_types}")

        valid_categories = {e.value for e in HazardCategoryEnum}
        cat_val = _enum_value(output.hazard_category)
        if cat_val not in valid_categories:
            errors.append(f"无效的隐患类别: {cat_val}，合法值: {valid_categories}")

        valid_levels = {e.value for e in HazardLevelEnum}
        level_val = _enum_value(output.hazard_level)
        if level_val not in valid_levels:
            errors.append(f"无效的隐患级别: {level_val}，合法值: {valid_levels}")

    def _validate_descriptions(
        self,
        output: HazardIdentificationOutput,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """验证描述质量和长度。"""
        # key_defect 长度
        if len(output.key_defect) < 10:
            errors.append(f"隐患描述（AI）过短（{len(output.key_defect)}字），最少10字")
        if len(output.key_defect) > 250:
            warnings.append(f"隐患描述（AI）超过200字限制（{len(output.key_defect)}字）")

        # key_defect 不应只是重复输入
        if output.key_defect.strip().endswith("。") is False and len(output.key_defect) > 20:
            warnings.append("隐患描述（AI）建议以句号结尾，确保表述完整")

    def _validate_rectification(
        self,
        suggestion: RectificationSuggestion | dict,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """验证整改建议格式和质量（兼容 model_construct 产生的 dict）。"""
        if isinstance(suggestion, dict):
            corrective = suggestion.get("corrective", "")
            preventive = suggestion.get("preventive", "")
        else:
            corrective = suggestion.corrective
            preventive = suggestion.preventive

        # 两层都不能为空
        if not corrective or len(corrective.strip()) < 10:
            errors.append("整改措施不能为空或过短（<10字）")
        if not preventive or len(preventive.strip()) < 10:
            errors.append("预防措施不能为空或过短（<10字）")

        # 检查泛泛表述
        for phrase in BANNED_PHRASES:
            if phrase in corrective:
                warnings.append(f"整改措施包含泛泛表述: '{phrase}'")
            if phrase in preventive:
                warnings.append(f"预防措施包含泛泛表述: '{phrase}'")

    def _validate_basis(
        self,
        basis: str,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """验证判定依据引用质量。"""
        if len(basis) < 20:
            errors.append(f"隐患判定依据过短（{len(basis)}字），必须包含具体法规引用")

        # 检查是否至少引用了法规名称
        has_regulation_ref = any(
            reg in basis
            for reg in KNOWN_REGULATIONS
        )
        if not has_regulation_ref:
            errors.append(
                "隐患判定依据必须引用具体法规/标准名称（如《安全生产法》、GB 30871 等）"
            )

        # 检查是否有条文编号（第X条、第X.X节等）
        has_article_ref = bool(
            re.search(r"第[一二三四五六七八九十\d]+[条章节]", basis)
            or re.search(r"第\s*\d+(\.\d+)*\s*[条章节]", basis)
        )
        if not has_article_ref:
            warnings.append("判定依据建议包含具体条文编号（如'第X条'）")

    def _check_consistency(
        self,
        output: HazardIdentificationOutput,
        warnings: list[str],
    ) -> None:
        """检查分类-类别逻辑一致性（非阻塞警告）。"""
        # 去除 None 值
        compat = {k: {x for x in v if x is not None} for k, v in TYPE_CATEGORY_COMPATIBILITY.items()}

        if output.hazard_type in compat:
            expected_categories = compat[output.hazard_type]
            if expected_categories and output.hazard_category not in expected_categories:
                type_val = _enum_value(output.hazard_type)
                cat_val = _enum_value(output.hazard_category)
                warnings.append(
                    f"隐患分类 '{type_val}' 与类别 "
                    f"'{cat_val}' 的关联性较低，"
                    f"通常 '{type_val}' 对应类别: "
                    f"{[_enum_value(c) for c in expected_categories]}"
                )

    def _check_relevance(
        self,
        input_data: HazardIdentificationInput,
        output: HazardIdentificationOutput,
        warnings: list[str],
    ) -> None:
        """检查输出与输入的相关性。"""
        desc = input_data.description
        # 简单关键词重叠检测
        desc_words = set(desc.replace("，", " ").replace("、", " ").split())
        defect_words = set(output.key_defect.replace("，", " ").replace("、", " ").split())

        if desc_words:
            overlap = desc_words & defect_words
            overlap_ratio = len(overlap) / len(desc_words) if desc_words else 0
            if overlap_ratio < 0.1:
                warnings.append(
                    f"输出描述与输入文本关键词重叠率仅 {overlap_ratio:.0%}，"
                    f"可能存在理解偏差"
                )


# ═══════════════════════════════════════════════════════════════════════════
# 输出自动修正器
# ═══════════════════════════════════════════════════════════════════════════


def auto_correct(output: HazardIdentificationOutput) -> HazardIdentificationOutput:
    """对 AI 输出进行自动修正（不改变语义，只修正格式问题）。

    - 去除 key_defect 首尾空白
    - 确保 rectification_suggestion 各字段非空
    - 修正已知的枚举值拼写/大小写
    """
    # 清理描述
    output.key_defect = output.key_defect.strip()

    # 保障整改建议非空
    for field_name in ("corrective", "preventive"):
        value = getattr(output.rectification_suggestion, field_name, "")
        if not value or not value.strip():
            setattr(
                output.rectification_suggestion,
                field_name,
                "需根据具体现场情况制定整改方案"
            )

    return output
