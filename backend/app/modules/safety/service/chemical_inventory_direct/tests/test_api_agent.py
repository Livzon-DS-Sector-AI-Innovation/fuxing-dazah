"""service/API/Agent 消费端直读切换单测（chemical_inventory-direct Ticket 07）。

覆盖：service 四方法双路径（过滤/分页/统计/分析与镜像同口径）、
POST /records 直读 400 拒绝（cert renew 口径）、列表/统计直读 meta、
Agent 工具直读返回字段齐备。
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.api import chemical_inventory as api_mod
from app.modules.safety.schemas.chemical_inventory import (
    ChemicalInventoryRecordCreate,
)
from app.modules.safety.service.chemical_inventory import ChemicalInventoryService
from app.modules.safety.service.chemical_inventory_direct import config
from app.modules.safety.service.chemical_inventory_direct.views import InventoryView


def _view(vid: str, *, dept: str = "warehouse", name: str | None = None,
          total: str = "12", limit: str = "10",
          flag: str = "normal", note: list[str] | None = None) -> InventoryView:
    qty = Decimal(total) * 1000
    if note is None:
        note = ["normal"]
    return InventoryView(
        id=vid, feishu_record_id=vid,
        department=dept, storage_location="危库1",
        material_name=name or f"物料-{vid}",
        quantity=qty, unit="kg",
        total_quantity_t=Decimal(total), max_limit=Decimal(limit),
        max_limit_unit="T", hazard_classes=["flammable"], category="溶剂",
        risk_flag=flag, risk_note=note,
    )


class FakeReader:
    def __init__(self, views: list[InventoryView]) -> None:
        self._views = views

    async def fetch_all(self, *, strict: bool = False) -> list[InventoryView]:
        return list(self._views)


def _seed_direct(monkeypatch: pytest.MonkeyPatch,
                 views: list[InventoryView]) -> None:
    from app.modules.safety.service.chemical_inventory_direct import reader as rm

    monkeypatch.setattr(config, "direct_enabled", lambda: True)
    monkeypatch.setattr(rm, "open_reader", lambda **kw: FakeReader(views))


def _seed_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.safety.service.chemical_inventory_direct import reader as rm

    def _boom(*_a: Any, **_kw: Any) -> None:
        raise AssertionError("legacy 不该触直读")

    monkeypatch.setattr(config, "direct_enabled", lambda: False)
    monkeypatch.setattr(rm, "open_reader", _boom)


class TestServiceDirect:
    async def test_get_records_filter_paginate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        views = [
            _view("r1", dept="qc", name="氯化钠"),
            _view("r2", name="丙酮"),
            _view("r3", name="乙醇"),
        ]
        _seed_direct(monkeypatch, views)
        svc = ChemicalInventoryService(db=None)  # type: ignore[arg-type]

        items, total = await svc.get_records(0, 2)
        assert [v.id for v in items] == ["r1", "r2"]  # qc < warehouse
        assert total == 3

        items, total = await svc.get_records(0, 10, department="warehouse")
        assert [v.id for v in items] == ["r2", "r3"]
        assert total == 2

        items, total = await svc.get_records(0, 10, material_name="醇")
        assert [v.id for v in items] == ["r3"]
        assert total == 1

    async def test_get_stats_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        views = [
            _view("r1", total="12", limit="10", flag="warn", note=["over_limit"]),
            _view("r2", total="1", limit="10", flag="normal"),
        ]
        _seed_direct(monkeypatch, views)
        svc = ChemicalInventoryService(db=None)  # type: ignore[arg-type]
        stats = await svc.get_stats()
        assert stats == {
            "total_records": 2, "over_limit": 1,
            "warn_count": 1, "normal_count": 1,
            "by_flag": {"warn": 1, "normal": 1},
        }

    async def test_analyze_risk_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        views = [
            _view("r1", dept="warehouse", total="12", limit="10"),
            _view("r2", dept="qc", total="1", limit="10"),
        ]
        _seed_direct(monkeypatch, views)
        svc = ChemicalInventoryService(db=None)  # type: ignore[arg-type]
        res = await svc.analyze_risk()
        assert res["alert_count"] == 1
        assert len(res["items"]) == 2
        over = next(i for i in res["items"] if i["material_name"] == "物料-r1")
        assert over["risk_flag"] == "warn"
        assert over["risk_note"] == ["over_limit"]

        res_dept = await svc.analyze_risk(department="qc")
        assert res_dept["alert_count"] == 0

    async def test_run_full_scan_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.modules.safety.service.chemical_inventory_direct.risk as risk_mod

        views = [_view("r1")]
        _seed_direct(monkeypatch, views)
        scanned: list[list[Any]] = []

        async def _fake_scan(records: list[Any]) -> dict[str, int]:
            scanned.append(records)
            return {"changed": 0, "warn_count": 0, "normal_count": 1}

        monkeypatch.setattr(risk_mod, "scan_inventory_views", _fake_scan)

        class _BoomRepo:
            def __getattr__(self, _name: Any) -> Any:
                raise AssertionError("直读扫描不该碰镜像 repo")

        svc = ChemicalInventoryService(db=None)  # type: ignore[arg-type]
        svc.repo = _BoomRepo()  # type: ignore[assignment]
        scan = await svc.run_full_scan()
        assert scan == {"changed": 0, "warn_count": 0, "normal_count": 1}
        assert [v.id for v in scanned[0]] == ["r1"]


class TestServiceLegacy:
    async def test_get_records_uses_repo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_legacy(monkeypatch)
        svc = ChemicalInventoryService(db=None)  # type: ignore[arg-type]
        sent: list[tuple[int, int]] = []

        async def _fake_repo(skip: int, limit: int, *, department: str | None = None,
                             material_name: str | None = None) -> tuple[list[Any], int]:
            sent.append((skip, limit))
            return [], 0

        svc.repo = SimpleNamespace(list_inventory_records=_fake_repo)  # type: ignore[assignment]
        await svc.get_records(5, 10)
        assert sent == [(5, 10)]

    async def test_run_full_scan_uses_orm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _seed_legacy(monkeypatch)
        svc = ChemicalInventoryService(db=None)  # type: ignore[arg-type]
        called: list[str] = []

        async def _fake_analyze(records: list[Any]) -> dict[str, int]:
            called.append("analyze")
            return {"changed": 0, "warn_count": 0, "normal_count": 0}

        async def _fake_rows() -> list[Any]:
            return []

        svc.repo = SimpleNamespace(list_all_inventory_records=_fake_rows)  # type: ignore[assignment]
        monkeypatch.setattr(svc, "analyze_records", _fake_analyze)
        await svc.run_full_scan()
        assert called == ["analyze"]


class TestApiEndpoints:
    async def test_post_records_direct_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "direct_enabled", lambda: True)
        data = ChemicalInventoryRecordCreate(department="warehouse", material_name="乙醇")
        resp = await api_mod.create_inventory_record(data=data, db=None, current_user=None)  # type: ignore[arg-type]
        assert resp.code == 400
        assert "直读" in resp.message

    async def test_post_records_legacy_ok(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "direct_enabled", lambda: False)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def create_record(self, _data: dict[str, Any]) -> InventoryView:
                return _view("recNew", flag="normal")

        monkeypatch.setattr(api_mod, "ChemicalInventoryService", _FakeSvc)
        data = ChemicalInventoryRecordCreate(department="warehouse", material_name="乙醇")
        resp = await api_mod.create_inventory_record(data=data, db=None, current_user=None)  # type: ignore[arg-type]
        assert resp.code == 200
        assert resp.data["id"] == "recNew"

    async def test_get_records_direct_meta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "direct_enabled", lambda: True)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def get_records(self, _skip: int, _limit: int, *,
                                  department: str | None = None,
                                  material_name: str | None = None) -> tuple[list[Any], int]:
                return [_view("rec1")], 1

        monkeypatch.setattr(api_mod, "ChemicalInventoryService", _FakeSvc)
        resp = await api_mod.get_inventory_records(
            page=1, page_size=50, department=None, material_name=None,
            db=None,  # type: ignore[arg-type]
            current_user=None,
        )
        assert resp.meta["mode"] == "direct"
        assert "elapsed_ms" in resp.meta
        assert resp.meta["total"] == 1
        assert resp.data[0]["id"] == "rec1"

    async def test_get_records_legacy_meta_plain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(config, "direct_enabled", lambda: False)

        class _FakeSvc:
            def __init__(self, _db: Any) -> None:
                pass

            async def get_records(self, _skip: int, _limit: int, *,
                                  department: str | None = None,
                                  material_name: str | None = None) -> tuple[list[Any], int]:
                return [], 0

        monkeypatch.setattr(api_mod, "ChemicalInventoryService", _FakeSvc)
        resp = await api_mod.get_inventory_records(
            page=1, page_size=50, department=None, material_name=None,
            db=None,  # type: ignore[arg-type]
            current_user=None,
        )
        assert "mode" not in resp.meta
        assert resp.meta["total"] == 0


class TestAgentTool:
    async def test_query_tool_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            query_chemical_inventory,
        )

        views = [
            _view("recQ", name="乙醇", flag="warn", note=["over_limit"]),
        ]
        _seed_direct(monkeypatch, views)
        ctx = SimpleNamespace(deps=SimpleNamespace(db=object()))
        res = await query_chemical_inventory(ctx,  # type: ignore[arg-type]
                                             department=None,
                                             material_name="乙醇", limit=50)
        assert res["total"] == 1
        item = res["items"][0]
        assert item["id"] == "recQ"
        assert item["material_name"] == "乙醇"
        assert item["risk_flag"] == "warn"
        assert item["quantity"] == 12000.0

    async def test_analyze_tool_direct(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.modules.safety.business_agent.tools.read_tools import (
            analyze_chemical_risk,
        )

        _seed_direct(monkeypatch, [_view("recA", total="12", limit="10")])
        ctx = SimpleNamespace(deps=SimpleNamespace(db=object()))
        res = await analyze_chemical_risk(ctx, department=None)  # type: ignore[arg-type]
        assert res["alert_count"] == 1
        assert res["items"][0]["risk_note"] == ["over_limit"]
