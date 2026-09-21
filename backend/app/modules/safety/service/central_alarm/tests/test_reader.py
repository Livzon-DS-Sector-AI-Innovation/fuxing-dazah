"""Ticket 02：中控报警直读 reader 单测（注入替身 client，零真机依赖）。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.modules.safety.service.central_alarm import reader as ca_reader
from app.modules.safety.service.central_alarm.bitable_mapper import (
    derive_workshop_line,
)

# ── 替身：BitablePageClient ──


class FakePageClient:
    """记录 search 调用并按 table_id 返回预置记录。"""

    def __init__(self, records_by_table: dict[str, list[dict[str, Any]]]) -> None:
        self._records = records_by_table
        self.calls: list[dict[str, Any]] = []

    async def search_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = 500,
        page_token: str | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        self.calls.append({
            "table_id": table_id,
            "sort": sort,
            "field_names": field_names,
            "page_size": page_size,
        })
        items = self._records.get(table_id or "", [])
        return {"items": items, "has_more": False, "page_token": None}


_NAME_MAP = {
    "tblA": "车间一（达托）",
    "tblB": "新罐区",
    "tblCFG": "中控报警数据源配置",
}
_TABLE_IDS = ["tblA", "tblB", "tblCFG"]


def _rec(record_id: str, *, y: int, mo: int, d: int, h: int = 2) -> dict[str, Any]:
    """构造一条 Bitable 原始记录（日期字段毫秒时间戳）。"""
    dt = datetime(y, mo, d, h, 0, tzinfo=UTC)
    return {
        "record_id": record_id,
        "fields": {
            "日期": dt.timestamp() * 1000,
            "岗位": "DCS 内操",
            "报警情况说明": f"报警 {record_id}",
            "特殊情况说明": "",
        },
    }


def _reader(
    records_by_table: dict[str, list[dict[str, Any]]],
    *,
    table_ids: list[str] | None = None,
    name_map: dict[str, str] | None = None,
) -> tuple[ca_reader.CentralAlarmBitableReader, FakePageClient]:
    client = FakePageClient(records_by_table)
    reader = ca_reader.CentralAlarmBitableReader(
        client,
        table_ids=table_ids if table_ids is not None else _TABLE_IDS,
        name_map=name_map if name_map is not None else _NAME_MAP,
    )
    return reader, client


async def test_config_table_excluded() -> None:
    r, client = _reader({"tblA": [_rec("r1", y=2026, mo=9, d=20)]})
    start = datetime(2026, 9, 19, 16, tzinfo=UTC)
    end = datetime(2026, 9, 20, 16, tzinfo=UTC)
    views = await r.fetch_window_records(start_utc=start, end_utc=end)
    assert [v.id for v in views] == ["r1"]
    assert views[0].workshop == "车间一"
    assert views[0].line == "达托"
    called_tables = [c["table_id"] for c in client.calls]
    assert "tblCFG" not in called_tables
    assert set(called_tables) == {"tblA", "tblB"}


async def test_window_trim_and_view_mapping() -> None:
    r, _client = _reader({
        "tblA": [
            _rec("in1", y=2026, mo=9, d=20, h=2),
            _rec("out", y=2026, mo=9, d=18, h=2),  # 窗口外
        ],
        "tblB": [_rec("in2", y=2026, mo=9, d=20, h=5)],
    })
    start = datetime(2026, 9, 19, 16, tzinfo=UTC)
    end = datetime(2026, 9, 20, 16, tzinfo=UTC)
    views = await r.fetch_window_records(start_utc=start, end_utc=end)
    assert {v.id for v in views} == {"in1", "in2"}
    by_id = {v.id: v for v in views}
    assert by_id["in2"].workshop == "新罐区"
    assert by_id["in2"].line is None
    assert by_id["in1"].post == "DCS 内操"
    assert by_id["in1"].ai_pattern is None  # 直读 ai_* 恒 None
    assert by_id["in1"].feishu_record_id == "in1"


async def test_sort_desc_uses_time_field() -> None:
    r, client = _reader({})
    start = datetime(2026, 9, 19, 16, tzinfo=UTC)
    end = datetime(2026, 9, 20, 16, tzinfo=UTC)
    await r.fetch_window_records(start_utc=start, end_utc=end)
    for call in client.calls:
        assert call["sort"] == [{"field_name": "日期", "desc": True}]


async def test_rolling_window_semantics() -> None:
    start, end = ca_reader.rolling_window(date(2026, 9, 20))
    # 前日北京时间 17:00 = UTC 09:00；当日 17:00 = UTC 09:00
    assert start == datetime(2026, 9, 19, 9, tzinfo=UTC)
    assert end == datetime(2026, 9, 20, 9, tzinfo=UTC)


async def test_day_window_semantics() -> None:
    start, end = ca_reader.day_window(date(2026, 9, 20))
    assert start == datetime(2026, 9, 19, 16, tzinfo=UTC)
    assert end == datetime(2026, 9, 20, 16, tzinfo=UTC)


async def test_derive_workshop_line_known_cases() -> None:
    assert derive_workshop_line("车间一（达托）") == ("车间一", "达托")
    assert derive_workshop_line("车间二（达巴、非达）") == ("车间二", "达巴、非达")
    assert derive_workshop_line("新罐区") == ("新罐区", None)


def test_view_from_record_defaults() -> None:
    rec = _rec("r9", y=2026, mo=9, d=20)
    view = ca_reader.view_from_record(
        "r9", rec["fields"], workshop="车间一", line="达托",
    )
    assert view.id == "r9"
    assert view.source == "bitable"
    assert view.alarm_date is not None
    assert view.created_at is None
