"""消防报警直读模式：视图对象与注入式读取器协议。

Ticket 01 只交付两件东西：

1. FireAlarmView：字段名与 FireAlarmRecord 完全同名，使聚合、渲染、私发卡片
   四段既有代码可以零改动复用；id 用飞书记录 ID 兜底。
2. FireAlarmRecordsReader：读取器协议，测试可注入替身；默认真实实现留待票据 03。

本模块是纯映射与协议，不做任何 IO，不连接 Bitable。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import filters as bd_filters
from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.fire_alarm import contract
from app.modules.safety.service.fire_alarm.bitable_mapper import map_bitable_fields

F_ALARM_TIME = "报警时间"

# 窗口缓存条目上限（中控同款）：台账页任意范围键低频增长，超限淘汰最旧
_CACHE_MAX_ENTRIES = 32


@dataclass
class _CacheEntry:
    """窗口缓存条目（ehs cache.py 同款形状：时间戳 + 视图列表）。"""

    at: float
    views: list[FireAlarmView]


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
    """自然周窗口：周一北京时间 00:00 至周日结束（下周一 00:00），左闭右开。

    语义与 month_window 相同（[起始日 00:00, 结束日次日 00:00)），
    保留独立命名便于 get_stats 本周 KPI 复用。
    """
    return month_window(week_start, week_end)


def month_window(month_start: date, month_end: date) -> tuple[datetime, datetime]:
    """自然月窗口：1 日北京时间 00:00 至月末结束（次月 1 日 00:00），左闭右开。"""
    start = bd_filters.bjt_day_start(month_start)
    end = bd_filters.bjt_day_start(month_end) + timedelta(days=1)
    return start, end


class FireAlarmBitableReader:
    """消防报警直读读取器真实实现。

    所有 IO 收口在注入的 BitableRecordsReader 上；默认由 open_reader() 从
    配置中心解析连接。三种窗口都先换算为北京时间自然日集合，按天批量查询，
    最后在应用侧按毫秒裁剪，避免 ExactDate 天粒度造成的边界误收。
    """

    def __init__(
        self,
        client: bd_reader.BitablePageClient,
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
        # 倒序分页 + 提前终止：不再按天逐次查询（票据 09）
        records = await bd_reader.fetch_window_records(
            self._client,
            time_field=F_ALARM_TIME,
            start=start,
            end=end,
            table_id=self._table_id,
            field_names=list(_REQUEST_FIELD_NAMES),
            page_size=self._page_size,
        )
        views = [to_view(record) for record in records]
        return bd_filters.trim_records(
            views,
            lambda view: view.alarm_time,
            start=start,
            end=end,
        )

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        """自然日窗口取数（strict 仅供协议同形：裸实现无缓存，恒现拉）。"""
        start, end = day_window(target_date)
        return await self._fetch_window(start, end)

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[FireAlarmView], datetime, datetime]:
        """滚动 24 小时窗口取数，额外返回 UTC 起止时间供渲染显示。"""
        start, end = rolling_window(target_date)
        views = await self._fetch_window(start, end)
        return views, start.astimezone(UTC), end.astimezone(UTC)

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        """自然周窗口取数（get_stats 本周 KPI 用）。"""
        start, end = week_window(week_start, week_end)
        return await self._fetch_window(start, end)

    async def get_records_by_month(
        self, month_start: date, month_end: date, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        """自然月窗口取数。"""
        start, end = month_window(month_start, month_end)
        return await self._fetch_window(start, end)

    async def get_records_by_range(
        self, start: datetime, end: datetime, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        """任意 UTC 瞬时区间取数（页面台账查询用；含端点毫秒裁剪）。"""
        return await self._fetch_window(start, end)

    async def count_all(self) -> int:
        """全表精确计数（search page_size=1 只取 total，不拉数据）。"""
        result = await self._client.search_records(
            table_id=self._table_id, page_size=1, strict=True
        )
        return int(result.get("total") or 0)


class CachedFireAlarmReader:
    """消防报警窗口拉取的 TTL 缓存包装（open_reader 单例持有）。

    窗口键 = (start_iso, end_iso)：自然日/周/月/滚动键全天稳定，总览驾驶舱
    与台账页 5 分钟内复用同一窗口结果（无缓存时每次刷新实打 Bitable 实测
    ~5s）。strict=True（日报/月报生成路径）绕过缓存也不回填——生成路径必须
    现拉，宁可多打也不静默缺数。

    TTL 在单例首次创建时读取一次（cert CachedCertReader 同口径）；
    构造本类直接注入的测试不受影响（裸 reader 无缓存）。
    """

    def __init__(self, inner: Any, *, ttl_seconds: int) -> None:
        self._inner = inner
        self._ttl = int(ttl_seconds)
        self._entries: dict[tuple[str, str], _CacheEntry] = {}

    async def _cached_window(
        self, start: datetime, end: datetime, *, strict: bool
    ) -> list[FireAlarmView]:
        key = (start.isoformat(), end.isoformat())
        now = time.monotonic()
        if not strict and self._ttl > 0:
            entry = self._entries.get(key)
            if entry is not None and now - entry.at < self._ttl:
                return entry.views
        views: list[FireAlarmView] = await self._inner.get_records_by_range(start, end)
        if not strict and self._ttl > 0:
            self._entries[key] = _CacheEntry(at=now, views=views)
            self._evict()
        return views

    def _evict(self) -> None:
        """超上限淘汰最旧条目（含已过期项），维持缓存占用有界。"""
        if len(self._entries) <= _CACHE_MAX_ENTRIES:
            return
        oldest = sorted(self._entries, key=lambda k: self._entries[k].at)
        for k in oldest[: len(self._entries) - _CACHE_MAX_ENTRIES]:
            self._entries.pop(k, None)

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        start, end = day_window(target_date)
        return await self._cached_window(start, end, strict=strict)

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[FireAlarmView], datetime, datetime]:
        start, end = rolling_window(target_date)
        views = await self._cached_window(start, end, strict=strict)
        return views, start.astimezone(UTC), end.astimezone(UTC)

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        start, end = week_window(week_start, week_end)
        return await self._cached_window(start, end, strict=strict)

    async def get_records_by_month(
        self, month_start: date, month_end: date, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        start, end = month_window(month_start, month_end)
        return await self._cached_window(start, end, strict=strict)

    async def get_records_by_range(
        self, start: datetime, end: datetime, *, strict: bool = False,
    ) -> list[FireAlarmView]:
        return await self._cached_window(start, end, strict=strict)

    async def count_all(self) -> int:
        total: int = await self._inner.count_all()
        return total


def open_reader(
    *,
    table_id: str | None = None,
    page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
) -> FireAlarmRecordsReader:
    """共享单例：从配置中心解析 fire_alarm/alarm 连接。

    全默认参数返回 TTL 缓存包装单例（总览/台账/统计共用同一缓存窗口）；
    任一参数非默认（测试/特殊表）返回裸 reader 现拉，与中控同语义
    （单例仅首次创建，非默认参数会被静默忽略，故不与其共享）。
    """
    if table_id is not None or page_size != bd_reader.DEFAULT_PAGE_SIZE:
        client = bd_reader.resolve_client("fire_alarm", "alarm", table_id=table_id)
        return FireAlarmBitableReader(
            client, table_id=table_id, page_size=page_size,
        )
    global _SHARED_READER
    if _SHARED_READER is None:
        from app.modules.safety.service.fire_alarm import config

        client = bd_reader.resolve_client("fire_alarm", "alarm")
        _SHARED_READER = CachedFireAlarmReader(
            FireAlarmBitableReader(client),
            ttl_seconds=config.cache_ttl_seconds(),
        )
    return _SHARED_READER


_SHARED_READER: CachedFireAlarmReader | None = None


@runtime_checkable
class FireAlarmRecordsReader(Protocol):
    """消防报警读取器协议（open_reader 返回缓存包装，测试用替身）。

    三个方法分别对应改造前 service.py 的三个取数窗口；返回视图对象。
    滚动窗口额外返回 UTC 起止时间，供渲染层显示「前日 17:00 至当日 17:00」。
    strict=True：生成路径（日报/月报编排）绕过查询面缓存现拉，保证新鲜。
    """

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[FireAlarmView]: ...

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[FireAlarmView], datetime, datetime]: ...

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[FireAlarmView]: ...

    async def get_records_by_month(
        self, month_start: date, month_end: date, *, strict: bool = False,
    ) -> list[FireAlarmView]: ...

    async def get_records_by_range(
        self, start: datetime, end: datetime, *, strict: bool = False,
    ) -> list[FireAlarmView]: ...

    async def count_all(self) -> int: ...


__all__ = [
    "FireAlarmView",
    "FireAlarmRecordsReader",
    "FireAlarmBitableReader",
    "CachedFireAlarmReader",
    "REQUEST_FIELD_NAMES",
    "day_window",
    "rolling_window",
    "week_window",
    "month_window",
    "open_reader",
    "to_view",
]
