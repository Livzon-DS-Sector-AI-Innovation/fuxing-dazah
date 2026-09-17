"""消防报警直读模式：视图对象与注入式读取器协议。

Ticket 01 只交付两件东西：

1. FireAlarmView：字段名与 FireAlarmRecord 完全同名，使聚合、渲染、私发卡片
   四段既有代码可以零改动复用；id 用飞书记录 ID 兜底。
2. FireAlarmRecordsReader：读取器协议，测试可注入替身；默认真实实现留待票据 03。

本模块是纯映射与协议，不做任何 IO，不连接 Bitable。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import filters as bd_filters
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.fire_alarm import contract
from app.modules.safety.service.fire_alarm.bitable_mapper import map_bitable_fields


@dataclass
class FireAlarmView:
    """消防报警记录的内存视图对象（不落库、不参与 ORM）。

    字段名与 FireAlarmRecord 同名，聚合 / 渲染 / 私发卡片只做属性读取，
    因此同一份数据用 ORM 对象或本对象跑，输出应逐字相同。
    """

    # 标识与元数据
    id: str = ""
    feishu_record_id: str | None = None
    source: str = "bitable"
    synced_at: datetime | None = None

    # 平台库审计字段：Bitable 无来源，保持为空，不臆造
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: Any = None
    updated_by: Any = None
    is_deleted: bool = False

    # 报警基础字段
    alarm_time: datetime | None = None
    alarm_type: str | None = None
    department: str | None = None
    department_leader_name: str | None = None
    building: str | None = None
    location: str | None = None
    alarm_nature: str | None = None
    cause_category: str | None = None
    cause_description: str | None = None
    bt_extra: dict[str, Any] | None = None

    # AI 分析字段
    ai_dimension: str | None = None
    ai_reason_analysis: str | None = None
    ai_rectification_direction: str | None = None
    ai_analyzed_at: datetime | None = None


def _ai_dimension(fields: dict[str, Any]) -> str | None:
    """Bitable「AI维度」中文选项 -> 平台英文枚举；空或未知返回 None。"""
    option = bd_fields.select(fields, contract.AI_DIMENSION_FIELD)
    return contract.option_to_dimension(option)


def to_view(
    record: dict[str, Any],
    *,
    synced_at: datetime | None = None,
) -> FireAlarmView:
    """Bitable 原始记录 -> FireAlarmView。

    复用既有 map_bitable_fields 完成基础字段映射（一行不改），再补齐
    id / feishu_record_id / source / synced_at 与 4 个 AI 列。
    """
    fields: dict[str, Any] = record.get("fields") or {}
    record_id = str(record.get("record_id") or "")
    mapped = map_bitable_fields(fields)

    return FireAlarmView(
        id=record_id,
        feishu_record_id=record_id or None,
        source="bitable",
        synced_at=synced_at or datetime.now(UTC),
        alarm_time=mapped.get("alarm_time"),
        alarm_type=mapped.get("alarm_type"),
        department=mapped.get("department"),
        department_leader_name=mapped.get("department_leader_name"),
        building=mapped.get("building"),
        location=mapped.get("location"),
        alarm_nature=mapped.get("alarm_nature"),
        cause_category=mapped.get("cause_category"),
        cause_description=mapped.get("cause_description"),
        bt_extra=mapped.get("bt_extra"),
        ai_dimension=_ai_dimension(fields),
        ai_reason_analysis=bd_fields.text(fields, contract.AI_REASON_ANALYSIS_FIELD),
        ai_rectification_direction=bd_fields.text(
            fields, contract.AI_RECTIFICATION_DIRECTION_FIELD
        ),
        ai_analyzed_at=bd_fields.datetime_ms(fields, contract.AI_ANALYZED_AT_FIELD),
    )


# Bitable「火灾报警信息」表里映射所需的字段名；查询时只请求这些列。
_BASE_REQUEST_FIELD_NAMES: tuple[str, ...] = (
    "报警时间",
    "报警类型",
    "报警部门负责人",
    "报警部门负责人.部门",
    "报警楼栋",
    "报警部位",
    "报警性质",
    "报警原因分类",
    "具体报警原因",
)
_REQUEST_FIELD_NAMES: tuple[str, ...] = (
    *_BASE_REQUEST_FIELD_NAMES,
    *contract.AI_FIELD_NAMES,
)
REQUEST_FIELD_NAMES: tuple[str, ...] = _REQUEST_FIELD_NAMES


def day_window(target_date: date) -> tuple[datetime, datetime]:
    """自然日窗口：目标日北京时间 00:00 至次日 00:00，左闭右开。"""
    start = bd_filters.bjt_day_start(target_date)
    return start, start + timedelta(days=1)


def rolling_window(target_date: date) -> tuple[datetime, datetime]:
    """滚动 24 小时窗口：前日北京时间 17:00 至当日 17:00，左闭右开。"""
    end = bd_filters.bjt_day_start(target_date) + timedelta(hours=17)
    return end - timedelta(days=1), end


def week_window(week_start: date, week_end: date) -> tuple[datetime, datetime]:
    """自然周窗口：周一北京时间 00:00 至周日结束（下周一 00:00），左闭右开。"""
    start = bd_filters.bjt_day_start(week_start)
    end = bd_filters.bjt_day_start(week_end) + timedelta(days=1)
    return start, end


class FireAlarmBitableReader:
    """消防报警直读读取器真实实现。

    所有 IO 收口在注入的 BitableRecordsReader 上；默认由 open_reader() 从
    配置中心解析连接。三种窗口都先换算为北京时间自然日集合，按天批量查询，
    最后在应用侧按毫秒裁剪，避免 ExactDate 天粒度造成的边界误收。
    """

    def __init__(
        self,
        client: bd_reader.BitableRecordsReader,
        *,
        table_id: str | None = None,
        page_size: int = 500,
    ) -> None:
        self._client = client
        self._table_id = table_id
        self._page_size = page_size

    async def _fetch_window(
        self, start: datetime, end: datetime
    ) -> list[FireAlarmView]:
        record_groups: list[list[dict[str, Any]]] = []
        for _day, filter_info in bd_filters.day_queries("报警时间", start, end):
            records = await self._client.list_all_records(
                table_id=self._table_id,
                filter_info=filter_info,
                field_names=list(_REQUEST_FIELD_NAMES),
                page_size=self._page_size,
                strict=True,
            )
            record_groups.append(records)
        merged = bd_filters.union_by_record_id(record_groups)
        views = [to_view(record) for record in merged]
        return bd_filters.trim_records(
            views,
            lambda view: view.alarm_time,
            start=start,
            end=end,
        )

    async def get_records_by_date(self, target_date: date) -> list[FireAlarmView]:
        """自然日窗口取数。"""
        start, end = day_window(target_date)
        return await self._fetch_window(start, end)

    async def get_records_by_rolling_window(
        self, target_date: date
    ) -> tuple[list[FireAlarmView], datetime, datetime]:
        """滚动 24 小时窗口取数，额外返回 UTC 起止时间供渲染显示。"""
        start, end = rolling_window(target_date)
        views = await self._fetch_window(start, end)
        return views, start.astimezone(UTC), end.astimezone(UTC)

    async def get_records_by_week(
        self, week_start: date, week_end: date
    ) -> list[FireAlarmView]:
        """自然周窗口取数。"""
        start, end = week_window(week_start, week_end)
        return await self._fetch_window(start, end)


def open_reader(
    *,
    table_id: str | None = None,
    page_size: int = 500,
) -> FireAlarmBitableReader:
    """默认真实实现：从配置中心解析 fire_alarm/alarm 连接。"""
    client = bd_reader.open_reader("fire_alarm", "alarm", table_id=table_id)
    return FireAlarmBitableReader(
        client, table_id=table_id, page_size=page_size
    )


@runtime_checkable
class FireAlarmRecordsReader(Protocol):
    """消防报警读取器协议（默认真实实现留待票据 03）。

    三个方法分别对应改造前 service.py 的三个取数窗口；返回视图对象。
    滚动窗口额外返回 UTC 起止时间，供渲染层显示「前日 17:00 至当日 17:00」。
    """

    async def get_records_by_date(self, target_date: date) -> list[FireAlarmView]: ...

    async def get_records_by_rolling_window(
        self, target_date: date
    ) -> tuple[list[FireAlarmView], datetime, datetime]: ...

    async def get_records_by_week(
        self, week_start: date, week_end: date
    ) -> list[FireAlarmView]: ...


__all__ = [
    "FireAlarmView",
    "FireAlarmRecordsReader",
    "FireAlarmBitableReader",
    "REQUEST_FIELD_NAMES",
    "day_window",
    "rolling_window",
    "week_window",
    "open_reader",
    "to_view",
]
