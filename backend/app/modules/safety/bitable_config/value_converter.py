"""Bitable 字段映射值转换器 — mapping 项 → 模型值的纯函数集。

语义对齐 ``app/modules/safety/audit/parser.py``（text/person/multi_select/
single_select/attachment/datetime/enum/combined_text），全部为同步纯函数：
无 IO、无状态、可单测。

入口 ``convert_value(raw, spec, option_map)`` 按 ``spec["field_type"]`` 分发；
未知 field_type 按 text 兜底并记告警日志（§7.1 R5：映射 JSONB 非法不中断运行）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.modules.safety.bitable_config.registry import FieldType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 8 种 field_type 纯函数（对齐 audit/parser.py 各 _parse_* 语义）
# ═══════════════════════════════════════════════════════════════


def convert_text(raw: Any) -> str:
    """text：直接取文本值。

    兼容 Bitable 富文本（list[{"type":"text","text":...}]）与普通字符串。
    """
    if raw is None:
        return ""
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            elif item:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip()


def convert_person(raw: Any) -> str:
    """person：Bitable 人员字段 → 姓名。

    - 单个 dict: {"name": ..., "id": ...} → name（缺 name 用 id）
    - list[dict] → 多值姓名顿号拼接（「张三、李四」）
    """
    if raw is None:
        return ""
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("id") or "")
    if isinstance(raw, list):
        names = [
            str(p.get("name") or p.get("id") or "")
            for p in raw
            if isinstance(p, dict)
        ]
        return "、".join(filter(None, names))
    return str(raw)


def convert_single_select(raw: Any) -> str:
    """single_select：单选纯文本直取。"""
    if raw is None:
        return ""
    return str(raw).strip()


def convert_multi_select(raw: Any) -> str:
    """multi_select：多选 list → 顿号拼接（「A、B」）。"""
    if raw is None:
        return ""
    if isinstance(raw, list):
        return "、".join(str(v) for v in raw if v)
    return str(raw).strip()


def convert_attachment(raw: Any) -> str | None:
    """attachment：附件数组 → 原始 JSON 直传（各 handler 现有下载链路处理）。

    空列表/非列表返回 None。
    """
    if raw is None or not isinstance(raw, list) or len(raw) == 0:
        return None
    return json.dumps(raw, ensure_ascii=False)


def convert_datetime(raw: Any) -> datetime | None:
    """datetime：Bitable DateTime（Unix 毫秒时间戳）→ datetime(UTC)。

    兼容 int/float 与数字字符串；<=0 或非法返回 None。
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ms = raw
    elif isinstance(raw, str) and raw.isdigit():
        ms = int(raw)
    else:
        return None
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (OSError, ValueError):
        return None


def convert_enum(raw: Any, value_map: Mapping[str, Any] | None = None) -> str | None:
    """enum：查 value_map 转换；未命中直取原文（对齐 parser._parse_enum）。"""
    if raw is None:
        return None
    if value_map is None:
        return str(raw).strip()
    text = str(raw).strip()
    return str(value_map.get(text, text))


def convert_combined_text(
    raw_record: Mapping[str, Any],
    spec: Mapping[str, Any] | None,
) -> str:
    """combined_text：多字段拼接。

    spec 格式（对齐 parser._parse_combined_text）::

        {"parts": ["字段1", "字段2"], "sep": "\\n", "prefix": {"字段1": "前缀："}}
    """
    config = dict(spec or {})
    parts = config.get("parts") or []
    sep = str(config.get("sep", "\n"))
    prefixes = config.get("prefix") or {}
    segments: list[str] = []
    for field_name in parts:
        text = convert_text(raw_record.get(field_name))
        if text:
            segments.append(f"{prefixes.get(field_name, '')}{text}")
    return sep.join(segments)


# ═══════════════════════════════════════════════════════════════
# 分发入口
# ═══════════════════════════════════════════════════════════════


def convert_value(
    raw: Any,
    spec: Mapping[str, Any] | None,
    option_map: Mapping[str, Any] | None = None,
) -> Any:
    """按 mapping 项 ``spec`` 的 field_type 转换 ``raw``。

    Args:
        raw: 源字段原始值（combined_text 时传整个 fields dict，与 parser 一致）
        spec: mapping 项 dict（含 field_type/default_value/value_map 等）
        option_map: 可选查表（enum 在 spec 无 value_map 时使用）

    未知 field_type 按 text 兜底 + 告警；转换结果为 None 时应用
    ``spec["default_value"]``。
    """
    item = dict(spec or {})
    field_type: str = str(item.get("field_type") or "text")

    if field_type == "person":
        value: Any = convert_person(raw)
    elif field_type == "multi_select":
        value = convert_multi_select(raw)
    elif field_type == "single_select":
        value = convert_single_select(raw)
    elif field_type == "attachment":
        value = convert_attachment(raw)
    elif field_type == "datetime":
        value = convert_datetime(raw)
    elif field_type == "enum":
        value = convert_enum(raw, item.get("value_map") or option_map)
    elif field_type == "combined_text":
        value = convert_combined_text(raw, item)
    elif field_type == "text":
        value = convert_text(raw)
    else:
        logger.warning(
            "未知 field_type: %s（target_field=%s），按 text 兜底",
            field_type, item.get("target_field"),
        )
        value = convert_text(raw)

    if value is None and item.get("default_value") is not None:
        return item["default_value"]
    return value


__all__ = [
    "FieldType",
    "convert_value",
    "convert_text",
    "convert_person",
    "convert_single_select",
    "convert_multi_select",
    "convert_attachment",
    "convert_datetime",
    "convert_enum",
    "convert_combined_text",
]
