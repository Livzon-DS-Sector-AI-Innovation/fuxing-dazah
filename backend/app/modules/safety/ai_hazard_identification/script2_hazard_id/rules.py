"""脚本2 HazardIdentifier — 输出规则验证器。

验证 AI 危险源辨识结果：
1. 危险类型必须命中 Bitable 预设 24 项（多选 1~5 个，按「、」连接）
2. 不规范行为必须包含具体动作描述
3. 三个字段不能互相矛盾
"""

from __future__ import annotations

import logging

from app.modules.safety.ai_hazard_identification.script2_hazard_id.prompts import (
    VALID_HAZARD_TYPES_BITABLE,
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

        # 危险类型多选拆分（Bitable「危险类型（AI）」多选，按「、」连接）
        hazard_types = (
            [t.strip() for t in output.hazard_type.split("、") if t.strip()]
            if output.hazard_type and output.hazard_type.strip() != UNCONFIRMED
            else []
        )

        # 1. 危险类型合法性（多选：逐个必须在预设 24 项内）
        invalid = [t for t in hazard_types if t not in VALID_HAZARD_TYPES_BITABLE]
        if invalid:
            errors.append(
                f"无效的危险类型 {invalid}，"
                f"必须从 Bitable 预设 24 项中选择: {VALID_HAZARD_TYPES_BITABLE}"
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

        # 5. 危险类型与事故描述的语义一致性检查（多选：逐项检查，软告警）
        if (
            hazard_types and accident and accident != UNCONFIRMED
        ):
            # 简单的关键词映射检查（键为 Bitable 预设选项名）
            TYPE_ACCIDENT_KEYWORDS = {
                "火灾爆炸": ["火", "燃烧", "着火", "爆炸", "爆燃"],
                "中毒窒息": ["中毒", "窒息", "毒气", "有毒", "氮气", "缺氧"],
                "触电": ["电击", "触电", "漏电", "电"],
                "机械伤害": ["卷入", "夹", "挤压", "切割", "剪切", "旋转", "转动"],
                "高处坠落": ["坠落", "跌落", "摔", "高空", "高处"],
                "腐蚀灼伤": ["腐蚀", "灼", "烫", "烧伤", "酸", "碱"],
                "车辆伤害": ["车辆", "叉车", "运输", "撞"],
                "环境污染": ["泄漏", "排放", "污染", "废水", "废气"],
                "容器爆炸": ["爆炸", "爆裂", "超压", "炸裂"],
                "静电危害": ["静电", "放电", "火花"],
                "物体打击": ["砸", "打击", "飞溅", "落下", "坠落物"],
                "泄漏危险": ["泄漏", "跑冒滴漏", "漏液", "漏气"],
                "粉尘爆炸": ["粉尘", "扬尘", "爆炸"],
                "高温烫伤": ["烫", "灼", "高温", "热"],
                "滑倒坠落": ["滑倒", "滑", "湿滑", "摔"],
                "化学灼伤": ["灼伤", "化学", "酸", "碱", "腐蚀"],
                "生物危害": ["生物", "感染", "病菌", "微生物"],
                "粉尘危害": ["粉尘", "扬尘", "吸入"],
                "噪声危害": ["噪声", "噪音", "听力"],
                "高压危险": ["高压", "超压", "压力"],
                "低温冻伤": ["冻伤", "低温", "液氮", "寒冷"],
                "火灾": ["火", "燃烧", "着火"],
                "其他爆炸": ["爆炸", "炸"],
                "其他": [],
            }
            for ht in hazard_types:
                keywords = TYPE_ACCIDENT_KEYWORDS.get(ht, [])
                if not keywords:
                    continue
                if not any(kw in accident for kw in keywords):
                    logger.warning(
                        "危险类型 '%s' 与事故描述关键词不匹配，事故描述: %s",
                        ht, accident[:50],
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
