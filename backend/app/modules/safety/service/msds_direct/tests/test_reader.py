"""msds 直读读取器单测（Ticket 02）——单表全量/分页/strict 两态/工厂单例。"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.msds_direct.reader import (
    MsdsBitableReader,
    open_reader,
)


class FakePageClient:
    """search_records 替身：按 preset 页返回（协议含 strict 参数）。"""

    def __init__(self, pages: list[list[dict[str, Any]]]):
        self._pages = pages
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
        self.calls.append({"page_token": page_token, "page_size": page_size})
        idx = int(page_token or 0)
        items = self._pages[idx]
        has_more = idx + 1 < len(self._pages)
        result: dict[str, Any] = {
            "items": items,
            "has_more": has_more,
            "total": sum(len(p) for p in self._pages),
        }
        if has_more:
            result["page_token"] = str(idx + 1)
        return result


def _row(rid: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {"record_id": rid, "fields": fields}


def _fields(name: str = "异丙醇") -> dict[str, Any]:
    return {
        "物质名称": [{"text": name, "type": "text"}],
        "日期": 1785974400000,
    }


class TestFetchAll:
    async def test_single_table_full_fetch(self) -> None:
        reader = MsdsBitableReader(
            FakePageClient([[_row("recA", _fields("异丙醇"))]]),
            table_id="tblMSDS",
        )
        views = await reader.fetch_all(strict=True)
        assert [v.id for v in views] == ["recA"]
        assert views[0].name == "异丙醇"

    async def test_pagination(self) -> None:
        reader = MsdsBitableReader(
            FakePageClient([
                [_row("rec1", _fields("a")), _row("rec2", _fields("b"))],
                [_row("rec3", _fields("c"))],
            ]),
            table_id="tblMSDS",
        )
        views = await reader.fetch_all(strict=True)
        assert [v.id for v in views] == ["rec1", "rec2", "rec3"]

    async def test_empty_record_id_skipped(self) -> None:
        reader = MsdsBitableReader(
            FakePageClient([[_row("rec1", {}), {"record_id": "", "fields": {}}]]),
            table_id="tblMSDS",
        )
        views = await reader.fetch_all()
        assert [v.id for v in views] == ["rec1"]

    async def test_strict_true_raises_on_error(self) -> None:
        class BoomClient(FakePageClient):
            async def search_records(self, *a: Any, **kw: Any) -> dict[str, Any]:
                raise RuntimeError("network down")

        reader = MsdsBitableReader(BoomClient([]), table_id="tblMSDS")
        with pytest.raises(Exception):
            await reader.fetch_all(strict=True)


class TestOpenReader:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.service.msds_direct import reader as reader_mod

        monkeypatch.setattr(reader_mod, "_shared_reader", None)

    def test_open_reader_unconfigured_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.bitable_config import store as store_mod

        monkeypatch.setattr(store_mod.store, "get_connection", lambda d, k: None)
        with pytest.raises(BitableConfigError):
            open_reader()

    def test_open_reader_resolves_registry_kind(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.service.bitable_direct import reader as bd_reader
        from app.modules.safety.service.msds_direct.cache import CachedReader

        seen: list[tuple[str, str]] = []

        def fake_resolve(
            domain: str, kind: str, *, table_id: str | None = None,
        ) -> bd_reader.SafetyBitableClient:
            seen.append((domain, kind))
            return FakePageClient([])  # type: ignore[return-value]

        monkeypatch.setattr(bd_reader, "resolve_client", fake_resolve)
        reader = open_reader()
        assert seen == [("msds", "registry")]
        assert isinstance(reader, CachedReader)  # D4 条款触发：TTL 缓存包装
        # 单例：重复调用不重复建连/不重置缓存
        assert open_reader() is reader


class _CountingReader:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        self.calls += 1
        return [{"id": f"rec{self.calls}"}]  # type: ignore[list-item]


class TestCachedReader:
    async def test_ttl_window_reuses_and_strict_bypasses(self) -> None:
        from app.modules.safety.service.msds_direct.cache import CachedReader

        inner = _CountingReader()
        reader = CachedReader(inner, ttl_seconds=60)
        first = await reader.fetch_all()
        second = await reader.fetch_all()
        assert inner.calls == 1  # TTL 窗口内复用
        assert first == second
        strict = await reader.fetch_all(strict=True)
        assert inner.calls == 2  # strict 恒绕过缓存
        assert strict == [{"id": "rec2"}]

    async def test_ttl_nonpositive_passthrough(self) -> None:
        from app.modules.safety.service.msds_direct.cache import CachedReader

        inner = _CountingReader()
        reader = CachedReader(inner, ttl_seconds=0)
        await reader.fetch_all()
        await reader.fetch_all()
        assert inner.calls == 2  # 直通不缓存

    async def test_view_objects_shared_readonly_shallow_copy(self) -> None:
        from app.modules.safety.service.msds_direct.cache import CachedReader
        from app.modules.safety.service.msds_direct.views import MsdsDocumentView

        inner_view = MsdsDocumentView(id="rec1")

        class FixedReader:
            async def fetch_all(
                self, *, strict: bool = False,
            ) -> list[MsdsDocumentView]:
                return [inner_view]

        reader = CachedReader(FixedReader(), ttl_seconds=60)
        got = await reader.fetch_all()
        assert got[0] is inner_view  # 视图对象共享（只读约定）
        assert got is not await reader.fetch_all()  # 列表浅拷贝
