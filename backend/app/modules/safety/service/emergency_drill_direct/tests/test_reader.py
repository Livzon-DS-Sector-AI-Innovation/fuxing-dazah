"""emergency_drill 直读读取器单测（Ticket 02）。

替身 page client 驱动：分页聚合、strict 两态、空 record_id 跳过、
open_reader 工厂解析（BitableConfigError）。
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableConfigError
from app.modules.safety.service.emergency_drill_direct.reader import (
    EmergencyDrillBitableReader,
    open_reader,
)
from app.modules.safety.service.emergency_drill_direct.views import (
    attachment_store_paths,
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


class TestFetchAll:
    async def test_pagination_and_view_mapping(self) -> None:
        client = FakePageClient([
            [_row("rec1", {"演练类型": "应急疏散演练", "实施时间": 1768924800000})],
            [_row("rec2", {"演练部门": "安全环保部"})],
        ])
        reader = EmergencyDrillBitableReader(client, table_id="tblX")
        views = await reader.fetch_all(strict=True)
        assert [v.id for v in views] == ["rec1", "rec2"]
        assert views[0].drill_type == "应急疏散演练"
        assert views[0].execution_time is not None
        assert views[1].department == "安全环保部"
        # 分页推进：第二页以 page_token 拉取
        assert [c["page_token"] for c in client.calls] == [None, "1"]

    async def test_empty_record_id_skipped(self) -> None:
        client = FakePageClient([
            [_row("rec1", {}), {"record_id": "", "fields": {}}, {"fields": {}}],
        ])
        views = await EmergencyDrillBitableReader(client).fetch_all()
        assert [v.id for v in views] == ["rec1"]

    async def test_strict_false_returns_partial_on_error(self) -> None:
        class BoomClient(FakePageClient):
            async def search_records(self, *a: Any, **kw: Any) -> dict[str, Any]:
                if kw.get("page_token"):
                    raise RuntimeError("network down")
                return await super().search_records(*a, **kw)

        client = BoomClient([[_row("rec1", {"演练类型": "消防器材培训"})]])
        views = await EmergencyDrillBitableReader(client).fetch_all(strict=False)
        assert [v.id for v in views] == ["rec1"]

    async def test_strict_true_raises_on_error(self) -> None:
        class BoomClient(FakePageClient):
            async def search_records(self, *a: Any, **kw: Any) -> dict[str, Any]:
                raise RuntimeError("network down")

        client = BoomClient([])
        with pytest.raises(Exception):
            await EmergencyDrillBitableReader(client).fetch_all(strict=True)

    async def test_attachment_paths_in_views(self) -> None:
        client = FakePageClient([
            [_row("rec1", {"签到表": [{"file_token": "tok", "name": "a.pdf"}]})],
        ])
        views = await EmergencyDrillBitableReader(client).fetch_all()
        assert views[0].signin_file == attachment_store_paths(
            "rec1", [{"file_token": "tok", "name": "a.pdf"}]
        )


class TestOpenReader:
    def test_open_reader_unconfigured_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.bitable_config import store as store_mod

        monkeypatch.setattr(
            store_mod.store, "get_connection",
            lambda domain, kind: None,
        )
        with pytest.raises(BitableConfigError):
            open_reader()

    def test_open_reader_builds_reader(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.service.bitable_direct import reader as bd_reader

        seen: dict[str, str] = {}

        def fake_resolve(
            domain: str, kind: str, *, table_id: str | None = None
        ) -> bd_reader.SafetyBitableClient:
            seen.update({"domain": domain, "kind": kind})
            return FakePageClient([])  # type: ignore[return-value]

        monkeypatch.setattr(bd_reader, "resolve_client", fake_resolve)
        reader = open_reader()
        assert seen == {"domain": "emergency_drill", "kind": "main"}
        assert isinstance(reader, EmergencyDrillBitableReader)
