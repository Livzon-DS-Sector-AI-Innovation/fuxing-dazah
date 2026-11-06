"""AI隐患识别插件 — 规则引擎。

对 AI 输出进行后处理验证，确保：
1. 枚举值在合法范围内
2. 分类-类别-级别之间存在逻辑一致性
3. 整改建议格式完整
4. 判定依据包含真实引用

C2 引用来源强约束（2026-11-06）：`validate(..., citation_evidence=...)` 拿到
本轮检索证据时，额外校验「判定依据的引用能否在本轮 chunks 中找到出处」：
零可验证 / 纯占位变体 → error（触发 A4 带错误反馈重试一次）；部分不可验证 /
占位注记（但整体有可验证引用） → warning 不阻断；无证据时行为与现状完全一致。
"""

from __future__ import annotations

import logging
import re

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    verify_citations,
)
from app.modules.safety.ai_hazard_identification.citations import (
    has_citation,
    is_placeholder_variant,
)
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

# ── C2 引用强约束文案（重试反馈会原样回灌给 AI，勿随意改） ──
# 零可验证：疑似凭记忆编造 → error（strict 模式下触发反馈重试）
CITATION_UNVERIFIED_ERROR = (
    "判定依据的引用无法在本轮检索到的法规条款中验证（疑似凭记忆编造）："
    "{unverified}。请只引用本轮知识库片段中出现的法规名/条号/条文原文"
)
# 部分不可验证：可接受但建议修正 → warning（不触发重试，避免调用成本翻倍）
CITATION_UNVERIFIED_WARNING = (
    "判定依据部分引用无法在本轮检索到的法规条款中验证（可接受，建议修正）："
    "{unverified}"
)
# 纯占位变体（含注记且无任何可验证引用）→ error
PLACEHOLDER_BASIS_ERROR = (
    "判定依据包含「知识库中无相应条文」类占位文案，不得写入台账；"
    "知识库确无对应条文时应输出空字符串"
)
# 含占位注记但整体有可验证引用 → warning（可接受的补充说明）
PLACEHOLDER_BASIS_WARNING = (
    "判定依据含「知识库无相应条文」类占位注记，但同时包含可验证引用，"
    "属可接受的补充说明（不阻断）"
)
# C1：major 级别建议引用重大隐患判定标准 → warning（不阻断）
MAJOR_STANDARD_WARNING = (
    "隐患级别判定为重大，但判定依据未引用《重大隐患判定标准》对应条款"
    "（如重大生产安全事故隐患判定标准/AQ 3067/重大火灾隐患判定），"
    "建议补充重大标准依据（不阻断）"
)
# 重大标准特征：重大〔…〕隐患〔…〕判定标准 / 重大火灾隐患判定 / AQ 3067
_MAJOR_STANDARD_PATTERN = re.compile(
    r"重大[^，。；\n]{0,20}(?:隐患|火灾隐患)[^，。；\n]{0,10}判定标准"
    r"|重大火灾隐患判定"
    r"|AQ\s*3067",
    re.IGNORECASE,
)


def _unverified_summary(unverified: tuple[str, ...]) -> str:
    """不可验证引用摘要（最多 5 条、每条 ≤80 字，由 CitationReport 保证）。"""
    if not unverified:
        return "（无）"
    return "；".join(unverified)


def _enum_value(val: object) -> str:
    """安全提取枚举值（兼容 model_construct 产生的裸字符串）。"""
    if isinstance(val, str):
        return val
    return getattr(val, "value", str(val))


# key_defect 字段上限（与 HazardIdentificationOutput.max_length 对齐）。
# A4 字段级容错：超长仅截断该字段，不放大为整条识别失败。
KEY_DEFECT_MAX_LENGTH = 200

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
        *,
        citation_evidence: CitationEvidence | None = None,
    ) -> ValidationResult:
        """对 AI 输出执行全量规则验证。

        Args:
            input_data: 标准化输入
            output: AI 输出
            citation_evidence: 本轮检索证据。``None``（默认）表示不做引用来源
                校验，行为与 P0-A 完全一致；非 ``None`` 时启用 C2 引用强约束
                （零可验证 → error / 部分不可验证 → warning）。

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

        # 4. 判定依据引用（C2：可带本轮检索证据做强校验）
        self._validate_basis(
            output, errors, warnings, citation_evidence=citation_evidence
        )

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
        suggestion: RectificationSuggestion | dict[str, str],
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
        output: HazardIdentificationOutput,
        errors: list[str],
        warnings: list[str],
        *,
        citation_evidence: CitationEvidence | None = None,
    ) -> None:
        """验证判定依据引用质量（引用判定与 A3 质量闸门同源）。

        ``citation_evidence`` 非 ``None`` 时叠加 C2 引用来源强校验：
        - ``total_units == 0``：保留既有「必须引用」error（不新造文案），
          但占位判断照常执行（纯占位变体仍需 error）；
        - 零可验证：新增 error（疑似凭记忆编造 + 不可验证引用摘要）；
        - 部分不可验证：warning 不阻断；
        - 占位注记：无 verified → error；有 verified → warning（可接受补充说明）。
        """
        basis = output.major_hazard_basis or ""

        if len(basis) < 20:
            errors.append(f"隐患判定依据过短（{len(basis)}字），必须包含具体法规引用")

        # 与 A3 质量闸门共用 citations.has_citation，接受《》、标准号、
        # 〔YYYY〕N号、[YYYY]N号、第X条/第X.X条/X.X条等真实引用格式。
        if not has_citation(basis):
            errors.append(
                "隐患判定依据必须引用具体法规/标准名称（如《安全生产法》、GB 30871 等）"
            )

        # 检查是否有条文编号（第X条、第X.X节等）——仅 warning，不阻塞
        has_article_ref = bool(
            re.search(r"第[一二三四五六七八九十\d]+[条章节]", basis)
            or re.search(r"第\s*\d+(\.\d+)*\s*[条章节]", basis)
        )
        if not has_article_ref:
            warnings.append("判定依据建议包含具体条文编号（如'第X条'）")

        if citation_evidence is not None:
            self._validate_basis_citations(basis, errors, warnings, citation_evidence)

        # C1：major 级别建议引用重大隐患判定标准（warning，不阻断）
        if _enum_value(output.hazard_level) == HazardLevelEnum.MAJOR.value:
            if not _MAJOR_STANDARD_PATTERN.search(basis):
                warnings.append(MAJOR_STANDARD_WARNING)

    def _validate_basis_citations(
        self,
        basis: str,
        errors: list[str],
        warnings: list[str],
        citation_evidence: CitationEvidence,
    ) -> None:
        """C2 引用来源强校验（纯函数 verify_citations 判定，开销可忽略）。"""
        report = verify_citations(basis, citation_evidence)

        if report.total_units == 0:
            # 无引用单元：既有「必须引用」error 已覆盖，不新造文案
            pass
        elif not report.has_verified:
            errors.append(
                CITATION_UNVERIFIED_ERROR.format(
                    unverified=_unverified_summary(report.unverified_texts)
                )
            )
        elif not report.all_verified:
            warnings.append(
                CITATION_UNVERIFIED_WARNING.format(
                    unverified=_unverified_summary(report.unverified_texts)
                )
            )

        if is_placeholder_variant(basis):
            # M1 验收修复：仅书名号命中不算实质引用，需条号/引文/标准号可验证才放行
            if report.has_substantive_verified:
                warnings.append(PLACEHOLDER_BASIS_WARNING)
            else:
                errors.append(PLACEHOLDER_BASIS_ERROR)

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

    - 去除 key_defect 首尾空白；超 200 字截断到 200（字段级容错）
    - 确保 rectification_suggestion 各字段非空
    - 修正已知的枚举值拼写/大小写
    """
    # 清理描述；超长截断而非整条失败（A4）
    output.key_defect = output.key_defect.strip()[:KEY_DEFECT_MAX_LENGTH]

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
