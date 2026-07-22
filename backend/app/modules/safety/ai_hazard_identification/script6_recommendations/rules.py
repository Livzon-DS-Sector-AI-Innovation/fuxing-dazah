"""脚本6 RecommendationGenerator — 输出规则验证器。

验证 AI 生成的建议措施：
1. needs_recommendation 与残余风险等级的一致性
2. 建议措施必须具体可执行，不含泛泛表述
3. 不得重复现有控制措施
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script6_recommendations.schemas import (
    RecommendationInput,
    RecommendationOutput,
)

logger = logging.getLogger(__name__)

UNCONFIRMED = "待人工确认"

# 禁止出现的空泛表述
BANNED_PHRASES = [
    "加强管理", "注意安全", "加强培训", "提高意识",
    "严格执行", "认真对待", "高度重视", "切实落实",
    "进一步完善", "继续加强", "不断改进",
]

VALID_NEEDS = ["是", "否"]
VALID_TYPES = ["工程控制", "管理控制", "PPE", "应急", "综合"]
VALID_PRIORITIES = ["高", "中", "低"]


class RecommendationRuleEngine:
    """脚本6 输出规则验证器。"""

    def validate(
        self,
        input_data: RecommendationInput,
        output: RecommendationOutput,
    ) -> list[str]:
        """验证 AI 输出。"""
        errors: list[str] = []

        # 1. needs_recommendation 合法值
        if output.needs_recommendation.strip() not in VALID_NEEDS:
            errors.append(
                f"needs_recommendation 必须为 '是' 或 '否'，当前: '{output.needs_recommendation}'"
            )

        # 2. 残余风险 level_1/2 必须建议
        if (
            input_data.residual_risk_level in ("level_1", "level_2")
            and output.needs_recommendation.strip() == "否"
        ):
            errors.append(
                f"残余风险为 {input_data.residual_risk_level}（{input_data.residual_risk_label}），"
                "needs_recommendation 不能为「否」"
            )

        # 3. recommendation_type 合法值
        if output.recommendation_type.strip() not in VALID_TYPES:
            errors.append(
                f"recommendation_type 必须在 {VALID_TYPES} 中，当前: '{output.recommendation_type}'"
            )

        # 4. recommendation_priority 合法值
        if output.recommendation_priority.strip() not in VALID_PRIORITIES:
            errors.append(
                f"recommendation_priority 必须在 {VALID_PRIORITIES} 中，当前: '{output.recommendation_priority}'"
            )

        # 5. 建议内容不能为空或过短
        content = (output.recommendation_content or "").strip()
        if output.needs_recommendation.strip() == "是":
            if len(content) < 20:
                errors.append(
                    f"建议措施内容过短（{len(content)}字），最少 20 字"
                )
            for phrase in BANNED_PHRASES:
                if phrase in content:
                    errors.append(
                        f"建议措施包含空泛表述: '{phrase}'，请输出具体可执行的措施"
                    )

        # 6. 不能与现有控制措施完全相同（字符串级别检查）
        for existing_field in [
            ("existing_engineering_controls", "工程控制"),
            ("existing_management_controls", "管理控制"),
            ("existing_ppe", "PPE"),
            ("existing_emergency_measures", "应急"),
        ]:
            existing_val = getattr(input_data, existing_field[0], "") or ""
            if existing_val and existing_val.strip() != UNCONFIRMED:
                # 检查建议内容是否大段重复现有措施
                if len(existing_val) > 30 and existing_val[:50] in content:
                    errors.append(
                        f"建议措施与现有{existing_field[1]}措施内容重复"
                    )

        return errors


def auto_correct(output: RecommendationOutput) -> RecommendationOutput:
    """自动修正 AI 输出。"""
    for field_name in (
        "needs_recommendation", "recommendation_type",
        "recommendation_content", "recommendation_priority",
    ):
        value = getattr(output, field_name, None)
        if value is None or not value.strip():
            setattr(output, field_name, "待人工确认" if field_name != "needs_recommendation" else "是")
        else:
            setattr(output, field_name, value.strip())

    return output
