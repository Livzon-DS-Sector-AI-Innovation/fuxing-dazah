"""T5 库存分析定档测试：组装/幂等/端点（fixture 不触网）。"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

CN_TZ = ZoneInfo("Asia/Shanghai")


def _stock(code: str, qty: float, *, expiry: date | None = None,
           status: str = "normal", category_cn: str = "原辅料") -> Any:
    from app.modules.warehouse.direct.views import StockView

    return StockView(
        record_id=f"s{code}{expiry}", code=code, name=f"物料{code}",
        batch_no=f"{code}-B", quantity=qty, unit="Kg", expiry_date=expiry,
        status=status, qc_sample_status=None, qc_report_status=None,
        qc_release_status=None, category_cn=category_cn,
    )


def _mv(direction: str, code: str, qty: float, days_ago: int) -> Any:
    from app.modules.warehouse.direct.views import MovementView

    return MovementView(
        record_id=f"m{direction}{code}{days_ago}", direction=direction,
        source_type="purchase" if direction == "inbound" else "production",
        code=code, name=f"物料{code}", batch_no=f"{code}-B", quantity=qty,
        unit="Kg", occurred_at=datetime.now(UTC) - timedelta(days=days_ago),
        category_cn="原辅料",
    )


@pytest.fixture
def direct_views(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.warehouse.direct import reader, service
    from app.modules.warehouse.direct.views import MaterialView

    async def _stocks(adapter: Any = None) -> list[Any]:
        soon = datetime.now(CN_TZ).date() + timedelta(days=30)
        return [
            _stock("A", 10, expiry=soon, status="normal"),
            _stock("B", 0, status="quarantine"),
            _stock("F", 5, status="frozen", category_cn="包材"),
        ]

    async def _movements(adapter: Any = None) -> list[Any]:
        return [
            _mv("inbound", "A", 10, days_ago=100),   # A 呆滞（有量+久未入）
            _mv("outbound", "A", 4, days_ago=1),
        ]

    async def _materials(adapter: Any = None) -> list[Any]:
        return [MaterialView(record_id="mstA", code="A", name="物料A",
                             category_cn="原辅料")]

    monkeypatch.setattr(reader, "fetch_stocks", _stocks)
    monkeypatch.setattr(reader, "fetch_movements", _movements)
    monkeypatch.setattr(reader, "fetch_materials", _materials)
    for cache in (service.stock_cache, service.movement_cache, service.material_cache):
        cache.invalidate()


class TestBuildSummary:
    async def test_summary_structure(self, direct_views: None) -> None:
        from app.modules.warehouse.analysis import build_analysis_summary

        summary = await build_analysis_summary()
        kpi = summary["kpi"]
        assert kpi["stock_rows"] == 3
        assert kpi["stock_skus"] == 3
        assert kpi["material_count"] == 1
        assert kpi["zero_stock_count"] == 1      # B
        assert kpi["frozen_count"] == 1          # F
        assert kpi["quarantine_count"] == 1      # B
        assert summary["distribution"][0]["category"] == "raw"
        assert summary["top"]["consumption"][0]["material_code"] == "A"
        alerts = summary["alerts"]
        assert alerts["idle_count"] == 1         # A 100 天未入库
        assert alerts["idle"][0]["material_code"] == "A"
        assert alerts["expiry_count"] == 1       # A 30 天后到期 ≤90
        assert alerts["expiry"][0]["days_left"] == 30
        assert alerts["low_stock_count"] == 0


class TestUpsertIdempotent:
    async def test_same_day_overwrites(self, db_session: Any, direct_views: None) -> None:
        from sqlalchemy import select

        from app.modules.warehouse.analysis import run_inventory_analysis
        from app.modules.warehouse.models import WarehouseAnalysisReport

        row1 = await run_inventory_analysis(db_session, trigger="scheduled")
        row2 = await run_inventory_analysis(db_session, trigger="manual")
        # 测试连共享开发库（仅写回滚），在跑服务的 00:30 定档任务会留下其他日期的
        # 已提交行——幂等断言只看当日，免疫跨日行污染。
        today = datetime.now(CN_TZ).date()
        rows = (
            await db_session.execute(
                select(WarehouseAnalysisReport).where(
                    WarehouseAnalysisReport.report_date == today,
                    WarehouseAnalysisReport.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].trigger == "manual"
        assert row2.id == row1.id


class TestAnalysisAPI:
    async def test_run_latest_list(
        self, api_context: Any, db_session: Any, direct_views: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        client, db = api_context

        async def _perms(uid: str, dbo: object) -> set[str]:
            return {"warehouse:intelligence:read", "warehouse:intelligence:update"}

        monkeypatch.setattr(
            "app.platform.permission.deps.get_user_permissions", _perms
        )
        r = await client.post("/api/v1/warehouse/analysis/run")
        assert r.status_code == 201
        data = r.json()["data"]
        assert data["trigger"] == "manual"
        assert data["summary"]["kpi"]["stock_rows"] == 3

        r2 = await client.get("/api/v1/warehouse/analysis/latest")
        assert r2.status_code == 200
        assert r2.json()["data"]["report_date"] == data["report_date"]

        r3 = await client.get("/api/v1/warehouse/analysis/reports")
        assert r3.status_code == 200
        assert r3.json()["meta"]["total"] >= 1
