"""Meter repository 工具函数。"""

from __future__ import annotations

from datetime import date
from typing import Any

_DATE_FIELDS = {"calibration_date", "next_calibration_date", "report_date"}


def _coerce_date_fields(updates: dict[str, Any]) -> None:
    """将 updates 中的日期字符串转为 Python date 对象，兼容 asyncpg 驱动。"""
    for field in _DATE_FIELDS & updates.keys():
        value = updates[field]
        if isinstance(value, str):
            updates[field] = date.fromisoformat(value)


def _parse_multi(value: str | None) -> list[str] | None:
    """将逗号分隔的筛选值拆分为列表，用于 IN 查询。"""
    if not value:
        return None
    parts = [v.strip() for v in value.split(",") if v.strip()]
    return parts if parts else None


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符（% _ \\），避免用户输入被当作通配符匹配全表。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ═══════════════════════════════════════════
# 标准计量器具
# ═══════════════════════════════════════════
