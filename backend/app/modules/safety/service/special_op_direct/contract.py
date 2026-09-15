"""特殊作业日报「直读多维表格」新列契约（列名 / 类型 / 选项 / 值映射）。

规格：.scratch/special-op-direct/spec.md「新增列规格」。

单一事实来源：建列脚本 ``backend/scripts/tmp/ensure_special_op_risk_field.py``
与日报回写共用本模块常量，避免「脚本建出的列」与「代码写入的列」漂移。
"""

from __future__ import annotations

from typing import Any

# 飞书 Bitable 字段类型：3 = 单选（SingleSelect）
FIELD_TYPE_SINGLE_SELECT = 3

RISK_FIELD_NAME = "日报风险等级（AI）"
RISK_FIELD_OPTIONS: tuple[str, ...] = ("高风险", "中风险", "低风险")

# 平台内部等级 -> Bitable 选项文案（只回写这一列）
RISK_LEVEL_TO_OPTION: dict[str, str] = {
    "high": "高风险",
    "medium": "中风险",
    "low": "低风险",
}
OPTION_TO_RISK_LEVEL: dict[str, str] = {
    option: level for level, option in RISK_LEVEL_TO_OPTION.items()
}


def create_field_property() -> dict[str, Any]:
    """建列请求体里的 ``property``（单选选项，顺序即展示顺序）。"""
    return {"options": [{"name": name} for name in RISK_FIELD_OPTIONS]}


def option_for_risk_level(level: str | None) -> str | None:
    """平台等级 -> 回写文案；空值或未知等级返回 None（表示不回写）。"""
    if not level:
        return None
    return RISK_LEVEL_TO_OPTION.get(level)
