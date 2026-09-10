"""消防报警 Bitable 字段映射（纯函数，无副作用）。

将飞书 Bitable「火灾报警信息」表（消防数据多维表格）原始字段映射为
FireAlarmRecord 字段。字段名以 spec/backend-design.md §2.2.2 为准；
联调时若实际列名不同，仅调整本文件，不影响 handler 与 service。

- _text / _ts / _name 与 special_operation_daily_report.map_bitable_fields 内的
  辅助同名同语义；_ts / _name 复用 bitable_handler 既有公共辅助
  （_ms_to_datetime / _extract_person_info，参照 oh_bitable_handler 的复用模式）。
- 多余字段进 bt_extra 兜底（不丢数据，不参与分析）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.modules.safety.feishu import bitable_handler as bh

# 已映射的 Bitable 中文列名（其余字段进 bt_extra 兜底）
_MAPPED_LABELS: tuple[str, ...] = (
    "报警时间",
    "报警类型",
    "报警部门",
    "报警部门负责人",
    "报警部门负责人.部门",  # 责任部门（负责人人字段的部门子字段）
    "报警楼栋",
    "报警部位",
    "报警性质",
    "报警原因分类",
    "具体报警原因",
)


def map_bitable_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """将 Bitable 原始字段映射为 FireAlarmRecord 字段。

    Returns:
        dict — 可直接用于 ORM 构造/更新；feishu_record_id/source 由调用方覆盖。
    """
    # 责任部门：多维表格记录于负责人人字段的关联子字段「报警部门负责人.部门」
    # （如 ['提炼工程四部']）；若将来新增独立「报警部门」列则优先取该列。
    department = _text(fields.get("报警部门")) or _related_dept(
        fields.get("报警部门负责人.部门")
    )
    mapped: dict[str, Any] = {
        "alarm_time": _ts(fields.get("报警时间")),
        "alarm_type": _text(fields.get("报警类型")),
        "department": department,
        "department_leader_name": _name(fields.get("报警部门负责人")),
        "building": _text(fields.get("报警楼栋")),
        "location": _text(fields.get("报警部位")),
        "alarm_nature": _text(fields.get("报警性质")),
        "cause_category": _text(fields.get("报警原因分类")),
        "cause_description": _text(fields.get("具体报警原因")),
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


def _ts(value: Any) -> datetime | None:
    """Bitable 毫秒时间戳 → timezone-aware datetime（复用 bitable_handler._ms_to_datetime）。"""
    return bh._ms_to_datetime(value)


def _text(value: Any) -> str | None:
    """富文本 / 单选 / 普通字符串 → 纯文本；空返回 None。"""
    if value is None:
        return None
    if isinstance(value, str):
        text_val = value.strip()
    elif isinstance(value, dict):
        # 公式包装 {"type":1,"value":[...]} 等
        text_val = bh._extract_rich_text(value.get("value", value))
    elif isinstance(value, list):
        text_val = bh._extract_rich_text(value)
    else:
        text_val = str(value).strip()
    return text_val or None


def _name(value: Any) -> str | None:
    """person 字段 → 姓名；空返回 None（复用 bitable_handler._extract_person_info）。"""
    name = bh._extract_person_info(value)["name"]
    return name or None


def _related_dept(value: Any) -> str | None:
    """关联字段「报警部门负责人.部门」→ 部门名；空值返回 None。

    实际值形如 ['提炼工程四部']（list）或 'None'/'null'（空占位），
    兼容 list / str / dict 包装。
    """
    if value is None:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = bh._extract_rich_text(value.get("value", value))
    if not isinstance(value, str):
        value = str(value)
    text_val = value.strip().strip("[]").strip("'\"")
    if text_val in ("", "None", "null", "[]"):
        return None
    return text_val or None
