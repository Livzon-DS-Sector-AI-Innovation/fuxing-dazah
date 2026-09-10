"""外部审计表 — 统一解析层

按配置中的 field_mapping 规则，将源记录逐字段转换为 HazardReport dict。

支持的解析规则:
  - text              : 直接取文本值
  - person_name       : User 对象/列表 → "name" 或 "name1、name2"
  - single_select     : 单选文本 → 直接取
  - multi_select      : 多选数组 → "、".join([...])
  - datetime_ms       : Unix 毫秒时间戳 → datetime
  - text_date_dot     : "2025.04.30" → datetime
  - text_date_slash   : "2026/08/10" → datetime
  - text_date_any     : 尝试多种格式 → datetime
  - enum              : 查映射表转换 → str
  - combined_text     : 多字段拼接 → str
  - attachments       : 附件数组 → 下载后本地路径 JSON
"""

import logging
from datetime import UTC, date, datetime
from typing import Any

UTC = UTC

logger = logging.getLogger(__name__)

# 日期解析格式（按优先级排序）
_DATE_FORMATS = [
    "%Y.%m.%d",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y年%m月%d日",
    "%Y.%m.%d.",
    "%Y/%m/%d.",
]


def parse_record(config: dict, raw_record: dict[str, Any]) -> dict[str, Any]:
    """将一条源记录解析为 HazardReport 字段 dict。

    Args:
        config: 表配置 dict（含 field_mapping 和 defaults）
        raw_record: 源记录，key 为中文字段名

    Returns:
        HazardReport 字段 dict（英文列名 → 转换后的值）
    """
    defaults = config.get("defaults", {})
    mapping = config.get("field_mapping", {})

    # 从默认值开始
    result = dict(defaults)

    for model_field, map_spec in mapping.items():
        if not isinstance(map_spec, (list, tuple)) or len(map_spec) < 2:
            logger.warning("字段 %s 映射配置无效: %s", model_field, map_spec)
            continue

        source_field = map_spec[0]  # 源字段名（或 None 表示 combined_text）
        rule = map_spec[1]          # 解析规则
        default = map_spec[2]       # 默认值
        extra = map_spec[3] if len(map_spec) > 3 else None  # 额外参数

        try:
            value = _apply_rule(rule, source_field, raw_record, extra)
        except Exception:
            logger.exception(
                "字段 %s 解析异常 (rule=%s, source=%s)",
                model_field, rule, source_field,
            )
            value = None

        # 只有解析出有效值才覆盖默认值
        if value is not None or rule == "text":
            result[model_field] = value if value is not None else default

    # 处理默认值中的 date 对象转 datetime
    for key, val in result.items():
        if isinstance(val, date) and not isinstance(val, datetime):
            result[key] = datetime(val.year, val.month, val.day, tzinfo=UTC)

    return result


# ============================================================
# 规则分发
# ============================================================


def _apply_rule(
    rule: str,
    source_field: str | None,
    record: dict[str, Any],
    extra: Any = None,
) -> Any:
    """根据规则名调用对应的转换函数。"""
    # combined_text 不需要从 record 取单个字段
    if rule == "combined_text":
        return _parse_combined_text(record, extra)

    # 其他规则从 record 取源字段值
    raw_value = record.get(source_field) if source_field else None

    if rule == "text":
        return _parse_text(raw_value)
    elif rule == "person_name":
        return _parse_person_name(raw_value)
    elif rule == "single_select":
        return _parse_single_select(raw_value)
    elif rule == "multi_select":
        return _parse_multi_select(raw_value)
    elif rule == "datetime_ms":
        return _parse_datetime_ms(raw_value)
    elif rule == "text_date_dot":
        return _parse_text_date(raw_value, ["%Y.%m.%d"])
    elif rule == "text_date_slash":
        return _parse_text_date(raw_value, ["%Y/%m/%d"])
    elif rule == "text_date_any":
        return _parse_text_date(raw_value, _DATE_FORMATS)
    elif rule == "enum":
        return _parse_enum(raw_value, extra)
    elif rule == "attachments":
        return _parse_attachments_placeholder(raw_value)
    else:
        logger.warning("未知解析规则: %s", rule)
        return raw_value


# ============================================================
# 各规则实现
# ============================================================


def _parse_text(raw_value: Any) -> str:
    """纯文本：直接转字符串，兼容 Bitable 富文本格式。

    Bitable 长文本字段返回 [{"type":"text","text":"...","style":{}}]，
    普通文本字段返回纯字符串。此函数兼容两种格式。
    """
    if raw_value is None:
        return ""
    if isinstance(raw_value, list):
        parts: list[str] = []
        for item in raw_value:
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
            elif item:
                parts.append(str(item))
        return "".join(parts).strip()
    if isinstance(raw_value, str):
        return raw_value.strip()
    return str(raw_value).strip()


def _parse_person_name(raw_value: Any) -> str:
    """User 字段 → 提取姓名。

    Bitable User 字段可能是:
      - 单个 dict: {"name": "张三", "id": "ou_xxx", ...}
      - 多个 dict 的 list
      - None
    """
    if raw_value is None:
        return ""
    if isinstance(raw_value, dict):
        return raw_value.get("name", raw_value.get("id", ""))
    if isinstance(raw_value, list):
        names = [
            p.get("name", p.get("id", ""))
            for p in raw_value
            if isinstance(p, dict)
        ]
        return "、".join(filter(None, names))
    return str(raw_value)


def _parse_single_select(raw_value: Any) -> str:
    """单选：Bitable 单选字段返回的是纯文本。"""
    if raw_value is None:
        return ""
    return str(raw_value).strip()


def _parse_multi_select(raw_value: Any) -> str:
    """多选：Bitable 多选字段返回 list[str]。"""
    if raw_value is None:
        return ""
    if isinstance(raw_value, list):
        return "、".join(str(v) for v in raw_value if v)
    return str(raw_value).strip()


def _parse_datetime_ms(raw_value: Any) -> datetime | None:
    """Unix 毫秒时间戳 → datetime (UTC)。"""
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        if raw_value <= 0:
            return None
        try:
            return datetime.fromtimestamp(raw_value / 1000, tz=UTC)
        except (OSError, ValueError):
            return None
    # Bitable 有时返回字符串形式的数字
    if isinstance(raw_value, str) and raw_value.isdigit():
        ms = int(raw_value)
        if ms <= 0:
            return None
        try:
            return datetime.fromtimestamp(ms / 1000, tz=UTC)
        except (OSError, ValueError):
            return None
    return None


def _parse_text_date(
    raw_value: Any,
    formats: list[str],
) -> datetime | None:
    """文本日期 → datetime (UTC)。

    尝试多个格式依次解析，全部失败返回 None。
    """
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    logger.debug("日期解析失败: %s (尝试格式: %s)", text, formats)
    return None


def _parse_enum(raw_value: Any, mapping: dict[str, str] | None) -> str | None:
    """枚举映射：查表转换。无匹配返回 None（调用方用默认值）。"""
    if raw_value is None:
        return None
    if mapping is None:
        return str(raw_value).strip()
    text = str(raw_value).strip()
    return mapping.get(text, text)


def _parse_combined_text(
    record: dict[str, Any],
    config: dict[str, Any],
) -> str:
    """多字段拼接文本。

    config 格式:
      {
        "parts": ["字段1", "字段2"],
        "sep": "\n",
        "prefix": {"字段1": "前缀：", "字段2": ""},   # 可选
      }
    """
    if not config:
        return ""
    parts = config.get("parts", [])
    sep = config.get("sep", "\n")
    prefixes = config.get("prefix", {})

    segments = []
    for field_name in parts:
        value = record.get(field_name, "")
        if value:
            text = _parse_text(value)
            if text:
                prefix = prefixes.get(field_name, "")
                segments.append(f"{prefix}{text}")

    return sep.join(segments)


def _parse_attachments_placeholder(raw_value: Any) -> str | None:
    """附件字段 → 暂存原始 JSON，由 service 层下载。

    返回 JSON 字符串形式的附件元数据列表，供 service 层异步下载。
    无附件返回 None。
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, list):
        if len(raw_value) == 0:
            return None
        # 返回附件的 JSON 表示，service 层负责下载
        import json
        return json.dumps(raw_value, ensure_ascii=False)
    return None
