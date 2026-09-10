"""脚本3.5 FujianRiskAssessor — 输出规则验证器。

验证：
1. 七指标值域（必须在 FUJIAN_RISK_LABELS 内或为 None）
2. 非默认蓝指标（危险工艺/压力/温度/人员密度）全 null → risk_label 必须为 null
   （默认蓝三项 substance/layout/environment 信息不明确时按低风险处理，不参与全 null 判定）
3. risk_label 值域（必须在 FUJIAN_RISK_LABELS 内或为 None）
4. 风险最大化校验（risk_label 必须等于七指标非 null 项的最高等级）
"""

from __future__ import annotations

from app.modules.safety.ai_hazard_identification.script3_5_fujian_risk.schemas import (
    FUJIAN_DEFAULT_BLUE_FIELDS,
    FUJIAN_INDICATOR_FIELDS,
    FUJIAN_RISK_LABELS,
    FujianRiskInput,
    FujianRiskOutput,
)


def _present_valid_levels(output: FujianRiskOutput) -> list[str]:
    """七指标中非 null 且在合法等级内的值。

    非法等级值不参与风险最大化比较（避免 index() 抛 ValueError），
    非法值本身仍由 validate 的指标值域校验报错。
    """
    levels: list[str] = []
    for f in FUJIAN_INDICATOR_FIELDS:
        v = getattr(output, f)
        if v is not None and v in FUJIAN_RISK_LABELS:
            levels.append(v)
    return levels


def _non_default_blue_all_null(output: FujianRiskOutput) -> bool:
    """非默认蓝四项（危险工艺/压力/温度/人员密度）是否全 null。

    默认蓝三项（substance/layout/environment）信息不明确时按低风险处理，
    不参与全 null 判定——只有其余四项全 null 才视为信息不足。
    """
    return all(
        getattr(output, f) is None
        for f in FUJIAN_INDICATOR_FIELDS
        if f not in FUJIAN_DEFAULT_BLUE_FIELDS
    )


class FujianRiskRuleEngine:
    """脚本3.5 福建固有风险输出规则验证器。"""

    def validate(
        self,
        input_data: FujianRiskInput,
        output: FujianRiskOutput,
    ) -> list[str]:
        """验证 AI 输出的福建固有风险评级。"""
        errors: list[str] = []

        # 1. 七指标值域
        for f in FUJIAN_INDICATOR_FIELDS:
            v = getattr(output, f)
            if v is not None and v not in FUJIAN_RISK_LABELS:
                errors.append(
                    f"指标 {f} 值 '{v}' 不在合法等级 {list(FUJIAN_RISK_LABELS)} 内"
                )

        # 2. 非默认蓝四项全 null 一致性（信息不足场景）
        #    默认蓝三项（substance/layout/environment）信息不明确时按「低风险」处理，
        #    此时综合等级应为「低风险」（蓝色最低档），而非 null
        if _non_default_blue_all_null(output):
            if output.risk_label != "低风险":
                errors.append(
                    "危险工艺/压力/温度/人员密度 四项全 null — 默认蓝三项按低风险，"
                    "risk_label 应为「低风险」"
                )
            return errors

        # 3. risk_label 值域
        if output.risk_label is not None and output.risk_label not in FUJIAN_RISK_LABELS:
            errors.append(
                f"risk_label '{output.risk_label}' 不在合法等级 {list(FUJIAN_RISK_LABELS)} 内"
            )

        # 4. 风险最大化校验
        present = _present_valid_levels(output)
        if present and output.risk_label is not None:
            expected = max(present, key=FUJIAN_RISK_LABELS.index)
            if output.risk_label != expected:
                errors.append(
                    f"risk_label '{output.risk_label}' 与风险最大化结果 '{expected}' 不一致"
                )

        return errors


def auto_correct(output: FujianRiskOutput) -> FujianRiskOutput:
    """自动修正：
    1. 默认蓝三项（substance/layout/environment）信息不明确（None）→ 补为「低风险」
    2. 重算 risk_label = 七指标非 null 项的最高等级（风险最大化）

    与脚本3 的 D=L×E×C 兜底同构：在 _parse_output 之后、_validate 之前由
    BasePlugin.identify 自动调用，AI 漏算/错算也能兜底。
    """
    for f in FUJIAN_DEFAULT_BLUE_FIELDS:
        if getattr(output, f) is None:
            setattr(output, f, "低风险")
    present = _present_valid_levels(output)
    output.risk_label = (
        max(present, key=FUJIAN_RISK_LABELS.index) if present else None
    )
    return output
