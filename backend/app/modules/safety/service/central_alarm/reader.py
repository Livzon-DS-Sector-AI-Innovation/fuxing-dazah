"""中控报警直读模式：视图对象与注入式读取器（central-alarm-direct）。

照搬消防 fire_alarm/reader.py 的模式，差异在本域是 **14 张同构表**：

1. CentralAlarmView：字段名与 CentralAlarmRecord ORM 完全同名，聚合 / 渲染 / AI
   代码只做属性读取，同一份数据用 ORM 或本对象跑输出应逐字相同；id 用飞书记录 ID。
2. CentralAlarmBitableReader：真实读取器——`GET /tables` 取表名 → 排除配置表 →
   `derive_workshop_line` 推导车间/产线 → 逐表窗口取数（底座 fetch_window_records，
   倒序分页 + 提前终止 + 应用侧毫秒裁剪）→ **asyncio 并发**（读接口允许并发）
   → 视图对象列表。表清单与表名映射均可注入，IO 收口在 open_reader()。
3. CentralAlarmRecordsReader：协议，日报编排 / query / stats 接受注入，测试用替身。

ai_* 字段保留声明、直读恒 None（已拍板：AI 分析不落盘、每日重跑）。

探针固化的 API 坑位：records/search 的 page_token 必须放 URL query 参数
（放 body 会被飞书忽略 → 恒返第一页）；响应 data.total 可免翻页计数。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import filters as bd_filters
from app.modules.safety.service.bitable_direct import reader as bd_reader

_TIME_FIELD = "日期"

__all__ = [
    "CentralAlarmView",
    "CentralAlarmRecordLike",
    "CentralAlarmRecordsReader",
    "CentralAlarmBitableReader",
    "open_reader",
    "day_window",
    "rolling_window",
    "week_window",
    "view_from_record",
]


@dataclass
class CentralAlarmView:
    """中控报警记录的内存视图对象（不落库、不参与 ORM）。

    字段名与 CentralAlarmRecord 同名；ai_* 恒 None（直读域 AI 不落盘）。
    """

    # 标识与元数据
    id: str = ""
    feishu_record_id: str | None = None
    source: str = "bitable"
    synced_at: datetime | None = None
    created_at: datetime | None = None

    # Bitable 原始字段（与 bitable_mapper.map_bitable_fields 对齐）
    alarm_date: datetime | None = None
    post: str | None = None
    alarm_description: str | None = None
    special_note: str | None = None

    # 车间/产线（由表名推导，derive_workshop_line）
    workshop: str | None = None
    line: str | None = None

    # AI 分析字段（直读恒 None；镜像路径由 ORM 承载历史值）
    ai_alarm_type: str | None = None
    ai_equipment: str | None = None
    ai_pattern: str | None = None
    ai_dimension: str | None = None
    ai_reason_analysis: str | None = None
    ai_rectification_direction: str | None = None
    ai_analyzed_at: datetime | None = None


@runtime_checkable
class CentralAlarmRecordLike(Protocol):
    """聚合 / 渲染 / AI 所需的最小记录属性（ORM 与 View 都满足）。

    id 在 ORM 侧是 int 主键、视图侧是飞书记录 ID 字符串，消费方一律 str() 化，
    故协议声明为 Any。
    """

    id: Any
    alarm_date: datetime | None
    post: str | None
    alarm_description: str | None
    special_note: str | None
    workshop: str | None
    line: str | None
    ai_alarm_type: str | None
    ai_equipment: str | None
    ai_pattern: str | None
    ai_dimension: str | None
    ai_reason_analysis: str | None
    ai_rectification_direction: str | None
    ai_analyzed_at: datetime | None


def view_from_record(
    record_id: str,
    fields: dict[str, Any],
    *,
    workshop: str | None,
    line: str | None,
) -> CentralAlarmView:
    """单条 Bitable 记录 → 视图对象（复用 bitable_mapper 纯函数映射）。"""
    from app.modules.safety.service.central_alarm.bitable_mapper import (
        map_bitable_fields,
    )

    mapped = map_bitable_fields(fields)
    return CentralAlarmView(
        id=record_id,
        feishu_record_id=record_id,
        alarm_date=mapped.get("alarm_date"),
        post=mapped.get("post"),
        alarm_description=mapped.get("alarm_description"),
        special_note=mapped.get("special_note"),
        workshop=workshop,
        line=line,
    )


# ── 窗口函数（北京时间切天，与 service.py 既有取数口径一致）──


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


# ── 真实读取器（多表并发）──


class CentralAlarmBitableReader:
    """中控报警直读读取器真实实现。

    所有 IO 收口在注入的 BitablePageClient 上；表清单 / 表名映射可注入
    （测试零真机依赖），缺省时由 open_reader() 从配置中心 + `GET /tables` 组装。
    """

    def __init__(
        self,
        client: bd_reader.BitablePageClient,
        *,
        table_ids: list[str] | None = None,
        name_map: dict[str, str] | None = None,
        page_size: int = 500,
        concurrency: int = 10,
    ) -> None:
        self._client = client
        self._table_ids = table_ids
        self._name_map = name_map
        self._page_size = page_size
        self._sem = asyncio.Semaphore(concurrency)

    async def _business_tables(self) -> list[tuple[str, str]]:
        """返回业务表 [(table_id, table_name)]（排除配置表）。"""
        from app.modules.safety.service.central_alarm.bitable_mapper import (
            _is_config_table,
        )

        table_ids = self._table_ids
        if table_ids is None:
            from app.modules.safety.service.central_alarm.service import (
                central_alarm_table_ids,
            )

            table_ids = central_alarm_table_ids()
        name_map = self._name_map
        if name_map is None:
            name_map = await self._fetch_name_map()
        return [
            (tid, name_map.get(tid, ""))
            for tid in table_ids
            if not _is_config_table(name_map.get(tid, ""))
        ]

    async def _fetch_name_map(self) -> dict[str, str]:
        """`GET /tables` → {table_id: name}（仅在未注入 name_map 时调用）。"""
        list_tables = getattr(self._client, "list_tables", None)
        if list_tables is None:
            return {}
        items = await list_tables()
        return {
            str(i.get("table_id", "")): str(i.get("name", ""))
            for i in (items or [])
        }

    async def _fetch_one_table(
        self,
        table_id: str,
        table_name: str,
        start: datetime,
        end: datetime,
    ) -> list[CentralAlarmView]:
        from app.modules.safety.service.central_alarm.bitable_mapper import (
            derive_workshop_line,
        )

        workshop, line = derive_workshop_line(table_name)
        async with self._sem:
            records = await bd_reader.fetch_window_records(
                self._client,
                time_field=_TIME_FIELD,
                start=start,
                end=end,
                table_id=table_id,
                page_size=self._page_size,
            )
        return [
            view_from_record(
                str(r.get("record_id") or ""),
                r.get("fields") or {},
                workshop=workshop,
                line=line,
            )
            for r in records
        ]

    async def fetch_window_records(
        self,
        *,
        start_utc: datetime,
        end_utc: datetime,
        strict: bool = False,
    ) -> list[CentralAlarmView]:
        """跨全部业务表并发拉取 [start, end) 窗口内的记录。

        strict=False（默认，查询/统计用）：单表失败跳过并告警，返回部分结果；
        strict=True（日报编排用）：任一表失败聚合上抛 RuntimeError——
        调度器标 failed 走补发窗口重试，绝不让日报静默缺车间。
        """
        tables = await self._business_tables()
        results = await asyncio.gather(
            *[
                self._fetch_one_table(tid, name, start_utc, end_utc)
                for tid, name in tables
            ],
            return_exceptions=True,
        )
        views: list[CentralAlarmView] = []
        failures: list[str] = []
        logger = logging.getLogger(__name__)
        for (tid, name), result in zip(tables, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning(
                    "中控报警直读单表拉取失败 table=%s(%s): %r", name, tid, result,
                )
                failures.append(f"{name}({tid})")
                continue
            views.extend(result)
        if strict and failures:
            raise RuntimeError(
                f"中控报警直读单表拉取失败（strict）: {', '.join(failures)}"
            )
        return views

    # ── 便捷窗口方法（与 service.py 既有三个取数口径一一对应）──

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]:
        start, end = day_window(target_date)
        return await self.fetch_window_records(
            start_utc=start, end_utc=end, strict=strict,
        )

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[CentralAlarmView], datetime, datetime]:
        start, end = rolling_window(target_date)
        views = await self.fetch_window_records(
            start_utc=start, end_utc=end, strict=strict,
        )
        # 底座窗口函数返回北京时间 aware 值；渲染层 _bj() 按 UTC+8 格式化，
        # 与消防同构：返回元数据前统一转 UTC（返回值仍表示同一时刻）
        return views, start.astimezone(UTC), end.astimezone(UTC)

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]:
        start, end = week_window(week_start, week_end)
        return await self.fetch_window_records(
            start_utc=start, end_utc=end, strict=strict,
        )

    async def count_total(self) -> int:
        """全 Base 业务表记录总数（search 首页 total 字段，14 表并发单请求）。

        利用 records/search 响应的 data.total 免翻页计数；total 缺失时退化为
        首页条数（低估，仅计数展示用）。
        """
        tables = await self._business_tables()

        async def _one(tid: str) -> int:
            async with self._sem:
                result = await self._client.search_records(
                    table_id=tid, page_size=1,
                )
            total = result.get("total")
            if isinstance(total, int) and total > 0:
                return total
            return len(result.get("items") or [])

        results = await asyncio.gather(
            *[_one(tid) for tid, _name in tables], return_exceptions=True,
        )
        out = 0
        for x in results:
            if isinstance(x, BaseException):
                continue
            out += x
        return out


def open_reader(
    *,
    page_size: int = 500,
    concurrency: int = 10,
) -> CentralAlarmBitableReader:
    """默认真实实现：配置中心解析 central_alarm/alarm 连接（Base 级 client）。"""
    client = bd_reader.resolve_client("central_alarm", "alarm")
    return CentralAlarmBitableReader(
        client, page_size=page_size, concurrency=concurrency,
    )


@runtime_checkable
class CentralAlarmRecordsReader(Protocol):
    """中控报警读取器协议（真实实现 CentralAlarmBitableReader）。

    fetch_window_records 为通用窗口入口（编排 21 天历史窗口用）；
    三个便捷方法对应改造前 service.py 的三个取数口径。
    strict=True 时单表失败聚合上抛（日报路径），False 跳过失败表返回部分结果。
    """

    async def fetch_window_records(
        self, *, start_utc: datetime, end_utc: datetime, strict: bool = False,
    ) -> list[CentralAlarmView]: ...

    async def get_records_by_date(
        self, target_date: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]: ...

    async def get_records_by_rolling_window(
        self, target_date: date, *, strict: bool = False,
    ) -> tuple[list[CentralAlarmView], datetime, datetime]: ...

    async def get_records_by_week(
        self, week_start: date, week_end: date, *, strict: bool = False,
    ) -> list[CentralAlarmView]: ...

    async def count_total(self) -> int: ...
