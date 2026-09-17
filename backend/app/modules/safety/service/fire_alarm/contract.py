"""消防报警 AI 列契约（列名 / 类型 / 选项 / 中英值映射）。

单一事实来源：建列脚本与回写逻辑共用本模块常量，避免「脚本建出的列」与
「代码写入的列」漂移。

列规格（.scratch/fire-alarm-direct/spec.md）：

| 列名 | 类型 | 选项 | 平台字段 |
|---|---|---|---|
| AI维度 | 单选 | 工艺 / 人员操作 / 设备设施 / 其他 | ai_dimension |
| AI原因分析 | 多行文本 | 自由文本 | ai_reason_analysis |
| AI整改方向 | 多行文本 | 自由文本 | ai_rectification_direction |
| AI分析时间 | 日期 | 毫秒时间戳 | ai_analyzed_at |
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct.writer import FieldSpec

# Bitable 字段类型
FIELD_TYPE_TEXT = 1
FIELD_TYPE_SINGLE_SELECT = 3
FIELD_TYPE_DATE = 5

# 列名
AI_DIMENSION_FIELD = "AI维度"
AI_REASON_ANALYSIS_FIELD = "AI原因分析"
AI_RECTIFICATION_DIRECTION_FIELD = "AI整改方向"
AI_ANALYZED_AT_FIELD = "AI分析时间"

# 兼容短名（便于调用方按业务字段名引用）
AI_DIMENSION = AI_DIMENSION_FIELD
AI_REASON_ANALYSIS = AI_REASON_ANALYSIS_FIELD
AI_RECTIFICATION_DIRECTION = AI_RECTIFICATION_DIRECTION_FIELD
AI_ANALYZED_AT = AI_ANALYZED_AT_FIELD

AI_FIELD_NAMES: tuple[str, ...] = (
    AI_DIMENSION_FIELD,
    AI_REASON_ANALYSIS_FIELD,
    AI_RECTIFICATION_DIRECTION_FIELD,
    AI_ANALYZED_AT_FIELD,
)

# AI 维度：Bitable 选项中文 -> 平台英文枚举
AI_DIMENSION_OPTIONS: tuple[str, ...] = ("工艺", "人员操作", "设备设施", "其他")

AI_DIMENSION_OPTION_TO_CODE: dict[str, str] = {
    "工艺": "process",
    "人员操作": "operation",
    "设备设施": "equipment",
    "其他": "other",
}
AI_DIMENSION_CODE_TO_OPTION: dict[str, str] = {
    code: option for option, code in AI_DIMENSION_OPTION_TO_CODE.items()
}


def option_to_dimension(option: str | None) -> str | None:
    """Bitable「AI维度」选项 -> 平台英文枚举；空或未知返回 None。"""
    if not option:
        return None
    return AI_DIMENSION_OPTION_TO_CODE.get(option.strip())


def dimension_to_option(code: str | None) -> str | None:
    """平台英文枚举 -> Bitable「AI维度」选项；空或未知返回 None（不写该列）。"""
    if not code:
        return None
    return AI_DIMENSION_CODE_TO_OPTION.get(code.strip())


def dimension_field_property() -> dict[str, list[dict[str, str]]]:
    """单选字段 property：选项顺序即展示顺序。"""
    return {"options": [{"name": name} for name in AI_DIMENSION_OPTIONS]}


def build_field_specs() -> tuple[FieldSpec, ...]:
    """四个 AI 列的幂等建列契约，顺序与 spec 表格一致。"""
    return (
        FieldSpec(
            name=AI_DIMENSION_FIELD,
            field_type=FIELD_TYPE_SINGLE_SELECT,
            property_=dimension_field_property(),
        ),
        FieldSpec(name=AI_REASON_ANALYSIS_FIELD, field_type=FIELD_TYPE_TEXT),
        FieldSpec(name=AI_RECTIFICATION_DIRECTION_FIELD, field_type=FIELD_TYPE_TEXT),
        FieldSpec(name=AI_ANALYZED_AT_FIELD, field_type=FIELD_TYPE_DATE),
    )


AI_FIELD_SPECS: tuple[FieldSpec, ...] = build_field_specs()


__all__ = [
    "FIELD_TYPE_TEXT",
    "FIELD_TYPE_SINGLE_SELECT",
    "FIELD_TYPE_DATE",
    "AI_DIMENSION_FIELD",
    "AI_REASON_ANALYSIS_FIELD",
    "AI_RECTIFICATION_DIRECTION_FIELD",
    "AI_ANALYZED_AT_FIELD",
    "AI_DIMENSION",
    "AI_REASON_ANALYSIS",
    "AI_RECTIFICATION_DIRECTION",
    "AI_ANALYZED_AT",
    "AI_FIELD_NAMES",
    "AI_DIMENSION_OPTIONS",
    "AI_DIMENSION_OPTION_TO_CODE",
    "AI_DIMENSION_CODE_TO_OPTION",
    "option_to_dimension",
    "dimension_to_option",
    "dimension_field_property",
    "build_field_specs",
    "AI_FIELD_SPECS",
]
