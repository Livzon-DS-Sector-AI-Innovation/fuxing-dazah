"""oh 直读读取器单测（Ticket 02）——两表全量/分页/strict 两态/工厂单例/缓存。"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.oh_direct.reader import (
    OhBitableReader,
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


def _position_fields(dept: str = "生产部", pos: str = "操作工") -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if dept:
        fields["部门"] = [{"text": dept, "type": "text"}]
    if pos:
        fields["岗位"] = [{"text": pos, "type": "text"}]
    return fields


def _factor_fields(name: str = "噪声", ppe: str = "耳塞") -> dict[str, Any]:
    return {
        "危害因素名称": [{"text": name, "type": "text"}],
        "呼吸防护用品": [{"text": ppe, "type": "text"}],
    }


class TestFetch:
    async def test_positions_full_fetch_and_skip_rules(self) -> None:
        reader = OhBitableReader(
            FakePageClient([[
                _row("recA", _position_fields()),
                _row("recB", {}),  # 部门岗位均空 → 跳行（spec D7）
                {"record_id": "", "fields": _position_fields()},  # 空 rid 丢弃
            ]]),
            FakePageClient([[]]),
        )
        views = await reader.fetch_positions(strict=True)
        assert [v.id for v in views] == ["recA"]
        assert views[0].department == "生产部"
        assert views[0].hazard_factors_status == "empty"

    async def test_factors_fetch(self) -> None:
        reader = OhBitableReader(
            FakePageClient([]),
            FakePageClient([[_row("recF", _factor_fields())]]),
        )
        views = await reader.fetch_factors(strict=True)
        assert [v.id for v in views] == ["recF"]
        assert views[0].factor_name == "噪声"
        assert views[0].ppe_respiratory == "耳塞"

    async def test_pagination(self) -> None:
        reader = OhBitableReader(
            FakePageClient([
                [_row("rec1", _position_fields("甲部")), _row("rec2", _position_fields("乙部"))],
                [_row("rec3", _position_fields("丙部"))],
            ]),
            FakePageClient([]),
        )
        views = await reader.fetch_positions(strict=True)
        assert [v.id for v in views] == ["rec1", "rec2", "rec3"]

    async def test_strict_true_raises_on_error(self) -> None:
        class BoomClient(FakePageClient):
            async def search_records(self, *a: Any, **kw: Any) -> dict[str, Any]:
                raise RuntimeError("network down")

        reader = OhBitableReader(BoomClient([]), FakePageClient([]))
        with pytest.raises(Exception):
            await reader.fetch_positions(strict=True)


class TestOpenReader:
    @pytest.fixture(autouse=True)
    def _reset_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.service.oh_direct import reader as reader_mod

        monkeypatch.setattr(reader_mod, "_shared_reader", None)

    def test_open_reader_unconfigured_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.bitable_config import store as store_mod

        monkeypatch.setattr(store_mod.store, "get_connection", lambda d, k: None)
        with pytest.raises(BitableConfigError):
            open_reader()

    def test_open_reader_resolves_registry_kinds(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.modules.safety.service.bitable_direct import reader as bd_reader
        from app.modules.safety.service.oh_direct.cache import CachedOhReader

        seen: list[tuple[str, str]] = []

        def fake_resolve(
            domain: str, kind: str, *, table_id: str | None = None,
        ) -> Any:
            seen.append((domain, kind))
            return FakePageClient([])

        monkeypatch.setattr(bd_reader, "resolve_client", fake_resolve)
        reader = open_reader()
        assert seen == [("oh", "position"), ("oh", "hazard_factor")]
        assert isinstance(reader, CachedOhReader)  # D4 条款触发：TTL 缓存包装
        # 单例：重复调用不重复建连/不重置缓存
        assert open_reader() is reader


class _CountingReader:
    def __init__(self) -> None:
        self.position_calls = 0
        self.factor_calls = 0

    async def fetch_positions(self, *, strict: bool = False) -> list[Any]:
        self.position_calls += 1
        return [{"id": f"pos{self.position_calls}"}]

    async def fetch_factors(self, *, strict: bool = False) -> list[Any]:
        self.factor_calls += 1
        return [{"id": f"fac{self.factor_calls}"}]


class TestCachedOhReader:
    async def test_ttl_window_reuses_per_table(self) -> None:
        from app.modules.safety.service.oh_direct.cache import CachedOhReader

        inner = _CountingReader()
        reader = CachedOhReader(inner, ttl_seconds=60)
        first = await reader.fetch_positions()
        second = await reader.fetch_positions()
        assert inner.position_calls == 1  # 同表 TTL 窗口内复用
        assert first == second
        await reader.fetch_factors()
        await reader.fetch_factors()
        assert inner.factor_calls == 1  # 两表各自独立缓存

    async def test_strict_bypasses(self) -> None:
        from app.modules.safety.service.oh_direct.cache import CachedOhReader

        inner = _CountingReader()
        reader = CachedOhReader(inner, ttl_seconds=60)
        strict = await reader.fetch_positions(strict=True)
        assert inner.position_calls == 1  # strict 恒绕过缓存
        assert strict == [{"id": "pos1"}]

    async def test_ttl_nonpositive_passthrough(self) -> None:
        from app.modules.safety.service.oh_direct.cache import CachedOhReader

        inner = _CountingReader()
        reader = CachedOhReader(inner, ttl_seconds=0)
        await reader.fetch_positions()
        await reader.fetch_positions()
        assert inner.position_calls == 2  # 直通不缓存

    async def test_view_objects_shared_shallow_copy(self) -> None:
        from app.modules.safety.service.oh_direct.cache import CachedOhReader
        from app.modules.safety.service.oh_direct.views import OhPositionView

        inner_view = OhPositionView(id="rec1")

        class FixedReader:
            async def fetch_positions(
                self, *, strict: bool = False,
            ) -> list[OhPositionView]:
                return [inner_view]

            async def fetch_factors(
                self, *, strict: bool = False,
            ) -> list[Any]:
                return []

        reader = CachedOhReader(FixedReader(), ttl_seconds=60)
        got = await reader.fetch_positions()
        assert got[0] is inner_view  # 视图对象共享（只读约定）
        assert got is not await reader.fetch_positions()  # 列表浅拷贝
