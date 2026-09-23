"""hazard_id 直读读取器单测（Ticket 03）——全量/分页/automatic_fields/
strict 两态/工厂单例/缓存。"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import (
    BitableConfigError,
    BitableQueryError,
)
from app.modules.safety.service.hazard_id_direct.reader import (
    HazardIdBitableReader,
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
        self.calls.append({
            "page_token": page_token, "page_size": page_size,
            "automatic_fields": automatic_fields,
        })
        if page_token is None:
            idx = 0
        else:
            idx = int(page_token)
        items = self._pages[idx]
        has_more = idx + 1 < len(self._pages)
        result: dict[str, Any] = {
            "items": items, "has_more": has_more,
            "total": sum(len(p) for p in self._pages),
        }
        if has_more:
            result["page_token"] = str(idx + 1)
        return result


def _row(rid: str, created: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "record_id": rid,
        "fields": {"岗位（人工）": [{"text": f"岗位{rid}", "type": "text"}]},
    }
    if created is not None:
        row["created_time"] = created
    return row


class TestFetchAll:
    async def test_full_fetch_with_created_time(self) -> None:
        client = FakePageClient([
            [_row("recA", 1776302265000), _row("recB", 1776302266000)],
            [_row("recC", 1776304888000)],
        ])
        views = await HazardIdBitableReader(client).fetch_all(strict=True)
        assert [v.record_id for v in views] == ["recA", "recB", "recC"]
        assert views[0].created_time_ms == 1776302265000
        assert views[2].created_time_ms == 1776304888000
        assert views[0].position == "岗位recA"

    async def test_automatic_fields_always_on(self) -> None:
        """恒传 automatic_fields=True 取 created_time 排序键（spec D5）。"""
        client = FakePageClient([[_row("recA", 1)]])
        await HazardIdBitableReader(client).fetch_all(strict=True)
        assert all(c["automatic_fields"] is True for c in client.calls)

    async def test_empty_record_id_dropped(self) -> None:
        client = FakePageClient([
            [_row("recA"), {"record_id": "", "fields": {}}, {"fields": {}}],
        ])
        views = await HazardIdBitableReader(client).fetch_all(strict=True)
        assert [v.record_id for v in views] == ["recA"]

    async def test_missing_created_time_tolerated(self) -> None:
        client = FakePageClient([[_row("recA")]])
        views = await HazardIdBitableReader(client).fetch_all(strict=True)
        assert views[0].created_time_ms is None

    async def test_strict_true_raises_on_error(self) -> None:
        class BoomClient(FakePageClient):
            async def search_records(self, *a: Any, **kw: Any) -> dict[str, Any]:
                raise BitableQueryError("network down")

        with pytest.raises(BitableQueryError):
            await HazardIdBitableReader(BoomClient([])).fetch_all(strict=True)

    async def test_strict_false_returns_partial(self) -> None:
        class PartialClient(FakePageClient):
            async def search_records(
                self, table_id: str | None = None, **kw: Any,
            ) -> dict[str, Any]:
                if kw.get("page_token"):
                    raise BitableQueryError("network down")
                return await super().search_records(table_id, **kw)

        client = PartialClient([[_row("recA")], [_row("recB")]])
        views = await HazardIdBitableReader(client).fetch_all(strict=False)
        assert [v.record_id for v in views] == ["recA"]  # 已拉到的部分


class TestOpenReader:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.service.hazard_id_direct import (
            reader as reader_mod,
        )

        monkeypatch.setattr(reader_mod, "_shared_reader", None)

    def test_open_reader_unconfigured_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.bitable_config import store as store_mod

        monkeypatch.setattr(
            store_mod.store, "get_connection", lambda d, k: None,
        )
        with pytest.raises(BitableConfigError):
            open_reader()

    def test_open_reader_resolves_registry_kind(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.service.bitable_direct import reader as bd_reader
        from app.modules.safety.service.hazard_id_direct.cache import (
            CachedHazardIdReader,
        )

        seen: list[tuple[str, str]] = []

        def fake_resolve(
            domain: str, kind: str, *, table_id: str | None = None,
        ) -> Any:
            seen.append((domain, kind))
            return FakePageClient([])

        monkeypatch.setattr(bd_reader, "resolve_client", fake_resolve)
        reader = open_reader()
        assert seen == [("hazard_id", "identification")]
        assert isinstance(reader, CachedHazardIdReader)  # D4：TTL 缓存包装
        assert open_reader() is reader  # 单例


class _CountingReader:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        self.calls += 1
        return [{"record_id": f"rec{self.calls}"}]


class TestCachedHazardIdReader:
    async def test_ttl_window_reuses(self) -> None:
        from app.modules.safety.service.hazard_id_direct.cache import (
            CachedHazardIdReader,
        )

        inner = _CountingReader()
        reader = CachedHazardIdReader(inner, ttl_seconds=60)
        first = await reader.fetch_all()
        second = await reader.fetch_all()
        assert inner.calls == 1
        assert first == second

    async def test_strict_bypasses(self) -> None:
        from app.modules.safety.service.hazard_id_direct.cache import (
            CachedHazardIdReader,
        )

        inner = _CountingReader()
        reader = CachedHazardIdReader(inner, ttl_seconds=60)
        await reader.fetch_all()
        strict = await reader.fetch_all(strict=True)
        assert inner.calls == 2  # strict 恒绕过缓存
        assert strict == [{"record_id": "rec2"}]

    async def test_ttl_nonpositive_passthrough(self) -> None:
        from app.modules.safety.service.hazard_id_direct.cache import (
            CachedHazardIdReader,
        )

        inner = _CountingReader()
        reader = CachedHazardIdReader(inner, ttl_seconds=0)
        await reader.fetch_all()
        await reader.fetch_all()
        assert inner.calls == 2  # 直通不缓存

    async def test_view_objects_shared_shallow_copy(self) -> None:
        from app.modules.safety.service.hazard_id_direct.cache import (
            CachedHazardIdReader,
        )
        from app.modules.safety.service.hazard_id_direct.views import (
            HazardIdentificationView,
        )

        inner_view = HazardIdentificationView(record_id="rec1")

        class FixedReader:
            async def fetch_all(
                self, *, strict: bool = False,
            ) -> list[HazardIdentificationView]:
                return [inner_view]

        reader = CachedHazardIdReader(FixedReader(), ttl_seconds=60)
        got = await reader.fetch_all()
        assert got[0] is inner_view  # 视图对象共享（只读约定）
        assert got is not await reader.fetch_all()  # 列表浅拷贝
