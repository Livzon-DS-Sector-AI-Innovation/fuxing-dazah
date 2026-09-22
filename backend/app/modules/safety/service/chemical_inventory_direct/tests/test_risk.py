"""直读风险重算 + 回写管线单测（chemical_inventory-direct Ticket 05）。

覆盖：重算计数口径（与镜像 analyze_records 同构）、changed 仅差异行、
WRITEBACK_RISK 两态、真实 sync_record_flags_to_bitable 的写请求只含两风险列 +
先防环（httpx.AsyncClient 哨兵拦截，零网络）。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

import app.modules.safety.feishu.chemical_inventory_bitable_handler as handler_mod
import app.modules.safety.service.chemical_inventory_direct.risk as risk_mod
from app.modules.safety.service.chemical_inventory_direct import config
from app.modules.safety.service.chemical_inventory_direct.contract import (
    WRITEBACK_FIELD_NAMES,
)
from app.modules.safety.service.chemical_inventory_direct.views import InventoryView


def _view(vid: str, *, total: str = "0.5", limit: str = "10",
          flag: str = "normal", note: list[str] | None = None) -> InventoryView:
    """默认正常行；total > limit 时命中 R01 超量；quantity 与 total 换算一致（不触 R07）。"""
    qty = Decimal(total) * 1000  # kg → T 与填报一致
    if note is None:
        note = ["normal"]
    return InventoryView(
        id=vid, feishu_record_id=vid,
        department="warehouse", storage_location="危库1", material_name=f"物料-{vid}",
        package_spec="160Kg/桶", quantity=qty, unit="kg",
        total_quantity_t=Decimal(total), max_limit=Decimal(limit),
        max_limit_unit="T", hazard_classes=["flammable"], category="溶剂",
        risk_flag=flag, risk_note=note,
    )


class TestScanInventoryViews:
    async def test_counts_and_changed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """超量行命中 warn；与当前值一致的行不算 changed；计数按计算值。"""
        monkeypatch.setattr(config, "writeback_risk_enabled", lambda: False)
        views = [
            _view("recOver", total="12", limit="10", flag="normal", note=["normal"]),
            _view("recOk", total="12", limit="10", flag="warn", note=["over_limit"]),
        ]
        scan = await risk_mod.scan_inventory_views(views)
        assert scan == {"changed": 1, "warn_count": 2, "normal_count": 0}
        assert views[0].risk_flag == "warn"
        assert views[0].risk_note == ["over_limit"]

    async def test_writeback_gate_on_calls_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[InventoryView]] = []

        async def _spy(records: list[InventoryView]) -> int:
            calls.append(records)
            return len(records)

        monkeypatch.setattr(config, "writeback_risk_enabled", lambda: True)
        monkeypatch.setattr(handler_mod, "sync_record_flags_to_bitable", _spy)
        views = [_view("recOver", total="12", limit="10")]
        scan = await risk_mod.scan_inventory_views(views)
        assert scan["changed"] == 1
        assert len(calls) == 1
        assert [v.id for v in calls[0]] == ["recOver"]

    async def test_writeback_gate_off_no_sync(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def _boom(records: list[InventoryView]) -> int:
            raise AssertionError("WRITEBACK_RISK 关时不该回写")

        monkeypatch.setattr(config, "writeback_risk_enabled", lambda: False)
        monkeypatch.setattr(handler_mod, "sync_record_flags_to_bitable", _boom)
        scan = await risk_mod.scan_inventory_views(
            [_view("recOver", total="12", limit="10")]
        )
        assert scan["changed"] == 1  # 日报仍用内存计算值

    async def test_writeback_failure_degrades(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回写异常降级为日志，不阻断扫描结果（与 legacy 语义一致）。"""
        async def _boom(records: list[InventoryView]) -> int:
            raise RuntimeError("feishu down")

        monkeypatch.setattr(config, "writeback_risk_enabled", lambda: True)
        monkeypatch.setattr(handler_mod, "sync_record_flags_to_bitable", _boom)
        scan = await risk_mod.scan_inventory_views(
            [_view("recOver", total="12", limit="10")]
        )
        assert scan["changed"] == 1

    async def test_empty_views(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, "writeback_risk_enabled", lambda: True)
        assert await risk_mod.scan_inventory_views([]) == {
            "changed": 0, "warn_count": 0, "normal_count": 0,
        }


class TestSyncFlagsToBitableReal:
    """零改动复用验证：真 sync_record_flags_to_bitable 吃视图，
    写请求 fields 键集合 == {风险标记, 风险说明}，且写前逐条 _set_sync_ignore。"""

    @pytest.fixture(autouse=True)
    def _fake_transport(self, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
        posted: list[dict[str, Any]] = []

        class _FakeResponse:
            def __init__(self, n: int) -> None:
                self._n = n

            def json(self) -> dict[str, Any]:
                return {"code": 0, "data": {"records": [{}] * self._n}}

        class _FakeHttp:
            def __init__(self, **_kw: Any) -> None:
                pass

            async def __aenter__(self) -> _FakeHttp:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def post(self, url: str, *, headers: Any = None,
                           json: Any = None, params: Any = None) -> _FakeResponse:
                posted.append({"url": url, "json": json})
                return _FakeResponse(len(json["records"]))

        monkeypatch.setattr("httpx.AsyncClient", _FakeHttp)
        ignored: list[str] = []
        monkeypatch.setattr(
            handler_mod, "_set_sync_ignore", _record_ignore(ignored)
        )
        monkeypatch.setattr(handler_mod, "SafetyBitableClient", _FakeClient)
        self.posted = posted
        self.ignored = ignored
        return posted

    async def test_write_request_only_risk_columns(self) -> None:
        views = [
            _view("recA", flag="normal", note=["normal"]),      # → 预警差异在 scan 造，
            _view("recB", flag="warn", note=["over_limit"]),
        ]
        views[0].risk_flag = "warn"
        views[0].risk_note = ["over_limit"]
        written = await handler_mod.sync_record_flags_to_bitable(views)
        assert written == 2
        assert len(self.posted) == 1
        payload = self.posted[0]["json"]["records"]
        assert [r["record_id"] for r in payload] == ["recA", "recB"]
        for r in payload:
            assert set(r["fields"]) == WRITEBACK_FIELD_NAMES
            assert r["fields"]["风险标记"] == "预警"
            assert r["fields"]["风险说明"] == ["超量"]
        assert self.ignored == ["recA", "recB"]  # 防环先于写


class _FakeClient:
    def __init__(self, *, app_token: str = "appX", table_id: str = "tblX") -> None:
        self.app_token = app_token
        self.table_id = table_id

    async def _token(self) -> str:
        return "tok"


def _record_ignore(into: list[str]) -> Any:
    async def _set(record_id: str, ttl: int = 60) -> None:
        into.append(record_id)

    return _set
