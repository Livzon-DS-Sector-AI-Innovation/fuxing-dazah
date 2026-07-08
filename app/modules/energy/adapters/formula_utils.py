"""共享公式解析工具。

提供跨平台适配器复用的公式解析函数：
- parse_formula_ids：从公式字符串中提取所有独立 ID
- has_formula：判断字符串是否包含 +/- 运算符
- eval_formula：根据聚合值字典计算公式结果
- resolve_api_url：解析 API 地址（优先使用配置值）
"""

from __future__ import annotations

import re

# 公式分隔符：按 + 或 - 拆分
_FORMULA_SPLIT_RE = re.compile(r"([+-])")


def parse_formula_ids(formula: str) -> list[str]:
    """从公式字符串中提取所有独立的设备/采集点 ID。

    如果 ``formula`` 包含 + 或 - 运算符，则拆分提取每个操作数；
    否则视为单个 ID 返回。
    """
    tokens = _FORMULA_SPLIT_RE.split(formula.strip())
    ids: list[str] = []
    for token in tokens:
        t = token.strip()
        if t and t not in ("+", "-"):
            ids.append(t)
    return ids


def has_formula(formula: str) -> bool:
    """判断字符串是否包含公式运算符（+ 或 -）。"""
    return "+" in formula or "-" in formula


def eval_formula(formula: str, value_map: dict[str, float]) -> float:
    """根据已聚合的设备值字典计算公式结果。

    Args:
        formula: 公式表达式，如 "2022001507+202503170001"
        value_map: ID → 聚合值 的映射字典

    Returns:
        公式计算结果
    """
    tokens = _FORMULA_SPLIT_RE.split(formula.strip())
    result = 0.0
    operator = "+"
    for token in tokens:
        t = token.strip()
        if t == "+":
            operator = "+"
        elif t == "-":
            operator = "-"
        elif t:
            value = value_map.get(t, 0.0)
            if operator == "+":
                result += value
            else:
                result -= value
    return result


def resolve_api_url(api_endpoint: str, default_url: str) -> str:
    """解析 API 地址：设备配置的 api_endpoint 非空时使用，否则回退默认地址。"""
    stripped = api_endpoint.strip() if api_endpoint else ""
    return stripped if stripped else default_url
