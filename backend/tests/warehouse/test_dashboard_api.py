"""驾驶舱聚合端点路由层测试（Ticket 05）。

鉴权覆写：require_user 返回构造用户、get_user_permissions 返回只读权限集。
数据清理：所有造数以 DASH-T 前缀标记，测试结束统一删除（client 会话提交后
db_session 的 rollback 无法回收，必须显式清理防污染）。
"""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
    WarehouseStockDailySnapshot,
    WarehouseStocktake,
)
from app.platform.permission.deps import require_user

CN_TZ = ZoneInfo("Asia/Shanghai")
PERM = {"warehouse:stock:read"}


@pytest.fixture
async def dashboard_client(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncClient]:
    """在 client（get_db 覆写）基础上叠加免登录 + 固定权限集。"""
    from app.platform.permission import deps as permission_deps

    async def _fake_user() -> object:
        return object.__new__(type("FakeUser", (), {"id": uuid.uuid4()}))

    async def _fake_perms(user_id: str, db: AsyncSession) -> set[str]:
        return PERM

    app.dependency_overrides[require_user] = _fake_user
    monkeypatch.setattr(permission_deps, "get_user_permissions", _fake_perms)
    yield client
    app.dependency_overrides.pop(require_user, None)


async def _seed(db: AsyncSession) -> None:  # noqa: C901
    today = datetime.now(CN_TZ)
    now_aware = today.astimezone(CN_TZ)

    m_low = WarehouseMaterial(
        code="DASH-T-M-LOW", name="驾驶舱低库存物料", category="raw",
        unit="kg", safety_stock=Decimal("100"),
    )
    m_ok = WarehouseMaterial(
        code="DASH-T-M-OK", name="驾驶舱正常物料", category="packaging",
        unit="个", safety_stock=Decimal("10"),
    )
    m_idle = WarehouseMaterial(
        code="DASH-T-M-IDLE", name="驾驶舱呆滞物料", category="raw",
        unit="kg", safety_stock=Decimal("0"),
    )
    db.add_all([m_low, m_ok, m_idle])
    await db.flush()

    loc = WarehouseLocation(code="DASH-T-LOC", name="驾驶舱库位", location_type="normal")
    db.add(loc)
    await db.flush()

    db.add_all(
        [
            WarehouseStock(
                material_id=m_low.id, material_code=m_low.code, material_name=m_low.name,
                batch_no="B1", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("30"),
            ),
            WarehouseStock(
                material_id=m_ok.id, material_code=m_ok.code, material_name=m_ok.name,
                batch_no="", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("500"),
            ),
            WarehouseStock(
                material_id=m_idle.id, material_code=m_idle.code, material_name=m_idle.name,
                batch_no="OLD", location_id=loc.id, location_code=loc.code,
                location_name=loc.name, quantity=Decimal("88"),
            ),
        ]
    )
    await db.flush()

    def _mv(no: str, direction: str, source: str, m: WarehouseMaterial,
            qty: str, occurred: datetime) -> WarehouseMovement:
        return WarehouseMovement(
            movement_no=no, direction=direction, source_type=source,
            material_id=m.id, material_code=m.code, material_name=m.name,
            batch_no="", quantity=Decimal(qty), unit=m.unit,
            location_id=loc.id, location_code=loc.code, location_name=loc.name,
            occurred_at=occurred,
        )

    db.add_all(
        [
            # 今日入库 40、出库 5；昨日入库 20
            _mv("DASH-T-MV-IN-T", "inbound", "purchase", m_ok, "40", now_aware),
            _mv("DASH-T-MV-OUT-T", "outbound", "sale", m_ok, "5", now_aware),
            _mv("DASH-T-MV-IN-Y", "inbound", "purchase", m_ok, "20",
                now_aware - timedelta(days=1)),
            # 呆滞物料：100 天前最后一次入库
            _mv("DASH-T-MV-IDLE", "inbound", "purchase", m_idle, "88",
                now_aware - timedelta(days=100)),
        ]
    )

    db.add(
        WarehouseStocktake(
            stocktake_no="DASH-T-ST-1", status="draft", remark="驾驶舱测试盘点",
        )
    )

    snapshot_day = now_aware.date()
    db.add_all(
        [
            WarehouseStockDailySnapshot(
                snapshot_date=snapshot_day, material_id=m_ok.id,
                material_code=m_ok.code, material_name=m_ok.name,
                total_quantity=Decimal("480"), stock_rows=1,
            ),
            WarehouseStockDailySnapshot(
                snapshot_date=snapshot_day - timedelta(days=1), material_id=m_ok.id,
                material_code=m_ok.code, material_name=m_ok.name,
                total_quantity=Decimal("460"), stock_rows=1,
            ),
        ]
    )
    await db.commit()


async def _cleanup(db: AsyncSession) -> None:
    markers = (
        select(WarehouseMaterial.id).where(WarehouseMaterial.code.like("DASH-T-%")),
        select(WarehouseLocation.id).where(WarehouseLocation.code.like("DASH-T-%")),
        select(WarehouseStocktake.id).where(WarehouseStocktake.stocktake_no.like("DASH-T-%")),
    )
    await db.execute(
        delete(WarehouseStock).where(WarehouseStock.material_id.in_(markers[0]))
    )
    await db.execute(
        delete(WarehouseMovement).where(WarehouseMovement.movement_no.like("DASH-T-%"))
    )
    await db.execute(
        delete(WarehouseStockDailySnapshot).where(
            WarehouseStockDailySnapshot.material_code.like("DASH-T-%")
        )
    )
    await db.execute(delete(WarehouseStocktake).where(WarehouseStocktake.stocktake_no.like("DASH-T-%")))
    await db.execute(delete(WarehouseStock).where(WarehouseStock.location_id.in_(markers[1])))
    await db.execute(delete(WarehouseLocation).where(WarehouseLocation.code.like("DASH-T-%")))
    await db.execute(delete(WarehouseMaterial).where(WarehouseMaterial.code.like("DASH-T-%")))
    await db.commit()


async def test_movement_trend_fills_missing_days(dashboard_client: AsyncClient) -> None:
    """空库也应返回完整 N 天序列（零填充）。"""
    resp = await dashboard_client.get("/api/v1/warehouse/dashboard/movement-trend?days=7")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    trend = body["data"]
    assert len(trend) == 7
    assert all({"date", "inbound", "outbound"} <= set(item) for item in trend)
    assert trend[-1]["date"] == datetime.now(CN_TZ).strftime("%Y-%m-%d")


async def test_dashboard_summary(
    dashboard_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        resp = await dashboard_client.get("/api/v1/warehouse/dashboard/summary")
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert Decimal(str(data["total_quantity"])) == Decimal("618")  # 30+500+88
        assert data["today_inbound_quantity"] == 40.0
        assert data["today_outbound_quantity"] == 5.0
        assert data["yesterday_inbound_quantity"] == 20.0
        # 环比基于快照：今日快照 480 - 昨日快照 460 = +20
        assert data["total_quantity_change"] == pytest.approx(20.0)
        assert data["summary_text"]
        assert "低库存" in data["summary_text"]
    finally:
        await _cleanup(db_session)


async def test_stock_distribution(
    dashboard_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        resp = await dashboard_client.get("/api/v1/warehouse/dashboard/stock-distribution")
        assert resp.status_code == 200
        data = resp.json()["data"]

        by_category = {item["category"]: float(item["total_quantity"]) for item in data["by_category"]}
        assert by_category["raw"] == pytest.approx(118.0)  # 30 + 88
        assert by_category["packaging"] == pytest.approx(500.0)
        by_type = {item["location_type"]: float(item["total_quantity"]) for item in data["by_location_type"]}
        assert by_type["normal"] == pytest.approx(618.0)
    finally:
        await _cleanup(db_session)


async def test_low_stock_top(
    dashboard_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        resp = await dashboard_client.get("/api/v1/warehouse/dashboard/low-stock-top?limit=10")
        assert resp.status_code == 200
        data = resp.json()["data"]

        low_codes = [item["material_code"] for item in data["low_stock"]]
        assert "DASH-T-M-LOW" in low_codes  # 30 < 安全库存 100
        assert "DASH-T-M-OK" not in low_codes  # 500 > 10

        idle_codes = [item["material_code"] for item in data["idle"]]
        assert "DASH-T-M-IDLE" in idle_codes  # 100 天无入库
        idle_item = next(i for i in data["idle"] if i["material_code"] == "DASH-T-M-IDLE")
        assert idle_item["days_idle"] >= 90
    finally:
        await _cleanup(db_session)


async def test_dashboard_todos(
    dashboard_client: AsyncClient, db_session: AsyncSession
) -> None:
    try:
        await _seed(db_session)
        resp = await dashboard_client.get("/api/v1/warehouse/dashboard/todos")
        assert resp.status_code == 200
        data = resp.json()["data"]

        assert data["low_stock_count"] >= 1
        assert any(item["stocktake_no"] == "DASH-T-ST-1" for item in data["draft_stocktakes"])
        assert len(data["recent_movements"]) >= 1
        assert data["recent_movements"][0]["occurred_at"]
    finally:
        await _cleanup(db_session)
