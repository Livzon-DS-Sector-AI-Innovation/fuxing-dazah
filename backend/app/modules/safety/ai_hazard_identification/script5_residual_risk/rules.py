"""脚本5 ResidualRiskAssessor — LEC 输出规则验证器。

在脚本3的 LEC 验证基础上，增加残余风险特有的约束：
- 残余风险不应高于固有风险
- 保守原则检查（无依据不得大幅降分）
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script5_residual_risk.schemas import (
    ResidualRiskInput,
    ResidualRiskOutput,
)

logger = logging.getLogger(__name__)

RISK_LEVEL_RANGES = {
    "level_1": (320, float("inf")),
    "level_2": (160, 320),
    "level_3": (70, 160),
    "level_4": (0, 70),
}


class ResidualRiskRuleEngine:
    """脚本5 LEC 输出规则验证器。"""

    def validate(
        self,
        input_data: ResidualRiskInput,
        output: ResidualRiskOutput,
    ) -> list[str]:
        """验证 AI 输出的残余风险 LEC 评价。"""
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

        # 4. 残余风险不应高于固有风险（保守约束）
        if (
            lec.d_value is not None
            and input_data.d_inherent is not None
            and lec.d_value > input_data.d_inherent * 1.05  # 容忍 5%
        ):
            errors.append(
                f"残余风险 D={lec.d_value} 高于固有风险 D={input_data.d_inherent}，"
                "措施不应增加风险"
            )

        # 5. 保守原则 — 无措施不得大幅降低 C 值
        if lec.c_value is not None and input_data.c_inherent is not None:
            if (
                lec.c_value < input_data.c_inherent * 0.5
                and "防爆" not in (input_data.existing_engineering_controls or "")
                and "泄压" not in (input_data.existing_engineering_controls or "")
            ):
                logger.warning(
                    "残余 C=%s 较固有 C=%s 下降超过 50%%，"
                    "但未发现可降低后果严重性的工程措施（防爆/泄压），请人工审核",
                    lec.c_value, input_data.c_inherent,
                )

        return errors


def auto_correct(output: ResidualRiskOutput) -> ResidualRiskOutput:
    """自动修正 LEC 输出（计算 D = L×E×C）。"""
    lec = output.lec
    if all(v is not None for v in (lec.l_value, lec.e_value, lec.c_value)):
        calculated_d = lec.l_value * lec.e_value * lec.c_value
        if lec.d_value is None or abs(lec.d_value - calculated_d) / max(calculated_d, 0.01) > 0.1:
            lec.d_value = calculated_d
    return output
