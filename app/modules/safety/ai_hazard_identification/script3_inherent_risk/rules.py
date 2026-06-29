"""脚本3 InherentRiskAssessor — LEC 输出规则验证器。

验证 AI 的 LEC 评分：
1. L/E/C 值在合法范围内（容忍 ±20% 偏差）
2. D = L × E × C（允许 ±5% 误差）
3. 风险等级与 D 值范围一致
4. 若 L/E/C 为 None → D 和 risk_level 也应为 None
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script3_inherent_risk.schemas import (
    VALID_C_VALUES,
    VALID_E_VALUES,
    VALID_L_VALUES,
    InherentRiskInput,
    InherentRiskOutput,
)

logger = logging.getLogger(__name__)

# 风险等级 D 值范围
RISK_LEVEL_RANGES = {
    "level_1": (320, float("inf")),
    "level_2": (160, 320),
    "level_3": (70, 160),
    "level_4": (0, 70),
}


def _is_close_to_valid(value: float, valid_set: list[float], tolerance: float = 0.2) -> bool:
    """检查 value 是否接近合法值（容忍 ±tolerance 比例偏差）。"""
    for valid in valid_set:
        if valid == 0:
            if abs(value) < 0.01:
                return True
        else:
            if abs(value - valid) / valid <= tolerance:
                return True
    return False


class InherentRiskRuleEngine:
    """脚本3 LEC 输出规则验证器。"""

    def validate(
        self,
        input_data: InherentRiskInput,
        output: InherentRiskOutput,
    ) -> list[str]:
        """验证 AI 输出的 LEC 评价。"""
        errors: list[str] = []
        lec = output.lec

        # 1. 全 null 检查（信息不足场景）
        if lec.is_unconfirmed:
            if lec.d_value is not None or lec.risk_level is not None:
                errors.append(
                    "L/E/C 中有 null 值，但 D 或 risk_level 不为 null — "
                    "信息不足时应全部为 null"
                )
            return errors

        # 2. L 值合法性（容忍 ±20% 偏差）
        if lec.l_value is not None and not _is_close_to_valid(lec.l_value, VALID_L_VALUES):
            errors.append(
                f"L 值 {lec.l_value} 不在合法范围内 {VALID_L_VALUES}（容忍 ±20%）"
            )

        # 3. E 值合法性
        if lec.e_value is not None and not _is_close_to_valid(lec.e_value, VALID_E_VALUES):
            errors.append(
                f"E 值 {lec.e_value} 不在合法范围内 {VALID_E_VALUES}（容忍 ±20%）"
            )

        # 4. C 值合法性
        if lec.c_value is not None and not _is_close_to_valid(lec.c_value, VALID_C_VALUES):
            errors.append(
                f"C 值 {lec.c_value} 不在合法范围内 {VALID_C_VALUES}（容忍 ±20%）"
            )

        # 5. D = L × E × C 校验（±5% 误差）
        if all(v is not None for v in (lec.l_value, lec.e_value, lec.c_value, lec.d_value)):
            expected_d = lec.l_value * lec.e_value * lec.c_value
            if expected_d > 0:
                deviation = abs(lec.d_value - expected_d) / expected_d
                if deviation > 0.05:
                    errors.append(
                        f"D 值 {lec.d_value} 与 L×E×C={expected_d} 偏差 {deviation:.1%}，"
                        f"超过 5% 容忍度"
                    )

        # 6. 风险等级与 D 值一致性
        if lec.d_value is not None and lec.risk_level is not None:
            ranges = RISK_LEVEL_RANGES.get(lec.risk_level)
            if ranges:
                min_d, max_d = ranges
                if not (min_d <= lec.d_value < max_d if max_d != float("inf") else lec.d_value >= min_d):
                    errors.append(
                        f"D 值 {lec.d_value} 与风险等级 {lec.risk_level} 不一致，"
                        f"预期区间: [{min_d}, {max_d})"
                    )

        # 7. 极端组合校验
        if all(v is not None for v in (lec.l_value, lec.e_value, lec.c_value)):
            if lec.l_value == 10 and lec.e_value == 10 and lec.c_value == 100:
                if lec.risk_level != "level_1":
                    errors.append("L=10, E=10, C=100 必须为 level_1（重大风险）")

        return errors


def auto_correct(output: InherentRiskOutput) -> InherentRiskOutput:
    """自动修正 LEC 输出（计算 D = L×E×C）。"""
    lec = output.lec
    if all(v is not None for v in (lec.l_value, lec.e_value, lec.c_value)):
        # 自动计算 D 值
        calculated_d = lec.l_value * lec.e_value * lec.c_value
        if lec.d_value is None or abs(lec.d_value - calculated_d) / max(calculated_d, 0.01) > 0.1:
            lec.d_value = calculated_d
    return output
