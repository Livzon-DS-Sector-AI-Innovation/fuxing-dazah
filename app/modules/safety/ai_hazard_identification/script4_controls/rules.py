"""脚本4 ControlMeasureExtractor — 输出规则验证器。

验证 AI 识别的控制措施质量：
1. 四维度不能全部为「待人工确认」
2. 禁止出现建议类表述词汇
3. 每项措施长度检查
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script4_controls.schemas import (
    ControlsInput,
    ControlsOutput,
)

logger = logging.getLogger(__name__)

UNCONFIRMED = "待人工确认"

# 禁止在现有措施中出现的建议类表述
BANNED_IN_CONTROLS = [
    "建议", "应增加", "需完善", "可考虑", "宜", "推荐",
    "最好", "应当增加", "需要补充", "有待加强",
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

        # 2. 禁止建议类表述
        for label, value in fields:
            if value and value.strip() != UNCONFIRMED:
                for phrase in BANNED_IN_CONTROLS:
                    if phrase in value:
                        errors.append(
                            f"{label} 包含建议类表述 '{phrase}' — "
                            "脚本4只输出已有措施，禁止建议"
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
