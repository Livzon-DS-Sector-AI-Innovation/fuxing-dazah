"""中控报警 Bitable 字段映射（纯函数，无副作用）。

将飞书 Bitable「中控报警统计」Base 各同构表原始字段映射为 CentralAlarmRecord 字段。
字段名以 spec/backend-design.md 为准（日期/岗位/报警情况说明/特殊情况说明）；
联调时若实际列名不同，仅调整本文件，不影响 handler 与 service。

- _ts / _text 复用 bitable_handler 既有公共辅助（_ms_to_datetime / _extract_rich_text）。
- derive_workshop_line 从 Bitable 表名推导车间/产线（如「车间一（达托）」→ 车间一/达托）。
- 多余字段进 bt_extra 兜底（不丢数据，不参与分析）。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.modules.safety.feishu import bitable_handler as bh

# 已映射的 Bitable 中文列名（其余字段进 bt_extra 兜底）
_MAPPED_LABELS: tuple[str, ...] = (
    "日期",
    "岗位",
    "报警情况说明",
    "特殊情况说明",
)

# 表名括号模式：<车间>（<产线>），如 车间一（达托）
_WORKSHOP_LINE_RE = re.compile(r"^(.+?)（(.+?)）$")


def map_bitable_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """将 Bitable 原始字段映射为 CentralAlarmRecord 字段。

    Returns:
        dict — 可直接用于 ORM 构造/更新；feishu_record_id/source/workshop/line 由调用方覆盖。
    """
    mapped: dict[str, Any] = {
        "alarm_date": _ts(fields.get("日期")),
        "post": _text(fields.get("岗位")),
        "alarm_description": _text(fields.get("报警情况说明")),
        "special_note": _text(fields.get("特殊情况说明")),
    }
    # 联调兜底：多余字段进 bt_extra（不覆盖已有映射字段）
    bt_extra = {
        label: fields[label]
        for label in fields
        if label not in _MAPPED_LABELS
    }
    if bt_extra:
        mapped["bt_extra"] = bt_extra
    return mapped


def derive_workshop_line(table_name: str) -> tuple[str, str | None]:
    """Bitable 表名 → (workshop, line)。

    - 「车间一（达托）」→ ("车间一", "达托")
    - 「车间二（达巴、非达）」→ ("车间二", "达巴、非达")
    - 「新罐区」→ ("新罐区", None)
    - 「酒精回收和旧罐区」→ ("酒精回收和旧罐区", None)

    规则：匹配「<X>（<Y>）」→ (X, Y)；否则 → (整表名, None)。
    """
    if not table_name:
        return ("", None)
    m = _WORKSHOP_LINE_RE.match(table_name.strip())
    if m:
        workshop, line = m.group(1).strip(), m.group(2).strip()
        return workshop, line
    return table_name.strip(), None


def _ts(value: Any) -> datetime | None:
    """Bitable 毫秒时间戳 → timezone-aware datetime（复用 bitable_handler._ms_to_datetime）。"""
    return bh._ms_to_datetime(value)


def _text(value: Any) -> str | None:
    """富文本 / 单选 / 普通字符串 → 纯文本；空返回 None。

    复用 bitable_handler._extract_rich_text（兼容 str/list/dict 公式包装）。
    """
    if value is None:
        return None
    if isinstance(value, str):
        text_val = value.strip()
    elif isinstance(value, dict):
        text_val = bh._extract_rich_text(value.get("value", value))
    elif isinstance(value, list):
        text_val = bh._extract_rich_text(value)
    else:
        text_val = str(value).strip()
    return text_val or None
