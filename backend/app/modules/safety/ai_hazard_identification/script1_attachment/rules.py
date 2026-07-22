"""脚本1 AttachmentParser — 输出规则验证器。

验证 AI 提取的作业信息质量：
1. 三个字段不能全部为空
2. 有附件内容时不能全部「待人工确认」
3. 每个字段满足最低长度要求
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script1_attachment.schemas import (
    AttachmentInput,
    AttachmentOutput,
)

logger = logging.getLogger(__name__)

UNCONFIRMED = "待人工确认"


class AttachmentRuleEngine:
    """脚本1 输出规则验证器。

    用法:
        engine = AttachmentRuleEngine()
        errors = engine.validate(input_data, output)
        if errors:
            for e in errors:
                logger.error("规则验证失败: %s", e)
    """

    def validate(
        self,
        input_data: AttachmentInput,
        output: AttachmentOutput,
    ) -> list[str]:
        """验证 AI 输出，返回错误列表（空列表 = 通过）。"""
        errors: list[str] = []

        fields: list[tuple[str, str]] = [
            ("specific_activity", output.specific_activity),
            ("equipment_facilities", output.equipment_facilities),
            ("raw_auxiliary_materials", output.raw_auxiliary_materials),
        ]

        # 1. 三个字段不能全部为空
        all_empty = all(not v or not v.strip() for _, v in fields)
        if all_empty:
            errors.append("三个输出字段不能全部为空")
            return errors  # 致命错误，后续检查无意义

        # 2. 若附件有实质内容但输出全是「待人工确认」→ 严重警告
        if input_data.attachment_text and len(input_data.attachment_text.strip()) > 100:
            all_unconfirmed = all(
                v.strip() == UNCONFIRMED for _, v in fields
            )
            if all_unconfirmed:
                errors.append(
                    f"附件包含 {len(input_data.attachment_text)} 字符内容，"
                    f"但三个输出字段全部为「{UNCONFIRMED}」，请重新分析附件"
                )

        # 3. 每个非「待人工确认」字段的最低长度校验
        for label, value in fields:
            if value and value.strip() and value.strip() != UNCONFIRMED:
                if len(value.strip()) < 5:
                    errors.append(
                        f"{label} 过短（当前 {len(value)} 字），最少 5 字"
                    )

        # 4. 来源标注检查（可选，非阻塞）
        for label, value in fields:
            if value and value.strip() and value.strip() != UNCONFIRMED:
                if "附件" not in value and "见第" not in value:
                    logger.debug(
                        "字段 %s 未标注附件来源页码，建议补充", label
                    )

        return errors


def auto_correct(output: AttachmentOutput) -> AttachmentOutput:
    """自动修正 AI 输出（格式层面，不改变语义）。

    - 去除各字段首尾空白
    - 保障字段非空（至少为「待人工确认」）
    """
    for field_name in ("specific_activity", "equipment_facilities", "raw_auxiliary_materials"):
        value = getattr(output, field_name, None)
        if value is None or not value.strip():
            setattr(output, field_name, UNCONFIRMED)
        else:
            setattr(output, field_name, value.strip())

    return output
