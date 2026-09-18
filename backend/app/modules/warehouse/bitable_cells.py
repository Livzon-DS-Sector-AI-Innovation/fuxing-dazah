"""Bitable 单元格值 → 文本/数值的规范解析（V3.0 分期A 从 agent/tools/query.py 抽出公开）。

Base 读取的字段值形态多样（records/search，测试版 Base 实测）：
- 直接标量：3700 / "是" / 1766937600000 / "硫酸"
- 单选/lookup 计算列包裹：{"type": 3, "value": ["放行"]}
- formula 包裹：{"type": 2, "value": [0]} / {"type": 5, "value": [ms]}
- 富文本分段：{"text": "...", "type": "text"} 或其数组
- user/人员：[{"id", "name", ...}]；关联：{"link_record_ids": ...}；附件：[{"name", ...}]

且读写不对称（写入纯字符串、读取数组化）。所有消费方（agent 工具、推送中心、
对账、base_mirror）统一走本模块解析——禁止各自手写 str(value) 拼接
（V3.0 分期A 真机验证教训：手写版遇富文本分段会把字典 repr 打进卡片）。
"""

from __future__ import annotations

from typing import Any


def cell_list(value: Any) -> list[str]:
    """把单元格值数组化为文本列表（兼容以上全部形态）。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [part for item in value for part in cell_list(item)]
    if isinstance(value, dict):
        if "text" in value:  # 富文本分段
            return cell_list(value.get("text"))
        if "value" in value:  # 类型包裹（formula/lookup）
            return cell_list(value.get("value"))
        name = value.get("name")  # user/附件
        if name:
            return [str(name)]
        return []
    if isinstance(value, bool):
        return [str(value)]
    return [str(value)]


def cell_text(value: Any) -> str:
    """单元格值 → 顿号连接的展示文本（空值为空串）。"""
    return "、".join(cell_list(value))


def unwrap(value: Any) -> Any:
    """递归取第一个标量（分段/包裹/数组展开）。"""
    if isinstance(value, list):
        return unwrap(value[0]) if value else None
    if isinstance(value, dict):
        for key in ("text", "value", "name"):
            if key in value:
                return unwrap(value[key])
        return None
    return value


def cell_number(value: Any) -> float | None:
    """单元格值 → 数值（数字/千分位文本；无法解析返回 None）。"""
    scalar = unwrap(value)
    if isinstance(scalar, bool) or scalar is None:
        return None
    if isinstance(scalar, (int, float)):
        return float(scalar)
    text = str(scalar).strip().replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None
