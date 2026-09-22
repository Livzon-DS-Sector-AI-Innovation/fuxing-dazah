"""key_risk_op 直读读取器与缓存单测（Ticket 02）。

替身实现 BitablePageClient 协议全方法（含 strict 参数）；覆盖「已删除」排除、
report_no 兜底、分页、strict 两态、缓存 TTL 两态/绕过/关闭。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableQueryError
from app.modules.safety.service.key_risk_op_direct.cache import CachedReader
from app.modules.safety.service.key_risk_op_direct.reader import (
    KeyRiskOpBitableReader,
    KeyRiskOpRecordsReader,
)


class FakePageClient:
    def __init__(
        self, pages: list[list[dict[str, Any]]], *, error: Exception | None = None
    ) -> None:
        self._pages = pages or [[]]
        self._error = error
        self.calls = 0

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
        self.calls += 1
        if self._error is not None:
            raise self._error
        index = 0 if not page_token else int(page_token)
        items = self._pages[index] if index < len(self._pages) else []
        has_more = index + 1 < len(self._pages)
        return {
            "items": items,
            "has_more": has_more,
            "page_token": str(index + 1) if has_more else None,
        }


def _item(rid: str, *, status: str = "已通过",
          start_ms: int | None = 1764311580000, **extra: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "申请编号": {"text": f"NO-{rid}", "link": "https://x"},
        "申请状态": status,
        "部门": "提炼六部",
        "作业内容": f"作业-{rid}",
    }
    if start_ms is not None:
        fields["作业开始时间"] = start_ms
    fields.update(extra)
    return {"record_id": rid, "fields": fields}


def _reader(
    pages: list[list[dict[str, Any]]], *, error: Exception | None = None
) -> KeyRiskOpBitableReader:
    return KeyRiskOpBitableReader(FakePageClient(pages, error=error), table_id="tblX")


class TestFetchAll:
    async def test_maps_and_sorts_desc_nulls_last(self) -> None:
        early = _item("recE", start_ms=1764311580000)   # 2025-11-28
        late = _item("recL", start_ms=1780000000000)    # 2026-05-末
        none_v = _item("recN", start_ms=None)
        views = await _reader([[late, none_v, early]]).fetch_all()
        assert [v.id for v in views] == ["recL", "recE", "recN"]
        assert views[0].report_no == "NO-recL"
        assert views[0].source == "bitable"

    async def test_deleted_rows_skipped(self) -> None:
        """「已删除」行排除（与镜像 sync 跳过同口径）。"""
        views = await _reader([[
            _item("recOk"),
            _item("recDel", status="已删除"),
        ]]).fetch_all()
        assert [v.id for v in views] == ["recOk"]

    async def test_report_no_fallback(self) -> None:
        views = await _reader([[_item("recABCDEF123456", 申请编号={"link": "x"})]]).fetch_all()
        assert views[0].report_no == "BT-ABCDEF123456"

    async def test_pagination_and_protocol(self) -> None:
        reader = _reader([[_item("rec1")], [_item("rec2")]])
        assert isinstance(reader, KeyRiskOpRecordsReader)
        views = await reader.fetch_all()
        assert [v.id for v in views] == ["rec1", "rec2"]

    async def test_strict_true_raises(self) -> None:
        with pytest.raises(BitableQueryError):
            await _reader([[]], error=BitableQueryError("boom")).fetch_all(strict=True)

    async def test_strict_false_partial(self) -> None:
        assert await _reader([[]], error=BitableQueryError("boom")).fetch_all() == []


class TestCachedReader:
    def _inner(self, views: list[Any], fail_second: bool = False) -> Any:
        state = {"calls": 0}

        class _Inner:
            async def fetch_all(self, *, strict: bool = False) -> list[Any]:
                state["calls"] += 1
                if fail_second and state["calls"] == 2:
                    raise RuntimeError("boom")
                return list(views)

        self.state = state
        return _Inner()

    async def test_ttl_hit_and_expire(self) -> None:
        inner = self._inner([SimpleNamespace(id="rec1")])
        cached = CachedReader(inner, ttl_seconds=60)
        await cached.fetch_all()
        assert self.state["calls"] == 1
        second = await cached.fetch_all()
        assert self.state["calls"] == 1  # 命中缓存
        assert [v.id for v in second] == ["rec1"]
        # TTL 过期（at 回拨模拟）
        assert cached._entry is not None  # noqa: SLF001
        cached._entry.at -= 61  # noqa: SLF001
        await cached.fetch_all()
        assert self.state["calls"] == 2

    async def test_strict_bypasses_cache(self) -> None:
        inner = self._inner([SimpleNamespace(id="rec1")])
        cached = CachedReader(inner, ttl_seconds=60)
        await cached.fetch_all(strict=True)
        await cached.fetch_all(strict=True)
        assert self.state["calls"] == 2

    async def test_ttl_zero_passthrough(self) -> None:
        inner = self._inner([SimpleNamespace(id="rec1")])
        cached = CachedReader(inner, ttl_seconds=0)
        await cached.fetch_all()
        await cached.fetch_all()
        assert self.state["calls"] == 2
        assert cached.cached is False

    async def test_views_copied_not_shared(self) -> None:
        inner = self._inner([SimpleNamespace(id="rec1")])
        cached = CachedReader(inner, ttl_seconds=60)
        first = await cached.fetch_all()
        first.clear()
        second = await cached.fetch_all()
        assert len(second) == 1  # 缓存返回副本，外部修改不穿透
