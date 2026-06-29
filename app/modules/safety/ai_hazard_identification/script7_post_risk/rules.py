"""脚本7 PostMeasureAssessor — LEC 输出规则验证器。

在脚本3的 LEC 验证基础上，增加措施后风险特有约束：
- 措施后风险不应高于残余风险
- 建议措施的下降幅度与措施类型匹配
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script7_post_risk.schemas import (
    PostRiskInput,
    PostRiskOutput,
)

logger = logging.getLogger(__name__)

RISK_LEVEL_RANGES = {
    "level_1": (320, float("inf")),
    "level_2": (160, 320),
    "level_3": (70, 160),
    "level_4": (0, 70),
}

# 措施类型 → 预期最大降幅（相对于残余风险）
MEASURE_TYPE_MAX_REDUCTION = {
    "工程控制": {"l": 0.5, "e": 0.3, "c": 0.5},
    "管理控制": {"l": 0.2, "e": 0, "c": 0},
    "PPE": {"l": 0, "e": 0, "c": 0.3},
    "应急": {"l": 0, "e": 0, "c": 0.3},
    "综合": {"l": 0.5, "e": 0.3, "c": 0.5},
}


class PostRiskRuleEngine:
    """脚本7 LEC 输出规则验证器。"""

    def validate(
        self,
        input_data: PostRiskInput,
        output: PostRiskOutput,
    ) -> list[str]:
        """验证 AI 输出的措施后风险 LEC 评价。"""
        errors: list[str] = []
        lec = output.lec

        # 1. 全 null 检查
        if lec.is_unconfirmed:
            if lec.d_value is not None or lec.risk_level is not None:
                errors.append(
                    "L/E/C 中有 null 值，但 D 或 risk_level 不为 null"
                )
            return errors

        # 2. D = L×E×C 校验
        if all(v is not None for v in (lec.l_value, lec.e_value, lec.c_value, lec.d_value)):
            expected_d = lec.l_value * lec.e_value * lec.c_value
            if expected_d > 0:
                deviation = abs(lec.d_value - expected_d) / expected_d
                if deviation > 0.05:
                    errors.append(
                        f"D 值 {lec.d_value} 与 L×E×C={expected_d} 偏差 {deviation:.1%}"
                    )

        # 3. 风险等级与 D 值一致性
        if lec.d_value is not None and lec.risk_level is not None:
            ranges = RISK_LEVEL_RANGES.get(lec.risk_level)
            if ranges:
                min_d, max_d = ranges
                if not (min_d <= lec.d_value < max_d if max_d != float("inf") else lec.d_value >= min_d):
                    errors.append(
                        f"D 值 {lec.d_value} 与风险等级 {lec.risk_level} 不一致"
                    )

        # 4. 措施后风险不应高于残余风险
        if (
            lec.d_value is not None
            and input_data.d_residual is not None
            and lec.d_value > input_data.d_residual * 1.05
        ):
            errors.append(
                f"措施后风险 D={lec.d_value} 高于残余风险 D={input_data.d_residual}，"
                "建议措施不应增加风险"
            )

        # 5. 措施后风险不应高于固有风险（基本约束）
        if (
            lec.d_value is not None
            and input_data.d_inherent is not None
            and lec.d_value > input_data.d_inherent * 1.05
        ):
            errors.append(
                f"措施后风险 D={lec.d_value} 高于固有风险 D={input_data.d_inherent}，"
                "这不合理"
            )

        # 6. 措施类型对应的合理降幅检查
        if (
            input_data.recommendation_type
            and input_data.l_residual is not None and lec.l_value is not None
            and input_data.d_residual is not None and lec.d_value is not None
        ):
            limits = MEASURE_TYPE_MAX_REDUCTION.get(
                input_data.recommendation_type,
                {"l": 0.5, "e": 0.3, "c": 0.5},
            )
            if input_data.l_residual > 0:
                l_ratio = lec.l_value / input_data.l_residual
                max_l_ratio = 1 - limits["l"]
                if l_ratio < max_l_ratio and input_data.l_residual > 1:
                    logger.warning(
                        "措施后 L=%s 较残余 L=%s 下降 %.0f%%，超出 %s 类措施的预期降幅（%.0f%%）",
                        lec.l_value, input_data.l_residual,
                        (1 - l_ratio) * 100,
                        input_data.recommendation_type,
                        limits["l"] * 100,
                    )

        return errors


def auto_correct(output: PostRiskOutput) -> PostRiskOutput:
    """自动修正 LEC 输出（计算 D = L×E×C）。"""
    lec = output.lec
    if all(v is not None for v in (lec.l_value, lec.e_value, lec.c_value)):
        calculated_d = lec.l_value * lec.e_value * lec.c_value
        if lec.d_value is None or abs(lec.d_value - calculated_d) / max(calculated_d, 0.01) > 0.1:
            lec.d_value = calculated_d
    return output
