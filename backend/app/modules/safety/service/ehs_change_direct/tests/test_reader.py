"""ehs_change 直读读取器单测（Ticket 02）——两表并发/分页/
automatic_fields/跳行/strict 两态/缓存。"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableQueryError
from app.modules.safety.service.ehs_change_direct.cache import (
    CachedEhsChangeReader,
)
from app.modules.safety.service.ehs_change_direct.reader import (
    EhsChangeBitableReader,
)


class FakePageClient:
    """search_records 替身：按 preset 页返回（协议含 strict 参数）。"""

    def __init__(
        self,
        pages: list[list[dict[str, Any]]],
        *,
        fail: bool = False,
    ):
        self._pages = pages
        self._fail = fail
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
            "automatic_fields": automatic_fields, "strict": strict,
        })
        if self._fail:
            raise BitableQueryError("table unreachable")
        idx = 0 if page_token is None else int(page_token)
        items = self._pages[idx]
        has_more = idx + 1 < len(self._pages)
        result: dict[str, Any] = {
            "items": items, "has_more": has_more,
            "total": sum(len(p) for p in self._pages),
        }
        if has_more:
            result["page_token"] = str(idx + 1)
        return result


def _approval_row(rid: str, status: str = "已通过", created: int | None = None,
                  ) -> dict[str, Any]:
    row: dict[str, Any] = {
        "record_id": rid,
        "fields": {"申请状态": status, "变更名称": [{"text": f"变更{rid}"}]},
    }
    if created is not None:
        row["created_time"] = created
    return row


def _acceptance_row(rid: str, status: str = "已通过",
                    created: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "record_id": rid,
        "fields": {"申请状态": status, "变更名称": [{"text": f"验收{rid}"}]},
    }
    if created is not None:
        row["created_time"] = created
    return row


class TestFetchAll:
    async def test_two_tables_merged_approval_first(self) -> None:
        approval = FakePageClient([[_approval_row("recA", created=1776300000000)]])
        acceptance = FakePageClient([[_acceptance_row("recB", created=1776300001000)]])
        views = await EhsChangeBitableReader(approval, acceptance).fetch_all(
            strict=True,
        )
        assert [v.record_id for v in views] == ["recA", "recB"]
        assert [v.kind for v in views] == ["approval", "acceptance"]
        assert views[0].created_time_ms == 1776300000000
        assert views[0].title == "变更recA"
        assert views[1].title == "验收recB"

    async def test_pagination_across_pages(self) -> None:
        approval = FakePageClient([
            [_approval_row("recA1"), _approval_row("recA2")],
            [_approval_row("recA3")],
        ])
        acceptance = FakePageClient([[_acceptance_row("recB1")]])
        views = await EhsChangeBitableReader(approval, acceptance).fetch_all(
            strict=True,
        )
        assert [v.record_id for v in views] == ["recA1", "recA2", "recA3", "recB1"]
        assert len(approval.calls) == 2  # 两个页 token 各一次

    async def test_automatic_fields_always_on(self) -> None:
        approval = FakePageClient([[_approval_row("recA")]])
        acceptance = FakePageClient([[]])
        await EhsChangeBitableReader(approval, acceptance).fetch_all(strict=False)
        assert all(c["automatic_fields"] for c in approval.calls)

    async def test_deleted_row_skipped(self) -> None:
        approval = FakePageClient([
            [_approval_row("recA"), _approval_row("recD", status="已删除")],
        ])
        acceptance = FakePageClient([[]])
        views = await EhsChangeBitableReader(approval, acceptance).fetch_all(
            strict=True,
        )
        assert [v.record_id for v in views] == ["recA"]

    async def test_strict_true_raises_on_failure(self) -> None:
        approval = FakePageClient([[]], fail=True)
        acceptance = FakePageClient([[]])
        with pytest.raises(BitableQueryError):
            await EhsChangeBitableReader(approval, acceptance).fetch_all(
                strict=True,
            )

    async def test_no_created_time_defaults_none(self) -> None:
        approval = FakePageClient([[_approval_row("recA")]])
        acceptance = FakePageClient([[]])
        views = await EhsChangeBitableReader(approval, acceptance).fetch_all()
        assert views[0].created_time_ms is None


class TestCachedReader:
    async def test_ttl_window_hits_cache(self) -> None:
        inner = FakePageClient([[_approval_row("recA")]])
        acceptance = FakePageClient([[]])
        reader = CachedEhsChangeReader(
            EhsChangeBitableReader(inner, acceptance), ttl_seconds=60,
        )
        first = await reader.fetch_all()
        second = await reader.fetch_all()
        assert [v.record_id for v in first] == ["recA"]
        assert second == first
        assert len(inner.calls) == 1  # TTL 窗口内只拉一次

    async def test_strict_bypasses_cache(self) -> None:
        inner = FakePageClient([[_approval_row("recA")]])
        acceptance = FakePageClient([[]])
        reader = CachedEhsChangeReader(
            EhsChangeBitableReader(inner, acceptance), ttl_seconds=60,
        )
        await reader.fetch_all()
        await reader.fetch_all(strict=True)
        assert len(inner.calls) == 2  # strict 强制回源

    async def test_ttl_zero_passthrough(self) -> None:
        inner = FakePageClient([[_approval_row("recA")]])
        acceptance = FakePageClient([[]])
        reader = CachedEhsChangeReader(
            EhsChangeBitableReader(inner, acceptance), ttl_seconds=0,
        )
        await reader.fetch_all()
        await reader.fetch_all()
        assert len(inner.calls) == 2


class TestOpenReaderSingleton:
    def test_open_reader_cached_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.service.bitable_direct import reader as bd_reader
        from app.modules.safety.service.ehs_change_direct import (
            reader as ehs_reader,
        )

        client = FakePageClient([[]])
        monkeypatch.setattr(bd_reader, "resolve_client", lambda *a, **k: client)
        monkeypatch.setattr(ehs_reader, "_shared_reader", None)
        r1 = ehs_reader.open_reader()
        r2 = ehs_reader.open_reader()
        assert r1 is r2
        monkeypatch.setattr(ehs_reader, "_shared_reader", None)  # 还原全局
