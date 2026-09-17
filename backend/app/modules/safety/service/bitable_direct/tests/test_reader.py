"""底座读取协议 / 分页批量查询 单测（假 client，无网络、无 DB）。

覆盖票据 04 验收项：单页 / 多页 / 超过页数上限 / API 报错 / 连接缺失或停用 /
只请求指定字段 / 协议可注入替身 / 全程不出现逐条单条读。
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.feishu.bitable_client import (
    BitableQueryError as ClientQueryError,
)
from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.service.bitable_direct import reader
from app.modules.safety.service.bitable_direct.errors import (
    BitableConfigError,
    BitableQueryError,
)


def _page(
    items: list[dict[str, Any]] | None = None,
    *,
    has_more: bool = False,
    page_token: str | None = None,
    total: int | None = None,
) -> dict[str, Any]:
    return {
        "items": items or [],
        "has_more": has_more,
        "page_token": page_token,
        "total": total,
    }


def _rec(record_id: str) -> dict[str, Any]:
    return {"record_id": record_id, "fields": {}}


def _conn(**overrides: Any) -> ConnectionView:
    base: dict[str, Any] = {
        "domain": "fire_alarm",
        "kind": "alarm",
        "app_token": "app1",
        "table_id": "tbl1",
        "extra_table_ids": (),
        "enabled": True,
        "note": None,
        "status": "db",
    }
    base.update(overrides)
    return ConnectionView(**base)


class FakePageClient:
    """假 page 级 client：按脚本返回分页结果或抛错，记录每次调用参数。"""

    def __init__(
        self,
        pages: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        *,
        error_on_call: int | None = None,
    ) -> None:
        self.pages: list[dict[str, Any]] = list(pages or [])
        self.error = error
        self.error_on_call = error_on_call
        self.calls: list[dict[str, Any]] = []

    async def search_records(
        self,
        table_id: str | None = None,
        *,
        filter_info: dict[str, Any] | None = None,
        field_names: list[str] | None = None,
        sort: list[dict[str, Any]] | None = None,
        automatic_fields: bool = False,
        page_size: int = reader.DEFAULT_PAGE_SIZE,
        page_token: str | None = None,
        strict: bool = True,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "table_id": table_id,
                "filter_info": filter_info,
                "field_names": field_names,
                "sort": sort,
                "automatic_fields": automatic_fields,
                "page_size": page_size,
                "page_token": page_token,
                "strict": strict,
            }
        )
        if self.error is not None and (
            self.error_on_call is None or self.error_on_call == len(self.calls)
        ):
            raise self.error
        index = len(self.calls) - 1
        if index < len(self.pages):
            return dict(self.pages[index])
        return _page([])


class TestFetchAllRecords:
    async def test_single_page(self) -> None:
        client = FakePageClient([_page([_rec("a"), _rec("b")])])

        result = await reader.fetch_all_records(client, filter_info={"x": 1})

        assert [r["record_id"] for r in result] == ["a", "b"]
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["page_token"] is None
        assert call["page_size"] == reader.DEFAULT_PAGE_SIZE
        assert call["strict"] is True
        assert call["filter_info"] == {"x": 1}

    async def test_multi_page_threads_page_token(self) -> None:
        client = FakePageClient(
            [
                _page([_rec("a")], has_more=True, page_token="t1"),
                _page([_rec("b")], has_more=True, page_token="t2"),
                _page([_rec("c")]),
            ]
        )

        result = await reader.fetch_all_records(client)

        assert [r["record_id"] for r in result] == ["a", "b", "c"]
        assert [call["page_token"] for call in client.calls] == [None, "t1", "t2"]

    async def test_empty_result(self) -> None:
        client = FakePageClient([_page([])])
        assert await reader.fetch_all_records(client) == []

    async def test_page_limit_raises(self) -> None:
        pages = [
            _page([_rec(f"r{i}")], has_more=True, page_token=f"t{i}")
            for i in range(10)
        ]
        client = FakePageClient(pages)

        with pytest.raises(BitableQueryError, match="上限"):
            await reader.fetch_all_records(client, max_pages=3)

        assert len(client.calls) == 3

    async def test_max_pages_zero_still_probes_one_page(self) -> None:
        client = FakePageClient([_page([_rec("a")], has_more=True, page_token="t")])

        with pytest.raises(BitableQueryError, match="上限"):
            await reader.fetch_all_records(client, max_pages=0)

        assert len(client.calls) == 1

    async def test_has_more_without_token_raises(self) -> None:
        client = FakePageClient([_page([_rec("a")], has_more=True, page_token=None)])

        with pytest.raises(BitableQueryError, match="page_token"):
            await reader.fetch_all_records(client)

    async def test_api_error_is_translated_to_base_error(self) -> None:
        client = FakePageClient(error=ClientQueryError(1254001, "table not found"))

        with pytest.raises(BitableQueryError) as excinfo:
            await reader.fetch_all_records(client)

        message = str(excinfo.value)
        assert "1254001" in message
        assert "table not found" in message
        assert isinstance(excinfo.value.__cause__, ClientQueryError)

    async def test_non_strict_returns_already_fetched(self) -> None:
        client = FakePageClient(
            pages=[_page([_rec("a")], has_more=True, page_token="t1")],
            error=ClientQueryError(1254291, "too many requests"),
            error_on_call=2,
        )

        result = await reader.fetch_all_records(client, strict=False)

        assert [r["record_id"] for r in result] == ["a"]

    async def test_field_names_and_options_forwarded(self) -> None:
        client = FakePageClient([_page([])])

        await reader.fetch_all_records(
            client,
            field_names=["报警时间", "报警类型"],
            sort=[{"field_name": "报警时间", "desc": True}],
            automatic_fields=True,
        )

        call = client.calls[0]
        assert call["field_names"] == ["报警时间", "报警类型"]
        assert call["sort"] == [{"field_name": "报警时间", "desc": True}]
        assert call["automatic_fields"] is True

    @pytest.mark.parametrize(
        ("given", "expected"),
        [(0, 1), (-5, 1), (200, 200), (500, 500), (9999, reader.MAX_PAGE_SIZE)],
    )
    async def test_page_size_clamped(self, given: int, expected: int) -> None:
        client = FakePageClient([_page([])])
        await reader.fetch_all_records(client, page_size=given)
        assert client.calls[0]["page_size"] == expected


class TestResolveClient:
    def test_uses_connection_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = _conn()
        monkeypatch.setattr(store, "get_connection", lambda *a, **k: conn)
        captured: dict[str, Any] = {}

        class FakeClient:
            def __init__(
                self, app_token: str | None = None, table_id: str | None = None
            ) -> None:
                captured["app_token"] = app_token
                captured["table_id"] = table_id

        monkeypatch.setattr(reader, "SafetyBitableClient", FakeClient)

        result = reader.resolve_client("fire_alarm", "alarm")

        assert isinstance(result, FakeClient)
        assert captured == {"app_token": "app1", "table_id": "tbl1"}

    def test_table_id_override_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "get_connection", lambda *a, **k: _conn())
        captured: dict[str, Any] = {}

        class FakeClient:
            def __init__(
                self, app_token: str | None = None, table_id: str | None = None
            ) -> None:
                captured["table_id"] = table_id

        monkeypatch.setattr(reader, "SafetyBitableClient", FakeClient)

        reader.resolve_client("fire_alarm", "alarm", table_id="tblX")

        assert captured["table_id"] == "tblX"

    def test_missing_connection_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "get_connection", lambda *a, **k: None)

        with pytest.raises(BitableConfigError, match="fire_alarm/alarm"):
            reader.resolve_client("fire_alarm", "alarm")

    def test_disabled_connection_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        conn = _conn(enabled=False, status="disabled")
        monkeypatch.setattr(store, "get_connection", lambda *a, **k: conn)

        with pytest.raises(BitableConfigError, match="已停用"):
            reader.resolve_client("fire_alarm", "alarm")


class TestClientRecordsReader:
    async def test_delegates_with_default_table_id(self) -> None:
        client = FakePageClient([_page([_rec("a")])])
        records_reader = reader.ClientRecordsReader(client=client, table_id="tbl1")

        result = await records_reader.list_all_records(filter_info={"x": 1})

        assert [r["record_id"] for r in result] == ["a"]
        assert client.calls[0]["table_id"] == "tbl1"
        assert client.calls[0]["filter_info"] == {"x": 1}

    async def test_per_call_table_id_overrides_default(self) -> None:
        client = FakePageClient([_page([])])
        records_reader = reader.ClientRecordsReader(client=client, table_id="tbl1")

        await records_reader.list_all_records(table_id="tbl2")

        assert client.calls[0]["table_id"] == "tbl2"

    async def test_default_table_id_passes_none(self) -> None:
        client = FakePageClient([_page([])])
        records_reader = reader.ClientRecordsReader(client=client)

        await records_reader.list_all_records()

        assert client.calls[0]["table_id"] is None

    async def test_max_pages_is_enforced(self) -> None:
        pages = [
            _page([_rec(f"r{i}")], has_more=True, page_token=f"t{i}")
            for i in range(5)
        ]
        client = FakePageClient(pages)
        records_reader = reader.ClientRecordsReader(client=client, max_pages=2)

        with pytest.raises(BitableQueryError, match="上限"):
            await records_reader.list_all_records()

        assert len(client.calls) == 2


class TestOpenReader:
    def test_wraps_resolved_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake = FakePageClient([_page([])])
        monkeypatch.setattr(reader, "resolve_client", lambda *a, **k: fake)

        records_reader = reader.open_reader(
            "fire_alarm", "alarm", table_id="tbl1", max_pages=7
        )

        assert isinstance(records_reader, reader.ClientRecordsReader)
        assert records_reader.client is fake
        assert records_reader.table_id == "tbl1"
        assert records_reader.max_pages == 7

    async def test_reads_through_wrapped_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakePageClient([_page([_rec("a")])])
        monkeypatch.setattr(reader, "resolve_client", lambda *a, **k: fake)
        records_reader = reader.open_reader("fire_alarm", "alarm")

        result = await records_reader.list_all_records(
            field_names=["报警时间"], page_size=100
        )

        assert [r["record_id"] for r in result] == ["a"]
        assert fake.calls[0]["field_names"] == ["报警时间"]
        assert fake.calls[0]["page_size"] == 100

    def test_propagates_config_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(store, "get_connection", lambda *a, **k: None)

        with pytest.raises(BitableConfigError):
            reader.open_reader("fire_alarm", "alarm")


class TestNoSingleRecordRead:
    def test_reader_source_has_no_single_record_methods(self) -> None:
        tree = ast.parse(Path(str(reader.__file__)).read_text(encoding="utf-8"))
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert "get_record" not in attrs
        assert "get_record_shared_url" not in attrs

    async def test_fetch_never_calls_single_record_even_if_available(self) -> None:
        class SneakyClient(FakePageClient):
            def __init__(self) -> None:
                super().__init__([_page([])])
                self.single_calls = 0

            async def get_record(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                self.single_calls += 1
                return {}

        client = SneakyClient()

        await reader.fetch_all_records(client)

        assert client.single_calls == 0


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpClient:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(
        self,
        url: str,
        headers: Any = None,
        params: Any = None,
        json: Any = None,
    ) -> _FakeResponse:
        self._captured["json"] = json
        self._captured["params"] = params
        return _FakeResponse(
            {
                "code": 0,
                "data": {
                    "items": [],
                    "has_more": False,
                    "page_token": None,
                    "total": 0,
                },
            }
        )


class TestClientFieldNamesPassthrough:
    """钉住 bitable_client 的 field_names 透传（底座 reader 依赖它）。"""

    async def _client(
        self, monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]
    ) -> SafetyBitableClient:
        monkeypatch.setattr(
            httpx, "AsyncClient", lambda **kw: _FakeHttpClient(captured)
        )
        monkeypatch.setattr(store, "get_connection", lambda *a, **k: None)

        async def fake_token(self: SafetyBitableClient) -> str:
            return "tok"

        monkeypatch.setattr(SafetyBitableClient, "_token", fake_token)
        return SafetyBitableClient(app_token="app", table_id="tbl")

    async def test_search_records_sends_field_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        client = await self._client(monkeypatch, captured)

        await client.search_records(field_names=["报警时间", "报警类型"], page_size=100)

        assert captured["json"]["field_names"] == ["报警时间", "报警类型"]

    async def test_search_records_omits_field_names_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        client = await self._client(monkeypatch, captured)

        await client.search_records(page_size=100)

        assert "field_names" not in captured["json"]

    async def test_list_all_records_passes_field_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}
        client = await self._client(monkeypatch, captured)

        await client.list_all_records(field_names=["报警时间"])

        assert captured["json"]["field_names"] == ["报警时间"]

def _timed(record_id: str, moment: datetime | None) -> dict[str, Any]:
    """带「报警时间」的记录；moment 为 None 表示时间字段缺失。"""
    fields: dict[str, Any] = {}
    if moment is not None:
        fields["报警时间"] = int(moment.timestamp() * 1000)
    return {"record_id": record_id, "fields": fields}


class TestFetchWindowRecords:
    """票据 09：按时间字段倒序分页 + 见到早于起点的记录即提前终止。"""

    START = datetime(2026, 9, 15, 0, 0, tzinfo=UTC)
    END = datetime(2026, 9, 17, 0, 0, tzinfo=UTC)
    MID = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
    OLD = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)

    async def test_single_page_stops_early(self) -> None:
        client = FakePageClient([
            _page(
                [
                    _timed("new", self.MID),
                    _timed("edge_start", self.START),
                    _timed("old", self.OLD),
                ],
                has_more=True,
                page_token="t1",
            )
        ])

        result = await reader.fetch_window_records(
            client, time_field="报警时间", start=self.START, end=self.END
        )

        assert [r["record_id"] for r in result] == ["new", "edge_start"]
        assert len(client.calls) == 1
        assert client.calls[0]["sort"] == [{"field_name": "报警时间", "desc": True}]
        assert client.calls[0]["page_token"] is None

    async def test_keeps_paging_until_older_than_start(self) -> None:
        client = FakePageClient([
            _page([_timed("a", self.MID)], has_more=True, page_token="t1"),
            _page([_timed("old", self.OLD)], has_more=True, page_token="t2"),
        ])

        result = await reader.fetch_window_records(
            client, time_field="报警时间", start=self.START, end=self.END
        )

        assert [r["record_id"] for r in result] == ["a"]
        assert len(client.calls) == 2
        assert client.calls[1]["page_token"] == "t1"

    async def test_end_is_exclusive(self) -> None:
        client = FakePageClient([
            _page([_timed("at_end", self.END), _timed("old", self.OLD)])
        ])

        result = await reader.fetch_window_records(
            client, time_field="报警时间", start=self.START, end=self.END
        )

        assert result == []

    async def test_records_without_time_are_skipped(self) -> None:
        client = FakePageClient([
            _page([
                _timed("no_time", None),
                _timed("in_window", self.MID),
                _timed("old", self.OLD),
            ])
        ])

        result = await reader.fetch_window_records(
            client, time_field="报警时间", start=self.START, end=self.END
        )

        assert [r["record_id"] for r in result] == ["in_window"]

    async def test_last_page_without_more_returns(self) -> None:
        client = FakePageClient([_page([_timed("a", self.MID)])])

        result = await reader.fetch_window_records(
            client, time_field="报警时间", start=self.START, end=self.END
        )

        assert [r["record_id"] for r in result] == ["a"]
        assert len(client.calls) == 1

    async def test_empty_result_when_no_records(self) -> None:
        client = FakePageClient([_page([])])

        result = await reader.fetch_window_records(
            client, time_field="报警时间", start=self.START, end=self.END
        )

        assert result == []

    async def test_page_limit_raises_instead_of_truncating(self) -> None:
        pages = [
            _page([_timed(f"r{i}", self.MID)], has_more=True, page_token=f"t{i}")
            for i in range(4)
        ]
        client = FakePageClient(pages)

        with pytest.raises(BitableQueryError):
            await reader.fetch_window_records(
                client,
                time_field="报警时间",
                start=self.START,
                end=self.END,
                max_pages=2,
            )

        assert len(client.calls) == 2

    async def test_api_error_propagates(self) -> None:
        client = FakePageClient(error=BitableQueryError("boom"))

        with pytest.raises(BitableQueryError):
            await reader.fetch_window_records(
                client, time_field="报警时间", start=self.START, end=self.END
            )

    async def test_passes_through_table_and_fields(self) -> None:
        client = FakePageClient([_page([_timed("a", self.MID)])])

        await reader.fetch_window_records(
            client,
            time_field="报警时间",
            start=self.START,
            end=self.END,
            table_id="tblX",
            field_names=["报警时间", "报警类型"],
            page_size=123,
        )

        call = client.calls[0]
        assert call["table_id"] == "tblX"
        assert call["field_names"] == ["报警时间", "报警类型"]
        assert call["page_size"] == 123
