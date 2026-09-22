"""直读编排双路径单测（chemical_inventory-direct Ticket 04）。

覆盖：daily 编排分支选择（DIRECT 开=直读收尾、关=不触直读）、直读收尾
（不回拉镜像/重算/回写/再读重试/快照注入/分析）、weekly 直读注入、
take_snapshot records 注入两态（假 session，零 DB）。
夹具口径：quantity = total*1000 kg（系统换算 == 填报吨数，避开 R07 单位异常）。
推送零触达：本套件不配置群聊、不开启 digest（safety-digest 铁律）。
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

import app.modules.safety.chemical_inventory.daily_job as daily_job
import app.modules.safety.chemical_inventory.weekly_report as weekly_mod
import app.modules.safety.feishu.chemical_inventory_bitable_handler as handler_mod
from app.modules.safety.chemical_inventory.snapshots import (
    take_snapshot,
)
from app.modules.safety.models import ChemicalInventorySnapshot
from app.modules.safety.service.chemical_inventory_direct import config
from app.modules.safety.service.chemical_inventory_direct.views import (
    InventoryView,
    view_from_record_id,
)


def _view(vid: str, *, total: str = "0.5", limit: str = "10",
          flag: str = "normal", note: list[str] | None = None) -> InventoryView:
    """total > limit 时命中 R01 超量；quantity 与 total 换算一致（不触 R07）。"""
    qty = Decimal(total) * 1000  # kg → T 与填报一致
    if note is None:
        note = ["normal"]
    return InventoryView(
        id=vid, feishu_record_id=vid,
        department="warehouse", storage_location="危库1", material_name=f"物料-{vid}",
        quantity=qty, unit="kg",
        total_quantity_t=Decimal(total), max_limit=Decimal(limit),
        max_limit_unit="T", hazard_classes=["flammable"], category="溶剂",
        risk_flag=flag, risk_note=note,
    )


class FakeReader:
    """InventoryRecordsReader 替身：可编排「第 n 次调用抛错」。"""

    def __init__(self, views: list[InventoryView],
                 fail_on_call: set[int] | None = None) -> None:
        self._views = views
        self._fail_on_call = fail_on_call or set()
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[InventoryView]:
        self.calls += 1
        if self.calls in self._fail_on_call:
            raise RuntimeError("bitable read boom")
        return list(self._views)


def _seed_direct(monkeypatch: pytest.MonkeyPatch, reader: FakeReader) -> list[Any]:
    """替身化直读包 open_reader + 回写哨兵；返回回写调用记录。"""
    from app.modules.safety.service.chemical_inventory_direct import (
        reader as reader_mod,
    )

    calls: list[list[InventoryView]] = []

    async def _spy(records: list[InventoryView]) -> int:
        calls.append(records)
        return len(records)

    async def _no_sync() -> dict[str, Any]:
        raise AssertionError("直读模式不该回拉镜像")

    monkeypatch.setattr(config, "direct_enabled", lambda: True)
    monkeypatch.setattr(config, "writeback_risk_enabled", lambda: True)
    monkeypatch.setattr(reader_mod, "open_reader", lambda **kw: reader)
    monkeypatch.setattr(handler_mod, "sync_record_flags_to_bitable", _spy)
    monkeypatch.setattr(daily_job, "sync_inventory_records_from_bitable", _no_sync)
    return calls


def _seed_files(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_files(*_a: Any) -> list[dict[str, str]]:
        return [{"message_id": "m1", "file_key": "k", "file_name": "a.xls"}]

    async def _fake_download(*_a: Any) -> bytes:
        return b"xls"

    async def _fake_apply(*_a: Any, **_kw: Any) -> dict[str, Any]:
        return {"parsed": 1, "updated": 1, "created": 0}

    monkeypatch.setattr(daily_job, "_inventory_app_token", lambda: "appX")
    monkeypatch.setattr(daily_job, "fetch_daily_files", _fake_files)
    monkeypatch.setattr(daily_job, "_download_message_file", _fake_download)
    monkeypatch.setattr(daily_job, "apply_daily_workbook", _fake_apply)


class _EmptyResult:
    def all(self) -> list[Any]:
        return []


class FakeSession:
    """take_snapshot 所需的最小 session 替身（scalars 恒返空；支持 async with）。"""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = False
        self.scalars_calls = 0

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def scalars(self, _stmt: Any) -> _EmptyResult:
        self.scalars_calls += 1
        return _EmptyResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


class FakeSessionFactory:
    def __call__(self) -> FakeSession:
        return FakeSession()


async def _fake_prev(_db: Any, _today: date) -> list[Any]:
    return []


async def _noop_take(_db: Any, _d: date, *,
                     kind: str = "weekly",
                     records: list[Any] | None = None) -> int:
    return 0


class TestDailyOrchestration:
    async def test_direct_branch_full_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DIRECT 开：写完不回拉镜像；重算→回写→再读→分析→快照注入。"""
        views = [
            # 已预警且仍超量：计算无差异
            _view("recOver", total="12", flag="warn", note=["over_limit"]),
            # 现态 normal 但超量：计算后翻预警 → changed
            _view("recFlip", total="12"),
        ]
        reader = FakeReader(views)
        wb_calls = _seed_direct(monkeypatch, reader)
        _seed_files(monkeypatch)

        snap_calls: list[tuple[date, str, list[Any] | None]] = []
        real_take = getattr(daily_job, "take_snapshot")

        async def _spy_take(db: Any, d: date, kind: str,
                            records: list[Any] | None = None) -> int:
            snap_calls.append((d, kind, records))
            n: int = await real_take(db, d, kind, records=records)
            return n

        monkeypatch.setattr(daily_job, "async_session_factory", FakeSessionFactory())
        monkeypatch.setattr(daily_job, "load_prev_daily_snapshot", _fake_prev)
        monkeypatch.setattr(daily_job, "take_snapshot", _spy_take)

        result = await daily_job.run_scheduled_daily_update()

        assert result["sync"] == {"skipped": True, "reason": "direct_mode"}
        assert result["scan"]["changed"] == 1
        assert reader.calls == 2  # 初读 + 写后再读
        assert len(wb_calls) == 1
        assert [v.id for v in wb_calls[0]] == ["recFlip"]
        # 快照注入的是「写后再读」的视图（重算回写后的值）
        assert len(snap_calls) == 1
        _, kind, records = snap_calls[0]
        assert kind == "daily"
        assert records is not None and [v.id for v in records] == ["recOver", "recFlip"]
        assert result["analysis"].over_limit_count == 2
        assert {w.id for w in result["warnings"]} == {"recOver", "recFlip"}

    async def test_direct_reread_retries_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """再读失败重试 1 次：第一次抛、第二次成功 → 不上抛。"""
        views = [_view("recA", total="12", flag="warn", note=["over_limit"])]
        reader = FakeReader(views, fail_on_call={2})
        _seed_direct(monkeypatch, reader)
        _seed_files(monkeypatch)
        monkeypatch.setattr(daily_job, "async_session_factory", FakeSessionFactory())
        monkeypatch.setattr(daily_job, "load_prev_daily_snapshot", _fake_prev)
        monkeypatch.setattr(daily_job, "take_snapshot", _noop_take)

        result = await daily_job.run_scheduled_daily_update()
        assert reader.calls == 3  # 初读(1) + 再读失败(2) + 重试成功(3)
        assert result["scan"]["changed"] == 0

    async def test_writeback_off_skips_reread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """WRITEBACK 关（灰度组合）：不重读，分析/快照用内存重算值（spec §4.4）。"""
        views = [_view("recFlip", total="12")]  # normal → 计算翻 warn
        reader = FakeReader(views)
        _seed_direct(monkeypatch, reader)
        monkeypatch.setattr(config, "writeback_risk_enabled", lambda: False)
        _seed_files(monkeypatch)

        snap_records: list[Any] = []

        async def _spy_take(_db: Any, _d: date, *,
                            kind: str = "weekly",
                            records: list[Any] | None = None) -> int:
            snap_records.append(records)
            return 0

        monkeypatch.setattr(daily_job, "async_session_factory", FakeSessionFactory())
        monkeypatch.setattr(daily_job, "load_prev_daily_snapshot", _fake_prev)
        monkeypatch.setattr(daily_job, "take_snapshot", _spy_take)

        result = await daily_job.run_scheduled_daily_update()
        assert reader.calls == 1  # 回写关 → 不重读
        assert result["scan"]["changed"] == 1
        # 快照拍的是内存重算后的值（视图被原地重算）
        assert snap_records[0] is not None and snap_records[0][0].risk_flag == "warn"
        assert {w.id for w in result["warnings"]} == {"recFlip"}

    async def test_direct_off_never_enters_direct(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """全关（默认）：无文件时提前跳过，不触直读收尾（哨兵上抛即暴露误用）。"""
        async def _no_direct(_files: list[dict[str, Any]]) -> dict[str, Any]:
            raise AssertionError("DIRECT 关时不该进直读收尾")

        monkeypatch.setattr(daily_job, "_finish_direct", _no_direct)

        async def _no_files(*_a: Any) -> list[dict[str, str]]:
            return []

        monkeypatch.setattr(daily_job, "_inventory_app_token", lambda: "appX")
        monkeypatch.setattr(daily_job, "fetch_daily_files", _no_files)
        result = await daily_job.run_scheduled_daily_update()
        assert result.get("skipped") is True


class TestWeeklyOrchestration:
    async def test_direct_injects_current_rows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.database as db_mod

        views = [_view("recW")]
        reader = FakeReader(views)
        _seed_direct(monkeypatch, reader)

        captured: dict[str, Any] = {}

        async def _spy_build(db: Any, d: date, *,
                             current_rows: list[Any] | None = None) -> dict[str, Any]:
            captured["current_rows"] = current_rows
            return {"snapshot_date": d.isoformat(), "first": True}

        async def _no_ai(_report: dict[str, Any]) -> str:
            return ""

        monkeypatch.setattr(weekly_mod, "build_weekly_report", _spy_build)
        monkeypatch.setattr(weekly_mod, "generate_ai_summary", _no_ai)
        # weekly_report 在函数内局部导入 async_session_factory → patch 源模块
        monkeypatch.setattr(db_mod, "async_session_factory", FakeSessionFactory())

        report = await weekly_mod.run_weekly_job(chat_id=None)
        assert report["first"] is True
        assert captured["current_rows"] == views

    async def test_legacy_passes_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.core.database as db_mod

        async def _boom() -> Any:
            raise AssertionError("legacy 不该触直读")

        from app.modules.safety.service.chemical_inventory_direct import reader as rm

        monkeypatch.setattr(config, "direct_enabled", lambda: False)
        monkeypatch.setattr(rm, "open_reader", lambda **kw: _boom())

        captured: dict[str, Any] = {}

        async def _spy_build(db: Any, d: date, *,
                             current_rows: list[Any] | None = None) -> dict[str, Any]:
            captured["current_rows"] = current_rows
            return {"snapshot_date": d.isoformat(), "first": True}

        async def _no_ai(_report: dict[str, Any]) -> str:
            return ""

        monkeypatch.setattr(weekly_mod, "build_weekly_report", _spy_build)
        monkeypatch.setattr(weekly_mod, "generate_ai_summary", _no_ai)
        monkeypatch.setattr(db_mod, "async_session_factory", FakeSessionFactory())

        await weekly_mod.run_weekly_job(chat_id=None)
        assert captured["current_rows"] is None


class TestTakeSnapshotInjection:
    async def test_records_injected_skips_orm_row_query(self) -> None:
        db = FakeSession()
        views = [_view("rec1"), _view("rec2")]
        n = await take_snapshot(db, date(2026, 9, 22), kind="daily", records=views)  # type: ignore[arg-type]
        assert n == 2
        assert len(db.added) == 2
        row = db.added[0]
        assert isinstance(row, ChemicalInventorySnapshot)
        assert row.department == "warehouse"
        assert row.material_name == "物料-rec1"
        assert row.total_quantity_t == Decimal("0.5")
        assert row.risk_flag == "normal"

    async def test_records_none_queries_orm(self) -> None:
        db = FakeSession()
        n = await take_snapshot(db, date(2026, 9, 22), kind="weekly", records=None)  # type: ignore[arg-type]
        assert n == 0
        assert db.scalars_calls == 2  # 行查询 + 旧快照软删查询（legacy 行为保持）

    async def test_view_and_orm_copy_equivalence(self) -> None:
        """同一份夹具：视图注入与 ORM-like 行产出同字段快照。"""
        view = _view("recE")
        fields = dict(
            department=view.department, storage_location=view.storage_location,
            material_name=view.material_name, quantity=view.quantity,
            unit=view.unit, total_quantity_t=view.total_quantity_t,
            risk_flag=view.risk_flag,
        )
        db_a = FakeSession()
        await take_snapshot(db_a, date(2026, 9, 22), kind="daily", records=[view])  # type: ignore[arg-type]
        db_b = FakeSession()
        await take_snapshot(db_b, date(2026, 9, 22), kind="daily",  # type: ignore[arg-type]
                            records=[type("R", (), fields)()])
        for a, b in zip(db_a.added, db_b.added):
            for col in ("department", "storage_location", "material_name",
                        "quantity", "unit", "total_quantity_t", "risk_flag"):
                assert getattr(a, col) == getattr(b, col)


class TestViewFromRecordIdFreshness:
    def test_bitable_row_to_view(self) -> None:
        """原始行 → 视图（含 updated_at 新鲜度信号）——编排读回链路冒烟。"""
        view = view_from_record_id("recX", {
            "部门": "仓储部",
            "物料名称": [{"text": "乙醇", "type": "text"}],
            "最后更新时间": 1789903843000,
            "风险标记": "预警",
        })
        assert view.updated_at is not None
        assert view.last_updated_at == view.updated_at
        assert view.risk_flag == "warn"
