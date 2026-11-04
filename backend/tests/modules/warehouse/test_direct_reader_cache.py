"""直读层单测：TTL 缓存 + reader 解析 + MAX_PAGES 防御（2026-11-04 直读改造）。

不触网：fake adapter 注入 / monkeypatch time.monotonic。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.warehouse.bitable_adapter import WarehouseBitableError
from app.modules.warehouse.direct import reader
from app.modules.warehouse.direct.cache import DirectCache


class FakeAdapter:
    """按页返回预置记录；always_token=True 时 page_token 永不断（测防御）。"""

    def __init__(self, pages: list[list[dict]], always_token: bool = False) -> None:
        self.pages = pages
        self.calls = 0
        self.always_token = always_token

    async def search_records_page(
        self, table_key: str, *, field_names: list[str] | None = None,
        limit: int = 500, page_token: str | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        idx = int(page_token) if page_token else 0
        records = self.pages[idx] if idx < len(self.pages) else []
        has_more = self.always_token or idx + 1 < len(self.pages)
        return {
            "records": records,
            "page_token": str(idx + 1) if has_more else "",
        }


# ── DirectCache ────────────────────────────────────────────────

class TestDirectCache:
    async def test_hit_within_ttl_loader_called_once(self) -> None:
        calls = {"n": 0}

        async def loader() -> list[int]:
            calls["n"] += 1
            return [1, 2]

        cache = DirectCache(lambda: 300)
        assert await cache.get(loader) == [1, 2]
        assert await cache.get(loader) == [1, 2]
        assert calls["n"] == 1

    async def test_expired_reloads(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = {"t": 0.0}
        monkeypatch.setattr(
            "app.modules.warehouse.direct.cache.time.monotonic",
            lambda: clock["t"],
        )
        calls = {"n": 0}

        async def loader() -> list[int]:
            calls["n"] += 1
            return [1]

        cache = DirectCache(lambda: 300)
        await cache.get(loader)
        clock["t"] = 301  # TTL 过期
        await cache.get(loader)
        assert calls["n"] == 2

    async def test_ttl_zero_bypasses(self) -> None:
        calls = {"n": 0}

        async def loader() -> list[int]:
            calls["n"] += 1
            return [1]

        cache = DirectCache(lambda: 0)
        await cache.get(loader)
        await cache.get(loader)
        assert calls["n"] == 2

    async def test_invalidate_forces_reload(self) -> None:
        calls = {"n": 0}

        async def loader() -> list[int]:
            calls["n"] += 1
            return [1]

        cache = DirectCache(lambda: 300)
        await cache.get(loader)
        cache.invalidate()
        await cache.get(loader)
        assert calls["n"] == 2

    async def test_force_bypasses_fresh_entry(self) -> None:
        calls = {"n": 0}

        async def loader() -> list[int]:
            calls["n"] += 1
            return [1]

        cache = DirectCache(lambda: 300)
        await cache.get(loader)
        await cache.get(loader, force=True)
        assert calls["n"] == 2


# ── reader 解析 ────────────────────────────────────────────────

class TestParseDatetime:
    def test_ms_number(self) -> None:
        dt = reader.parse_datetime(1767060616781)
        assert dt == datetime(2025, 12, 30, 2, 10, 16, 781000, tzinfo=UTC)

    def test_ms_digit_string(self) -> None:
        # 出库表 领用日期 实测形态：毫秒字符串
        assert reader.parse_datetime("1767060616781") == reader.parse_datetime(1767060616781)

    def test_iso_text(self) -> None:
        assert reader.parse_datetime("2026-03-11") == datetime(2026, 3, 11, tzinfo=UTC)

    def test_empty_and_garbage(self) -> None:
        assert reader.parse_datetime(None) is None
        assert reader.parse_datetime("") is None
        assert reader.parse_datetime("不是日期") is None
        assert reader.parse_datetime(42) is None  # 秒/毫秒都不像


class TestFetchStocks:
    async def test_mapping_and_status(self) -> None:
        adapter = FakeAdapter([[
            {
                "record_id": "rec1",
                "fields": {
                    "代码": [{"text": "10101", "type": "text"}],   # 富文本形态
                    "物料名称": "碳酸钠",
                    "物料批号": "10101-260101",
                    "剩余数量": 25.5,
                    "单位": "Kg",
                    "有效期至/复验期至": 1835000000000,  # 2028-03 许可误差
                    "QC出报": "已出报（合格）",
                    "QC取样情况": "已取样",
                    "QA放行": "放行",
                    "物料大类": "原辅料",
                },
            },
            {
                "record_id": "rec2",
                "fields": {
                    "代码": "10102", "物料名称": "亚硫酸氢钠",
                    "物料批号": "", "剩余数量": 0, "单位": "",
                    "QC出报": "", "QA放行": "未放行",
                },
            },
            {"record_id": "rec3", "fields": {}},  # 全空脏行跳过
        ]])
        views = await reader.fetch_stocks(adapter)
        assert len(views) == 2
        v1 = views[0]
        assert (v1.code, v1.name, v1.quantity, v1.unit) == ("10101", "碳酸钠", 25.5, "Kg")
        assert v1.status == "normal"
        assert v1.qc_release_status == "放行"
        assert v1.expiry_date is not None
        assert v1.category == "raw"
        v2 = views[1]
        assert v2.status == "quarantine"          # 未放行且无不合格
        assert v2.expiry_date is None

    async def test_frozen_when_unqualified(self) -> None:
        adapter = FakeAdapter([[
            {"record_id": "recF", "fields": {
                "代码": "X", "物料名称": "Y", "剩余数量": 1,
                "QC出报": "已出报（不合格）", "QA放行": "",
            }},
        ]])
        assert (await reader.fetch_stocks(adapter))[0].status == "frozen"


class TestMaxPagesGuard:
    async def test_too_many_pages_raises(self) -> None:
        adapter = FakeAdapter([[]], always_token=True)
        with pytest.raises(WarehouseBitableError, match="防御上限"):
            await reader.fetch_all_pages(adapter, "material_stock", ["代码"])


class TestFetchMaterials:
    async def test_dirty_rows_skipped(self) -> None:
        adapter = FakeAdapter([[
            {"record_id": "m1", "fields": {"代码": "10101", "物料名称": "碳酸钠",
                                            "物料大类": "原辅料", "飞书规格": "25Kg/包"}},
            {"record_id": "m2", "fields": {"代码": "", "物料名称": "无代码"}},
        ]])
        views = await reader.fetch_materials(adapter)
        assert len(views) == 1
        assert views[0].category == "raw"
        assert views[0].spec == "25Kg/包"
