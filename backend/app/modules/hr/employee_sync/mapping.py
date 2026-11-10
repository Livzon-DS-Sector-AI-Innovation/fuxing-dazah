"""飞书多维表格记录值 ↔ Employee ORM 字段 转换。

列名映射复用 EmployeeService._UPLOAD_COLUMN_MAP（Excel 上传与多维表格
使用同一套中文列名）。值形态差异由本模块抹平：

- 拉取 API（list_all_records）：文本为 segment 数组、单选为选项 ID
  （opt 开头）、人员字段为 {"users": [...]}、日期为毫秒时间戳、多选为 list
- WS 事件（after_value）：值均为字符串，复合值为 JSON 字符串
- 单选选项 ID → 文本 的翻译表由调用方从 list_fields 构建后传入
  （option_maps：中文列名 → {选项ID: 选项名}）
"""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.modules.hr.service import EmployeeService

# 上传映射（中文列名 → ORM 字段）
COLUMN_MAP: dict[str, str] = EmployeeService._UPLOAD_COLUMN_MAP

_DATE_FIELDS: set[str] = EmployeeService._DATE_FIELDS
_INT_FIELDS: set[str] = EmployeeService._INT_FIELDS
# 全量对账时未出现的列按置空处理（与 Excel 上传"以文件为准"语义一致）
RESETTABLE_FIELDS: set[str] = EmployeeService._EXCEL_RESETTABLE_FIELDS

# 人员状态占位值：跳过写入（沿用 Excel 上传的规范化规则）
_STATUS_SKIP = {"—", "——", "-", "", "无"}
_STATUS_VALID = {"在职", "离职", "试用期", "待审批", "病假", "产假", "产假复岗"}

# 多选/JSON 字段（本地 ORM 为 JSON 列，直接存 list）
_LIST_FIELDS: set[str] = {"qualifications", "remarks"}

# 飞书日期字段的毫秒时间戳按东八区语义（date-only 存当日 00:00 +08）；
# 用 UTC 解析会差一天。写入也按东八区零点，读回一致。
_TZ_CN = timezone(timedelta(hours=8))


class _Skip:
    """哨兵：该字段本次不写入（值缺失/非法/状态占位）。"""


_SKIP = _Skip()


def _ms_to_date(ms: float) -> date | None:
    """毫秒时间戳 → date（东八区语义；0/负值为空）。"""
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=_TZ_CN).date()
    except (OverflowError, OSError, ValueError):
        return None


def _parse_date_like(value: Any) -> date | None:
    """日期字段值：数值按毫秒时间戳或 Excel 序列号（源表两种都存在），文本按格式解析。"""
    if isinstance(value, bool):  # bool 是 int 子类，先排除
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        # Excel 序列号（如 42671=2016-10-31）；毫秒时间戳不会落在该区间
        if 0 < num < 65536:
            return EmployeeService._parse_date_value(value)
        return _ms_to_date(num)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if stripped.isdigit() and len(stripped) >= 12:
            return _ms_to_date(float(stripped))
        return EmployeeService._parse_date_value(stripped)
    return EmployeeService._parse_date_value(value)


def normalize_event_value(value: Any) -> Any:
    """事件 after_value 的复合值（附件/多选等）为 JSON 字符串，解析回 list/dict。"""
    if isinstance(value, str) and value[:1] in ("[", "{"):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def _segment_text(value: list[Any]) -> str | None:
    """飞书文本字段的值是 segment 数组 [{"text": str, ...}, ...]，拼接为纯文本。"""
    parts: list[str] = []
    for seg in value:
        if isinstance(seg, dict):
            text = seg.get("text")
            if text:
                parts.append(str(text))
        else:
            parts.append(str(seg))
    return "".join(parts) or None


def _users_text(payload: Any) -> str | None:
    """人员字段值取姓名拼接：{"users": [{"name": ...}]} 或 [{"name": ...}, ...]。"""
    if isinstance(payload, dict) and isinstance(payload.get("users"), list):
        members = payload["users"]
    elif isinstance(payload, list):
        members = payload
    else:
        return None
    names = [str(m.get("name")) for m in members if isinstance(m, dict) and m.get("name")]
    return "、".join(names) or None


def normalize_cell(raw_value: Any) -> Any:
    """单元格原始值归一：segment 数组 → 纯文本；人员对象 → 姓名文本；
    单元素标量数组解包（单选 ['optXXX']、日期 [1477238400000] 的包裹形态）。"""
    if isinstance(raw_value, list):
        if not raw_value:
            return None
        if isinstance(raw_value[0], dict) and "text" in raw_value[0]:
            return _segment_text(raw_value)
        if any(isinstance(v, dict) and ("users" in v or "name" in v) for v in raw_value):
            return _users_text(raw_value)
        if len(raw_value) == 1 and isinstance(raw_value[0], (str, int, float)):
            return raw_value[0]
        return raw_value  # 普通多选数组
    if isinstance(raw_value, dict):
        return _users_text(raw_value)
    return raw_value


def build_option_maps(fields_schema: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """从 list_fields 结果构建 单选列 选项ID → 选项名 的翻译表。"""
    maps: dict[str, dict[str, str]] = {}
    for field in fields_schema:
        col_name = str(field.get("field_name") or "")
        options = ((field.get("property") or {}).get("options")) or []
        mapping = {
            str(o.get("id")): str(o.get("name"))
            for o in options
            if o.get("id") is not None and o.get("name") is not None
        }
        if col_name and mapping:
            maps[col_name] = mapping
    return maps


def _convert_scalar(field_name: str, value: Any) -> Any:
    """单个单元格值（已归一）→ ORM 字段值。返回 _SKIP 表示不写入该字段。"""
    if value is None:
        return _SKIP
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return _SKIP
    if isinstance(value, list):
        if not value:
            return _SKIP
        if isinstance(value[0], dict) and "text" in value[0]:
            joined = _segment_text(value)
            return joined if joined else _SKIP

    if field_name in _DATE_FIELDS:
        # 与 Excel 上传一致：无法解析的日期跳过，不清空本地值
        parsed = _parse_date_like(value)
        return parsed if parsed else _SKIP
    if field_name in _INT_FIELDS:
        try:
            return int(float(str(value)))
        except (ValueError, TypeError):
            return _SKIP
    if field_name in _LIST_FIELDS:
        if isinstance(value, list):
            items = [str(v).strip() for v in value if str(v).strip()]
            return items or None
        # 事件值可能是 JSON 串（未经 normalize_event_value 的调用方容错）
        if isinstance(value, str) and value[:1] == "[":
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    items = [str(v).strip() for v in parsed if str(v).strip()]
                    return items or None
            except (TypeError, ValueError):
                pass
        return [v.strip() for v in str(value).split(",") if v.strip()] or None
    if field_name == "status":
        if value not in _STATUS_VALID:
            return _SKIP
        return value
    if isinstance(value, list):  # 未预期的多选值落到普通字段：拼接为文本
        return "、".join(str(v).strip() for v in value if str(v).strip()) or _SKIP
    return str(value)


def convert_source_fields(
    fields: dict[str, Any],
    *,
    reset_missing: bool,
    option_maps: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """源表一行（中文列名 → 值）→ ORM 字段 dict。

    reset_missing=True（全量对账）：未出现的可重置列补 None，行级"以表为准"；
    reset_missing=False（事件增量）：只更新出现的字段，不动其余数据。
    option_maps 用于把拉取 API 返回的单选选项 ID 翻译为选项文本
    （事件值本身就是文本，无需传入）。事件值应先经 normalize_event_value 处理。
    """
    data: dict[str, Any] = {}
    for col_name, raw_value in fields.items():
        field_name = COLUMN_MAP.get(col_name)
        if not field_name:
            continue
        value = normalize_cell(raw_value)
        # 单选选项 ID → 选项文本
        if option_maps and isinstance(value, str):
            translated = option_maps.get(col_name, {}).get(value)
            if translated is not None:
                value = translated

        if field_name == "_birth_date":
            # Excel 上传的内部中间键：出生年月拆为年/月/日三字段，本身不入库
            if isinstance(value, list):
                value = _segment_text(value)
            parsed = _parse_date_like(value)
            if parsed:
                data["birth_year"] = parsed.year
                data["birth_month"] = parsed.month
                data["birth_day"] = parsed.day
            continue
        converted = _convert_scalar(field_name, value)
        if converted is _SKIP:
            continue
        data[field_name] = converted

    if reset_missing:
        for field_name in RESETTABLE_FIELDS:
            data.setdefault(field_name, None)
    return data
