"""直读读取器单测（chemical_inventory-direct Ticket 03）。

替身实现 BitablePageClient 协议全方法（含 strict 参数，mypy 结构化检查口径）；
覆盖单表全量映射、无物料名称跳过、分页、strict 两态、镜像口径排序、单位透传。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from app.modules.safety.service.bitable_direct.errors import BitableQueryError
from app.modules.safety.service.chemical_inventory_direct.reader import (
    InventoryBitableReader,
    InventoryRecordsReader,
)


class FakePageClient:
    """BitablePageClient 替身：按页返回预置 items 或抛错。"""

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


def _item(rid: str, name: str = "乙醇", **extra: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "部门": "仓储部",
        "物料名称": [{"text": name, "type": "text"}],
        "库存数量": 10,
        "风险标记": "正常",
    }
    fields.update(extra)
    return {"record_id": rid, "fields": fields}


def _reader(
    pages: list[list[dict[str, Any]]], *, error: Exception | None = None
) -> InventoryBitableReader:
    return InventoryBitableReader(FakePageClient(pages, error=error), table_id="tblX")


class TestFetchAll:
    async def test_maps_and_sorts(self) -> None:
        reader = _reader([[_item("recB", "乙醇"), _item("recA", "丙酮")]])
        views = await reader.fetch_all()
        assert [v.id for v in views] == ["recA", "recB"]  # 同部门按物料名排
        assert views[0].material_name == "丙酮"
        assert views[0].feishu_record_id == "recA"
        assert views[0].department == "warehouse"
        assert views[0].risk_flag == "normal"
        assert views[0].quantity == Decimal("10")

    async def test_dirty_rows_skipped(self) -> None:
        """无 record_id / 无物料名称的行跳过（与镜像 sync 同口径）。"""
        reader = _reader([[
            _item("recOk"),
            {"record_id": "", "fields": {"物料名称": [{"text": "x", "type": "text"}]}},
            {"record_id": "recNoName", "fields": {"部门": "仓储部"}},
        ]])
        views = await reader.fetch_all()
        assert [v.id for v in views] == ["recOk"]

    async def test_pagination(self) -> None:
        reader = _reader([[_item("rec1")], [_item("rec2")]])
        views = await reader.fetch_all()
        assert [v.id for v in views] == ["rec1", "rec2"]

    async def test_unit_passthrough(self) -> None:
        """单位脏选项行透传（与镜像逐字一致）。"""
        reader = _reader([[_item("recU", 单位="槽车")]])
        views = await reader.fetch_all()
        assert views[0].unit == "槽车"

    async def test_protocol_runtime_check(self) -> None:
        assert isinstance(_reader([[]]), InventoryRecordsReader)


class TestStrictModes:
    async def test_strict_true_raises(self) -> None:
        reader = _reader([[]], error=BitableQueryError("boom"))
        with pytest.raises(BitableQueryError):
            await reader.fetch_all(strict=True)

    async def test_strict_false_returns_partial(self) -> None:
        """查询/统计容错：首页失败返回空（不上抛）。"""
        reader = _reader([[]], error=BitableQueryError("boom"))
        assert await reader.fetch_all(strict=False) == []


class TestOpenReaderSourceSwitch:
    """open_reader 按 SAFETY_CHEMICAL_INVENTORY_SOURCE 分支（P1-T2）。

    组装件全部 monkeypatch（resolve_client / build_office_client /
    bitable_config store），零真机依赖；单例按 source 取值缓存，切换重建。
    """

    def _reset_singleton(self) -> None:
        import app.modules.safety.service.chemical_inventory_direct.reader as rd

        rd._shared_reader = None
        rd._shared_reader_source = None

    def test_bitable_source_returns_bitable_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.modules.safety.service.chemical_inventory_direct.reader as rd

        self._reset_singleton()
        monkeypatch.delenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", raising=False)
        built: dict[str, Any] = {}

        def _fake_resolve(domain: str, kind: str, **kw: Any) -> Any:
            built["bitable"] = (domain, kind)
            return FakePageClient([[]])

        monkeypatch.setattr(rd.bd_reader, "resolve_client", _fake_resolve)
        reader = rd.open_reader()
        assert built["bitable"] == ("chemical_inventory", "inventory")
        assert isinstance(reader._inner, InventoryBitableReader)
        self._reset_singleton()

    def test_sheet_source_returns_sheets_reader(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.modules.safety.service.chemical_inventory_direct.reader as rd
        from app.modules.safety.service.chemical_inventory_direct.sheet_reader import (
            SheetsInventoryReader,
        )

        self._reset_singleton()
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        built: dict[str, Any] = {}

        class _FakeOffice:
            pass

        def _fake_build() -> Any:
            built["office"] = True
            return _FakeOffice()

        def _fake_conn(domain: str, kind: str) -> Any:
            from types import SimpleNamespace

            built["conn"] = (domain, kind)
            return SimpleNamespace(app_token="H0YWsAf52hBAIDtmJlxcqThZn2c", enabled=True)

        monkeypatch.setattr(rd, "build_office_client", _fake_build)
        monkeypatch.setattr(
            "app.modules.safety.bitable_config.store.store.get_connection", _fake_conn
        )
        reader = rd.open_reader()
        assert built["conn"] == ("chemical_inventory", "source_sheet")
        assert isinstance(reader._inner, SheetsInventoryReader)
        self._reset_singleton()

    def test_sheet_source_unconfigured_raises(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.modules.safety.service.chemical_inventory_direct.reader as rd
        from app.modules.safety.service.bitable_direct.errors import BitableConfigError

        self._reset_singleton()
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        monkeypatch.setattr(
            "app.modules.safety.bitable_config.store.store.get_connection",
            lambda domain, kind: None,
        )
        with pytest.raises(BitableConfigError):
            rd.open_reader()
        self._reset_singleton()

    def test_singleton_rebuilds_on_source_change(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import app.modules.safety.service.chemical_inventory_direct.reader as rd
        from app.modules.safety.service.chemical_inventory_direct.sheet_reader import (
            SheetsInventoryReader,
        )

        self._reset_singleton()
        monkeypatch.setattr(
            rd.bd_reader, "resolve_client", lambda *a, **kw: FakePageClient([[]])
        )

        def _fake_conn(domain: str, kind: str) -> Any:
            from types import SimpleNamespace

            return SimpleNamespace(app_token="tok", enabled=True)

        monkeypatch.setattr(
            "app.modules.safety.bitable_config.store.store.get_connection", _fake_conn
        )
        monkeypatch.setattr(rd, "build_office_client", lambda: object())

        monkeypatch.delenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", raising=False)
        first = rd.open_reader()
        assert isinstance(first._inner, InventoryBitableReader)

        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        second = rd.open_reader()
        assert second is not first
        assert isinstance(second._inner, SheetsInventoryReader)
        self._reset_singleton()
