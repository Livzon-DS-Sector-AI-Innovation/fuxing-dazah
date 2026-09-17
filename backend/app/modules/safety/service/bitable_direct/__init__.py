"""公共直读多维表格底座（bitable_direct）。

只承载"与 Bitable 打交道的通用能力"：字段取值、过滤条件构造与下推能力矩阵、
北京时间日期窗口、注入式读写协议、串行回写、per-record 锁、开关闸门。
不含任何业务域的字段映射、视图对象、判定规则与编排。

入口（PEP 562 惰性加载）：

- ``gates``   开关与闸门判定（SAFETY_<DOMAIN>_* 统一命名）
- ``errors``  异常基类
- ``filters`` 过滤条件构造 / 下推能力矩阵 / 北京时间日期窗口
- ``reader``  读取协议 / 分页批量查询 / 连接解析
- ``writer``  写入协议 / 串行回写 / 字段 ID 缓存 / 幂等建列
- ``locks``   per-record 分布式锁（Redis SET NX EX，可注入）

至此底座模块（gates / errors / fields / filters / reader / writer / locks）全部落地。

实现说明：本 ``__init__`` **不做任何 eager import**，避免拉起 ORM / AI /
scheduler 等重依赖，也避免与域包形成导入环。
"""

from __future__ import annotations

import importlib
from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    # errors
    "BitableDirectError": ("errors", "BitableDirectError"),
    "BitableQueryError": ("errors", "BitableQueryError"),
    "BitableWriteError": ("errors", "BitableWriteError"),
    "BitableConfigError": ("errors", "BitableConfigError"),
    # gates
    "flag": ("gates", "flag"),
    "int_env": ("gates", "int_env"),
    "domain_env": ("gates", "domain_env"),
    "direct_enabled": ("gates", "direct_enabled"),
    "event_sync_enabled": ("gates", "event_sync_enabled"),
    "sync_job_enabled": ("gates", "sync_job_enabled"),
    "writeback_enabled": ("gates", "writeback_enabled"),
    "legacy_event_sync_active": ("gates", "legacy_event_sync_active"),
    "legacy_sync_job_active": ("gates", "legacy_sync_job_active"),
    # fields（纯值级原语）
    "rich_text": ("fields", "rich_text"),
    "select_values": ("fields", "select_values"),
    "person_info": ("fields", "person_info"),
    "person_name": ("fields", "person_name"),
    "ms_to_utc": ("fields", "ms_to_utc"),
    "to_utc": ("fields", "to_utc"),
    "utc_to_ms": ("fields", "utc_to_ms"),
    "fetch_window_records": ("reader", "fetch_window_records"),
    "attachment_list": ("fields", "attachment_list"),
    "to_millis": ("fields", "to_millis"),
    # fields（字段级取值，空值统一 None）
    "text": ("fields", "text"),
    "select": ("fields", "select"),
    "multi": ("fields", "multi"),
    "person": ("fields", "person"),
    "datetime_ms": ("fields", "datetime_ms"),
    "attachments": ("fields", "attachments"),
    # filters（过滤条件构造与下推能力矩阵）
    "BJT": ("filters", "BJT"),
    "EXACT_DATE": ("filters", "EXACT_DATE"),
    "DATE_RANGE_OPERATORS": ("filters", "DATE_RANGE_OPERATORS"),
    "COMPARISON_OPERATORS": ("filters", "COMPARISON_OPERATORS"),
    "OPERATORS_BY_FIELD_TYPE": ("filters", "OPERATORS_BY_FIELD_TYPE"),
    "FIELD_TYPES": ("filters", "FIELD_TYPES"),
    "operators_for": ("filters", "operators_for"),
    "supports": ("filters", "supports"),
    "ensure_supported": ("filters", "ensure_supported"),
    "condition": ("filters", "condition"),
    "checked_condition": ("filters", "checked_condition"),
    "is_date_condition": ("filters", "is_date_condition"),
    "and_group": ("filters", "and_group"),
    "or_group": ("filters", "or_group"),
    "flat_group": ("filters", "flat_group"),
    "epoch_ms": ("filters", "epoch_ms"),
    "bjt_day_start": ("filters", "bjt_day_start"),
    "day_window": ("filters", "day_window"),
    "date_range_window": ("filters", "date_range_window"),
    "exact_date_value": ("filters", "exact_date_value"),
    "date_condition": ("filters", "date_condition"),
    "day_conditions": ("filters", "day_conditions"),
    "day_filter": ("filters", "day_filter"),
    "window_days": ("filters", "window_days"),
    "day_queries": ("filters", "day_queries"),
    "in_window": ("filters", "in_window"),
    "trim_records": ("filters", "trim_records"),
    "union_by_record_id": ("filters", "union_by_record_id"),
    # reader（读取协议与分页批量查询）
    "MAX_PAGE_SIZE": ("reader", "MAX_PAGE_SIZE"),
    "DEFAULT_PAGE_SIZE": ("reader", "DEFAULT_PAGE_SIZE"),
    "DEFAULT_MAX_PAGES": ("reader", "DEFAULT_MAX_PAGES"),
    "BitablePageClient": ("reader", "BitablePageClient"),
    "BitableRecordsReader": ("reader", "BitableRecordsReader"),
    "fetch_all_records": ("reader", "fetch_all_records"),
    "resolve_client": ("reader", "resolve_client"),
    "ClientRecordsReader": ("reader", "ClientRecordsReader"),
    "open_reader": ("reader", "open_reader"),
    # writer（写入协议 / 串行回写 / 幂等建列）
    "WRITEBACK_INTERVAL_SECONDS": ("writer", "WRITEBACK_INTERVAL_SECONDS"),
    "BitableRecordWriter": ("writer", "BitableRecordWriter"),
    "BitableFieldAdmin": ("writer", "BitableFieldAdmin"),
    "RecordUpdate": ("writer", "RecordUpdate"),
    "WritebackResult": ("writer", "WritebackResult"),
    "write_serial": ("writer", "write_serial"),
    "resolve_field_id": ("writer", "resolve_field_id"),
    "FieldIdResolver": ("writer", "FieldIdResolver"),
    "FieldSpec": ("writer", "FieldSpec"),
    "EnsureStatus": ("writer", "EnsureStatus"),
    "EnsureFieldResult": ("writer", "EnsureFieldResult"),
    "property_matches": ("writer", "property_matches"),
    "field_matches": ("writer", "field_matches"),
    "extract_option_names": ("writer", "extract_option_names"),
    "describe_spec": ("writer", "describe_spec"),
    "ensure_field": ("writer", "ensure_field"),
    "open_writer": ("writer", "open_writer"),
    # locks（per-record 锁）
    "RedisLike": ("locks", "RedisLike"),
    "record_lock_key": ("locks", "record_lock_key"),
    "record_lock": ("locks", "record_lock"),
}

__all__ = list(_LAZY)


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    module = importlib.import_module(f"{__name__}.{module_name}")
    value = getattr(module, attr)
    globals()[name] = value  # 缓存，后续直接命中
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
