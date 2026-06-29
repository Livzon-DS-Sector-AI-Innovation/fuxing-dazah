"""脚本2 HazardIdentifier — 输出规则验证器。

验证 AI 危险源辨识结果：
1. 危险类型必须在 GB 6441 14 类范围内
2. 不规范行为必须包含具体动作描述
3. 三个字段不能互相矛盾
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script2_hazard_id.prompts import (
    VALID_HAZARD_TYPES_6441,
)
from app.modules.safety.ai_hazard_identification.script2_hazard_id.schemas import (
    HazardIdInput,
    HazardIdOutput,
)

logger = logging.getLogger(__name__)

UNCONFIRMED = "待人工确认"

# 禁止出现的泛泛表述
BANNED_PHRASES = [
    "加强管理", "注意安全", "加强培训", "提高意识",
    "严格执行", "认真对待", "高度重视", "操作不当",
    "管理不善", "安全意识不足", "麻痹大意",
]


class HazardIdRuleEngine:
    """脚本2 输出规则验证器。"""

    def validate(
        self,
        input_data: HazardIdInput,
        output: HazardIdOutput,
    ) -> list[str]:
        """验证 AI 输出，返回错误列表（空列表 = 通过）。"""
        errors: list[str] = []

        # 1. 危险类型合法性
        if output.hazard_type and output.hazard_type.strip() != UNCONFIRMED:
            if output.hazard_type.strip() not in VALID_HAZARD_TYPES_6441:
                errors.append(
                    f"无效的危险类型 '{output.hazard_type}'，"
                    f"必须在 GB 6441 的 14 类范围内: {VALID_HAZARD_TYPES_6441}"
                )

        # 2. 三个字段不能全部为「待人工确认」
        all_unconfirmed = all(
            (v or "").strip() == UNCONFIRMED
            for v in [output.hazard_type, output.possible_accident, output.unsafe_behavior]
        )
        if all_unconfirmed:
            errors.append("三个输出字段不能全部为「待人工确认」")

        # 3. 不规范行为必须包含具体动词/动作描述
        behavior = (output.unsafe_behavior or "").strip()
        if behavior and behavior != UNCONFIRMED:
            if len(behavior) < 10:
                errors.append(
                    f"不规范行为描述过短（{len(behavior)}字），最少 10 字"
                )
            for phrase in BANNED_PHRASES:
                if phrase in behavior:
                    errors.append(
                        f"不规范行为包含泛泛表述: '{phrase}'，"
                        f"请输出具体的不安全动作/状态描述"
                    )

        # 4. 事故描述长度检查
        accident = (output.possible_accident or "").strip()
        if accident and accident != UNCONFIRMED and len(accident) < 10:
            errors.append(f"事故描述过短（{len(accident)}字），最少 10 字")

        # 5. 危险类型与事故描述的语义一致性检查
        if (
            output.hazard_type and output.hazard_type.strip() != UNCONFIRMED
            and output.possible_accident and output.possible_accident.strip() != UNCONFIRMED
        ):
            # 简单的关键词映射检查
            TYPE_ACCIDENT_KEYWORDS = {
                "灼烫": ["烫", "灼", "烧伤", "高温", "热", "酸", "碱", "腐蚀"],
                "机械伤害": ["卷入", "夹", "挤压", "切割", "剪切", "旋转", "转动"],
                "触电": ["电击", "触电", "漏电", "电"],
                "中毒和窒息": ["中毒", "窒息", "毒气", "有毒", "氮气", "缺氧"],
                "高处坠落": ["坠落", "跌落", "摔", "高空", "高处"],
                "火灾": ["火", "燃烧", "着火"],
                "容器爆炸": ["爆炸", "爆裂", "超压", "炸裂"],
                "物体打击": ["砸", "打击", "飞溅", "落下", "坠落物"],
            }
            expected_keywords = TYPE_ACCIDENT_KEYWORDS.get(output.hazard_type.strip(), [])
            if expected_keywords:
                match_found = any(kw in accident for kw in expected_keywords)
                if not match_found:
                    logger.warning(
                        "危险类型 '%s' 与事故描述关键词不匹配，事故描述: %s",
                        output.hazard_type, accident[:50],
                    )

        return errors


def auto_correct(output: HazardIdOutput) -> HazardIdOutput:
    """自动修正 AI 输出。"""
    for field_name in ("hazard_type", "possible_accident", "unsafe_behavior"):
        value = getattr(output, field_name, None)
        if value is None or not value.strip():
            setattr(output, field_name, UNCONFIRMED)
        else:
            setattr(output, field_name, value.strip())

    return output
