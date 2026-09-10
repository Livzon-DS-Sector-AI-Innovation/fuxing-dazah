"""脚本4 ControlMeasureExtractor — 输出规则验证器。

验证 AI 推导的控制措施质量：
1. 四维度不能全部为「待人工确认」
2. 禁止空泛/含糊表述词汇（建议/推荐/可考虑/宜/最好）
3. 每项措施长度检查
4. PPE 维度不应包含工程/管理措施描述
5. （宽松，不阻断）措施-风险对应软检查：维度完全缺少依据标注时仅记日志告警
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script4_controls.schemas import (
    ControlsInput,
    ControlsOutput,
)

logger = logging.getLogger(__name__)

UNCONFIRMED = "待人工确认"

# 脚本4 角色已从「识别已有措施」翻转为「推导控制措施」，
# 允许 "应增加/需完善/需要补充" 等表述（推导缺失措施时的正当措辞），
# 仍禁止空泛、含糊、削弱措施确定性的措辞。
BANNED_IN_CONTROLS = [
    "建议", "推荐", "可考虑", "宜", "最好",
]


class ControlsRuleEngine:
    """脚本4 输出规则验证器。"""

    def validate(
        self,
        input_data: ControlsInput,
        output: ControlsOutput,
    ) -> list[str]:
        """验证 AI 输出。"""
        errors: list[str] = []

        fields: list[tuple[str, str]] = [
            ("engineering_controls", output.engineering_controls),
            ("management_controls", output.management_controls),
            ("ppe", output.ppe),
            ("emergency_measures", output.emergency_measures),
        ]

        # 1. 四个维度不能全部为「待人工确认」
        all_unconfirmed = all(
            (v or "").strip() == UNCONFIRMED for _, v in fields
        )
        if all_unconfirmed:
            errors.append("四个维度不能全部为「待人工确认」")

        # 2. 禁止空泛/含糊表述
        for label, value in fields:
            if value and value.strip() != UNCONFIRMED:
                for phrase in BANNED_IN_CONTROLS:
                    if phrase in value:
                        errors.append(
                            f"{label} 包含空泛/含糊表述 '{phrase}' — "
                            "脚本4 输出应为明确的控制措施，禁止空泛/含糊表述"
                        )

        # 3. 每个非空字段最低长度
        for label, value in fields:
            if value and value.strip() and value.strip() != UNCONFIRMED:
                if len(value.strip()) < 10:
                    errors.append(
                        f"{label} 过短（{len(value)}字），最少 10 字"
                    )

        # 4. PPE 维度不应包含工程或管理措施描述
        if output.ppe and output.ppe.strip() != UNCONFIRMED:
            ppe_text = output.ppe
            engineering_keywords = ["联锁", "报警器", "通风机", "安全阀", "爆破片"]
            for kw in engineering_keywords:
                if kw in ppe_text:
                    errors.append(
                        f"PPE 维度不应包含工程控制描述（检测到: '{kw}'），"
                        "请移至 engineering_controls"
                    )

        # 5.（宽松，不阻断）措施-风险对应软检查：仅当某维度完全没有依据标注时记告警。
        #    不作为 error —— strict_mode=True 下任何 error 都会阻断脚本4 落库，
        #    依据标注由 prompt + FEWSHOT 强约束、人工审核兜底，硬校验代价过高。
        for label, value in fields:
            if value and value.strip() != UNCONFIRMED:
                lines = [ln for ln in value.splitlines() if ln.strip()]
                if lines and not any(("针对事故" in ln or "针对行为" in ln) for ln in lines):
                    logger.warning(
                        "脚本4 %s 输出缺少「针对事故N/行为N」依据标注（软提醒，不阻断）",
                        label,
                    )

        return errors


def auto_correct(output: ControlsOutput) -> ControlsOutput:
    """自动修正 AI 输出。"""
    for field_name in (
        "engineering_controls", "management_controls",
        "ppe", "emergency_measures",
    ):
        value = getattr(output, field_name, None)
        if value is None or not value.strip():
            setattr(output, field_name, UNCONFIRMED)
        else:
            setattr(output, field_name, value.strip())

    return output
