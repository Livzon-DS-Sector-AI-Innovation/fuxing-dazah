"""sheet 源日报编排单测（chemical-inventory-sheet-source P1-T3）。

覆盖：sheet 模式跳过拉群 Excel/写 Bitable、revision 未更新标注、行数骤降
红标、D8 跨源首日跳环比、快照 source='sheet' 注入、文案（日报/速递/补录拒绝）、
writeback 强制关。替身口径同 test_orchestration（FakeSession/FakeReader，零 DB 零飞书）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

import app.modules.safety.chemical_inventory.daily_job as daily_job
from app.modules.safety.app_config.store import store as _app_config_store
from app.modules.safety.service.chemical_inventory_direct import config

TODAY = date(2026, 10, 15)


def _bj_today() -> date:
    """北京时间今天（编排内 take_snapshot/revision 状态用真实当日，勿冻结）。"""
    return (datetime.now(UTC) + timedelta(hours=8)).date()


class _EmptyResult:
    def all(self) -> list[Any]:
        return []


class FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def scalars(self, _stmt: Any) -> _EmptyResult:
        return _EmptyResult()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


class FakeSessionFactory:
    def __call__(self) -> FakeSession:
        return FakeSession()


class FakeSheetReader:
    """带 last_revision 的 reader 替身（协议口径 + D6 revision 暴露）。"""

    def __init__(self, views: list[Any], revision: int = 364) -> None:
        self._views = views
        self.last_revision = revision
        self.calls = 0

    async def fetch_all(self, *, strict: bool = False) -> list[Any]:
        self.calls += 1
        return list(self._views)


def _view(vid: str, *, total: str = "0.5", limit: str = "10") -> SimpleNamespace:
    return SimpleNamespace(
        id=vid, feishu_record_id=vid,
        department="aimo", storage_location="车间二提取岗位",
        material_name=f"物料-{vid}",
        quantity=Decimal(total) * 1000, unit="kg",
        total_quantity_t=Decimal(total), max_limit=Decimal(limit),
        max_limit_unit="T", hazard_classes=["flammable"],
        risk_flag="normal", risk_note=["normal"],
        updated_at=datetime.now(UTC),
    )


class _PrevRow(SimpleNamespace):
    """load_prev_daily_snapshot_with_source 替身返回的行（带 source）。"""


def _seed_sheet(
    monkeypatch: pytest.MonkeyPatch,
    reader: FakeSheetReader,
    *,
    prev_rows: list[Any] | None = None,
    prev_source: str | None = None,
) -> dict[str, Any]:
    """替身化 sheet 编排全部 IO；返回捕获器。"""
    from app.modules.safety.service.chemical_inventory_direct import (
        reader as reader_mod,
    )

    captured: dict[str, Any] = {"snapshots": [], "set_values": []}

    # P2 退役：Excel 拉群/镜像回拉函数已整体删码（结构性保证，无需哨兵）

    async def _fake_prev_with_source(_db: Any, _today: date) -> tuple[list[Any], str | None]:
        return prev_rows or [], prev_source

    async def _spy_take(
        _db: Any, _d: date, *, kind: str = "weekly",
        records: list[Any] | None = None, source: str | None = None,
    ) -> int:
        captured["snapshots"].append({"kind": kind, "records": records, "source": source})
        return len(records or [])

    async def _spy_set_value(
        _db: Any, key: str, value: str, **_kw: Any
    ) -> dict[str, Any]:
        captured["set_values"].append((key, value))
        return {}

    monkeypatch.setattr(
        daily_job, "load_prev_daily_snapshot_with_source", _fake_prev_with_source
    )
    monkeypatch.setattr(daily_job, "take_snapshot", _spy_take)
    monkeypatch.setattr(daily_job, "async_session_factory", FakeSessionFactory())
    monkeypatch.setattr(reader_mod, "open_reader", lambda **kw: reader)
    monkeypatch.setattr(_app_config_store, "set_value", _spy_set_value)
    monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
    monkeypatch.delenv("SAFETY_CHEMICAL_INVENTORY_SHEET_REVISION", raising=False)
    return captured


class TestSheetModeOrchestration:
    async def test_skips_excel_and_bitable_writes(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """sheet 模式：不拉群文件/不回拉镜像/不回写；快照 source='sheet'。"""
        reader = FakeSheetReader([_view("r1"), _view("r2")])
        captured = _seed_sheet(monkeypatch, reader)

        result = await daily_job.run_scheduled_daily_update()

        assert result["source"] == "sheet"
        assert result["sync"] == {"skipped": True, "reason": "sheet_source"}
        assert result["files"] == []
        assert reader.calls == 1
        assert len(captured["snapshots"]) == 1
        snap = captured["snapshots"][0]
        assert snap["kind"] == "daily"
        assert snap["source"] == "sheet"
        assert [v.id for v in snap["records"]] == ["r1", "r2"]

    async def test_revision_unchanged_marks_not_updated(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """revision 与已记录一致：日报标注 + 视图 updated_at 置 None。"""
        views = [_view("r1")]
        reader = FakeSheetReader(views, revision=364)
        _seed_sheet(monkeypatch, reader)
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SHEET_REVISION", "364|2026-10-14")

        result = await daily_job.run_scheduled_daily_update()

        assert result["not_updated_note"] == "数据自 2026-10-14 未更新（表格 revision 无变化）"
        assert all(v.updated_at is None for v in views)

    async def test_revision_changed_persists_state(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """revision 变化：状态落库（{revision}|{今日}），无未更新标注。"""
        views = [_view("r1")]
        reader = FakeSheetReader(views, revision=365)
        captured = _seed_sheet(monkeypatch, reader)
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SHEET_REVISION", "364|2026-10-14")

        result = await daily_job.run_scheduled_daily_update()

        assert result["not_updated_note"] is None
        assert captured["set_values"] == [
            ("SAFETY_CHEMICAL_INVENTORY_SHEET_REVISION", f"365|{_bj_today().isoformat()}")
        ]
        assert all(v.updated_at is not None for v in views)

    async def test_first_run_records_state_without_note(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reader = FakeSheetReader([_view("r1")], revision=364)
        captured = _seed_sheet(monkeypatch, reader)

        result = await daily_job.run_scheduled_daily_update()

        assert result["not_updated_note"] is None
        assert captured["set_values"]

    async def test_row_drop_alert(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同源昨日快照行数 100 → 今日 40（骤降 >50%）：红标告警。"""
        prev = [_PrevRow(material_name=f"p{i}", total_quantity_t=Decimal("1"),
                         source="sheet") for i in range(100)]
        reader = FakeSheetReader([_view(f"r{i}") for i in range(40)])
        _seed_sheet(monkeypatch, reader, prev_rows=prev, prev_source="sheet")

        result = await daily_job.run_scheduled_daily_update()

        assert len(result["sheet_alerts"]) == 1
        assert "行数骤降" in result["sheet_alerts"][0]

    async def test_moderate_decline_no_alert(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """降 40%（未过 50% 线）：不告警。"""
        prev = [_PrevRow(material_name=f"p{i}", total_quantity_t=Decimal("1"),
                         source="sheet") for i in range(100)]
        reader = FakeSheetReader([_view(f"r{i}") for i in range(60)])
        _seed_sheet(monkeypatch, reader, prev_rows=prev, prev_source="sheet")

        result = await daily_job.run_scheduled_daily_update()

        assert result["sheet_alerts"] == []

    async def test_cross_source_day_skips_compare(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """D8：昨日快照 source=None（legacy/总表口径）→ 跳环比 + 明示，无骤降误报。"""
        prev = [_PrevRow(material_name=f"p{i}", total_quantity_t=Decimal("99"),
                         source=None) for i in range(300)]
        reader = FakeSheetReader([_view(f"r{i}") for i in range(10)])
        _seed_sheet(monkeypatch, reader, prev_rows=prev, prev_source=None)

        result = await daily_job.run_scheduled_daily_update()

        assert result["compare_note"] == "数据源口径切换，本日不做环比"
        assert result["sheet_alerts"] == []  # 300→10 也不告警（口径不可比）
        assert result["analysis"].surge == [] and result["analysis"].decline == []
        assert result["analysis"].has_prev is False
        # D8 断点日汇总表必须照常渲染实际库存（compare_skipped ≠ 首日无数据）
        assert result["analysis"].compare_skipped is True
        assert result["analysis"].summary, "断点日汇总表不能为空（今日实际数据）"
        content = daily_job.build_daily_summary(result)
        assert "危化品 ｜ 今日库存 ｜ 较昨日变化" in content
        assert "昨日无快照数据" not in content
        assert any(v.material_name in content for v in result["analysis"].summary)

    async def test_same_source_day_compares(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """同源（sheet）昨日快照：环比照常（surge/decline 计算生效）。"""
        prev = [_PrevRow(material_name="物料-r1", total_quantity_t=Decimal("1"),
                         source="sheet")]
        reader = FakeSheetReader([_view("r1", total="5")])  # 1T → 5T：+4T ≥1T 且 ≥30%
        _seed_sheet(monkeypatch, reader, prev_rows=prev, prev_source="sheet")

        result = await daily_job.run_scheduled_daily_update()

        assert result["compare_note"] is None
        assert result["analysis"].surge_count == 1

    async def test_empty_views_returns_skipped(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        reader = FakeSheetReader([])
        _seed_sheet(monkeypatch, reader)

        result = await daily_job.run_scheduled_daily_update()

        assert result == {"source": "sheet", "skipped": True,
                          "reason": "sheet_empty", "files": []}


class TestSheetModeWording:
    def test_summary_skipped_sheet_wording(self) -> None:
        content = daily_job.build_daily_summary(
            {"skipped": True, "source": "sheet", "reason": "sheet_empty"}
        )
        assert "读取异常或无数据" in content
        assert "Excel" not in content

    def test_summary_prepends_notes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        analysis = SimpleNamespace(report_date=TODAY)
        monkeypatch.setattr(daily_job, "render_daily_report", lambda _a: "BODY: 危化品库存每日分析日报")
        result = {
            "analysis": analysis,
            "not_updated_note": "数据自 2026-10-14 未更新（表格 revision 无变化）",
            "compare_note": "数据源口径切换，本日不做环比",
            "sheet_alerts": ["行数骤降：今日 40 行 vs 昨日 100 行，请核实《危险品日报表》是否被误清空"],
        }
        content = daily_job.build_daily_summary(result)
        assert content.index("⚠️ 数据自 2026-10-14") < content.index("🚨 行数骤降")
        assert content.index("🚨 行数骤降") < content.index("BODY: 危化品库存每日分析日报")

    def test_receipt_message_branches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", raising=False)
        assert "Excel 日报" in config.receipt_direct_disabled_message()
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        assert "《危险品日报表》" in config.receipt_direct_disabled_message()

class TestWeeklySourceSwitch:
    async def test_weekly_cross_source_skips_compare(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """weekly D8：上一份周快照源不一致 → first+source_switch（不整周误报）。"""
        from app.modules.safety.chemical_inventory import weekly_report as wr

        class _Rows(list):
            def all(self) -> list[Any]:
                return list(self)

        class _Scalar:
            def __init__(self, value: Any) -> None:
                self._value = value

            async def all(self) -> list[Any]:
                return [self._value] if self._value is not None else []

        class _Db:
            def __init__(self) -> None:
                self.calls = 0

            async def scalar(self, stmt: Any) -> Any:
                return date(2026, 10, 9)  # prev_snapshot_date：上一份周快照日期

            async def scalars(self, stmt: Any) -> Any:
                self.calls += 1
                text = str(stmt)
                if "is_deleted" in text and "snapshot_date" in text:
                    # 上一份快照行（source=None）→ 触发 D8 断点
                    return _Rows([
                        _PrevRow(material_name="x", total_quantity_t=Decimal("1"),
                                 source=None),
                    ])
                return _Rows([])  # 镜像行/软删旧行查询

            def add(self, obj: Any) -> None:
                return None

            async def flush(self) -> None:
                return None

        db = _Db()
        views = [_view("r1")]
        report = await wr.build_weekly_report(db, TODAY, current_rows=views, source="sheet")
        assert report["first"] is True
        assert report["source_switch"] is True
        text = wr._format_report(report, "")
        assert "数据源口径切换" in text


class TestSnapshotDuplicateKeyMerge:
    """sheet 源同键多行（多储罐）→ 快照合并（uq_cisnap_key 粒度）。"""

    async def test_same_key_rows_merged_with_summed_totals(self) -> None:
        from types import SimpleNamespace

        from app.modules.safety.chemical_inventory.snapshots import take_snapshot

        class _S:
            def __init__(self) -> None:
                self.added: list[Any] = []

            async def scalars(self, _stmt: Any) -> Any:
                class _R:
                    def all(self) -> list[Any]:
                        return []

                return _R()

            def add(self, obj: Any) -> None:
                self.added.append(obj)

            async def flush(self) -> None:
                return None

        def _row(total: str, flag: str = "normal") -> Any:
            return SimpleNamespace(
                department="aimo", storage_location="车间二层析岗位",
                material_name="乙酸乙酯正庚烷",
                quantity=Decimal(total) * 1000, unit="kg",
                total_quantity_t=Decimal(total), risk_flag=flag,
            )

        db = _S()
        n = await take_snapshot(
            db, TODAY, kind="daily",
            records=[_row("5"), _row("5"), _row("5", flag="warn"), _row("2")],
            source="sheet",
        )
        assert n == 1  # 同键 4 行合并为 1 行
        assert len(db.added) == 1
        snap = db.added[0]
        assert snap.total_quantity_t == Decimal("17")
        assert snap.quantity == Decimal("17000")
        assert snap.risk_flag == "warn"  # 保守取 warn
        assert snap.source == "sheet"


class TestNightlySnapshot:
    """23:00 日终快照（kind=nightly 纯存档）：源开关两态。"""

    def _seed(
        self, monkeypatch: pytest.MonkeyPatch, reader: Any,
    ) -> dict[str, Any]:
        from app.modules.safety.service.chemical_inventory_direct import (
            reader as reader_mod,
        )

        captured: dict[str, Any] = {"snapshots": []}

        async def _spy_take(
            _db: Any, _d: date, *, kind: str = "weekly",
            records: list[Any] | None = None, source: str | None = None,
        ) -> int:
            captured["snapshots"].append(
                {"kind": kind, "records": records, "source": source}
            )
            return len(records or [])

        monkeypatch.setattr(daily_job, "take_snapshot", _spy_take)
        monkeypatch.setattr(daily_job, "async_session_factory", FakeSessionFactory())
        monkeypatch.setattr(reader_mod, "open_reader", lambda **kw: reader)
        return captured

    async def test_sheet_mode_nightly_snapshot(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """sheet 模式：直读视图注入 + kind=nightly + source='sheet' + 风险重算。"""
        monkeypatch.setenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", "sheet")
        views = [_view("r1"), _view("r2")]
        captured = self._seed(monkeypatch, FakeSheetReader(views))

        result = await daily_job.run_nightly_snapshot()

        assert result["kind"] == "nightly"
        assert result["source"] == "sheet"
        assert result["records"] == 2
        snap = captured["snapshots"][0]
        assert snap["kind"] == "nightly"
        assert snap["source"] == "sheet"
        assert [v.id for v in snap["records"]] == ["r1", "r2"]
        assert result["scan"]["changed"] >= 0  # 内存重算已执行

    async def test_legacy_mode_snapshots_from_orm_mirror(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """legacy 模式（开关全关）：records=None 快照自取 ORM 镜像，source=bitable。"""
        monkeypatch.delenv("SAFETY_CHEMICAL_INVENTORY_SOURCE", raising=False)
        monkeypatch.delenv("SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED", raising=False)
        from app.modules.safety.service.chemical_inventory_direct import (
            reader as reader_mod,
        )

        async def _boom(**_kw: Any) -> Any:
            raise AssertionError("legacy 模式不该触直读")

        monkeypatch.setattr(reader_mod, "open_reader", _boom)
        captured = self._seed(monkeypatch, None)

        result = await daily_job.run_nightly_snapshot()

        assert result["source"] == "bitable"
        assert "scan" not in result
        snap = captured["snapshots"][0]
        assert snap["kind"] == "nightly"
        assert snap["records"] is None   # take_snapshot 内部查 ORM 镜像
        assert snap["source"] is None
