"""R1 消防候选规则声明 —— 白名单 ∪ 故障 ∪ 闭环（§9.1 拍板口径）。

字段名=消防表实测原始列名（2026-11-03 实测 16 列核实），修复冒烟③
``fields.原因分类`` 恒 None 的错位（基线 39→1 是错位产物）。
closure_class 由扫描源（scan_source）翻译进 ``payload._derived``——
文本语义判定在 Source 翻译层完成，规则引擎只判结构化值（零 AI、
无文本操作符需求，不改底座 evaluate_condition）。
"""

from __future__ import annotations

from typing import Any

from app.modules.safety.service.alarm_hazard_r1.closure import (
    CLOSURE_EMPTY,
    CLOSURE_EXPLICIT_TODO,
    CLOSURE_PENDING_HANDOVER,
)

#: R1 扫描源实例名（迁移播种的 agent_sources.name；规则 source 过滤依据）
R1_FIRE_SOURCE_NAME = "safety.fire_alarm.r1"

#: P1 拍板白名单（原因分类；边缘类 氮气引发/实验室操作 不进）
FIRE_CAUSE_ALLOWLIST = ("现场着火", "硫化氢引发", "氨水引发", "甲烷引发")
#: 计划内性质排除集（「测试性质」为同义脏值——白名单制必要性的实证）
FIRE_NATURE_EXCLUDE = ("测试报警", "测试性质", "演练引发")
#: 故障子规则的原因排除集（坑①：故障|测试 12 条计划内噪音）
FIRE_FAULT_RULE_EXCLUDE_CAUSES = ("测试", "演练引发")
FIRE_FAULT_NATURE = "故障报警"

#: 闭环子规则命中集合（§9.1：移交无回执/明示待办/处理情况空）
_CLOSURE_HITS = [CLOSURE_PENDING_HANDOVER, CLOSURE_EXPLICIT_TODO, CLOSURE_EMPTY]


def r1_fire_rule() -> dict[str, Any]:
    """消防候选规则声明（rule_id 沿用 fire_alarm_candidate；内容升版走 Policy 版本化）。"""
    return {
        "rule_id": "fire_alarm_candidate",
        "enabled": True,
        "source": R1_FIRE_SOURCE_NAME,
        "executor": "alarm_hazard_create",
        "conditions": [
            # 排除：性质 ∈ {测试报警, 测试性质, 演练引发}（计划内，最高优先级）
            {"field": "fields.报警性质", "op": "not_in", "values": list(FIRE_NATURE_EXCLUDE)},
            # 命中（并集）：原因白名单 ∪ 故障子规则 ∪ 闭环子规则
            {"any_of": [
                {"field": "fields.报警原因分类", "op": "in",
                 "values": list(FIRE_CAUSE_ALLOWLIST)},
                {"all_of": [
                    {"field": "fields.报警性质", "op": "equals",
                     "values": [FIRE_FAULT_NATURE]},
                    {"field": "fields.报警原因分类", "op": "not_in",
                     "values": list(FIRE_FAULT_RULE_EXCLUDE_CAUSES)},
                ]},
                {"field": "_derived.closure_class", "op": "in",
                 "values": _CLOSURE_HITS},
            ]},
        ],
    }
