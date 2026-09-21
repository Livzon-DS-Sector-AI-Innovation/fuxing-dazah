"""年报与危化品专项测试（V3.0 分期D Ticket 04，§4.5）。

- get_annual_report：seed 全年 movement（真实库+回滚），校验 12 个月聚合；
- get_hazardous_report：FakeAdapter 注入 material_master 分类（大类/法规
  双口径命中矩阵），本地库 seed movement/stock join；
- annual_report 生成器 dry_run（LLM 打桩，正例+降级）；
- yearly 调度槽位直测（engine._calendar_slot）。
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.warehouse.push_center import generators
from app.modules.warehouse.push_center.engine import _calendar_slot
from app.modules.warehouse.reports import (
    build_annual_xlsx,
    get_annual_report,
    get_hazardous_report,
    is_hazardous_material,
)
from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_movement,
    create_stock,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


async def _seed_year_movements(db_session, material, location, year: int) -> None:
    """三个月各 1 笔出库 + 1 笔入库（数量可辨识）。"""
    for month, qty in ((1, "10"), (6, "20"), (12, "30")):
        await create_movement(
            db_session, material, location,
            direction="outbound", quantity=Decimal(qty),
            occurred_at=datetime(year, month, 15, tzinfo=CN_TZ),
        )
        await create_movement(
            db_session, material, location,
            direction="inbound", quantity=Decimal(qty),
            occurred_at=datetime(year, month, 5, tzinfo=CN_TZ),
        )


class TestAnnualReport:
    async def test_twelve_month_aggregation(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        material = await create_material(db_session)
        location = await create_location(db_session)
        year = 2025
        await _seed_year_movements(db_session, material, location, year)

        report = await get_annual_report(db_session, year)
        assert report["year"] == year
        assert report["summary"]["outbound_count"] == 3
        assert report["summary"]["outbound_qty"] == 60.0
        assert report["summary"]["inbound_qty"] == 60.0
        by_month = {m["month"]: m["outbound_qty"] for m in report["months"]}
        assert by_month[1] == 10.0
        assert by_month[6] == 20.0
        assert by_month[12] == 30.0
        assert report["items"][0]["outbound_qty"] == 60.0
        assert build_annual_xlsx(report)[:2] == b"PK"  # xlsx 魔数


class TestHazardousFilter:
    def test_is_hazardous_matrix(self) -> None:
        assert is_hazardous_material("危化品", "-") is True
        assert is_hazardous_material("原辅料", "危化品&易制爆") is True
        assert is_hazardous_material("原辅料", "危化品&易制毒") is True
        assert is_hazardous_material("原辅料", "危化品&重点监管") is True
        assert is_hazardous_material("原辅料", "危化品&高毒物品") is True
        assert is_hazardous_material("原辅料", "EVERSHINE") is False
        assert is_hazardous_material("包材", "") is False
        assert is_hazardous_material("", "") is False


class FakeMasterAdapter:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def search_records_page(self, table_key: str, **kwargs: Any) -> dict[str, Any]:
        assert table_key == "material_master"
        return {"records": self.rows, "total": len(self.rows), "page_token": None}


async def test_hazardous_report_join(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = await create_material(db_session, name="高锰酸钾")
    other = await create_material(db_session, name="某包材")
    location = await create_location(db_session)
    await create_movement(
        db_session, material, location, direction="outbound",
        quantity=Decimal("5"),
        occurred_at=datetime(2026, 9, 10, tzinfo=CN_TZ),
    )
    await create_movement(
        db_session, other, location, direction="outbound",
        quantity=Decimal("999"),
        occurred_at=datetime(2026, 9, 10, tzinfo=CN_TZ),
    )
    await create_stock(db_session, material, location, quantity=Decimal("7"))

    fake = FakeMasterAdapter([
        {"record_id": "m1", "fields": {"物料名称": "高锰酸钾", "物料大类": "原辅料",
                                        "法规危险性分类": "危化品&易制爆"}},
        {"record_id": "m2", "fields": {"物料名称": "硫酸", "物料大类": "危化品",
                                        "法规危险性分类": "危化品"}},
        {"record_id": "m3", "fields": {"物料名称": "某包材", "物料大类": "包材",
                                        "法规危险性分类": ""}},
        {"record_id": "m4", "fields": {"物料名称": "鱼蛋白胨", "物料大类": "原辅料",
                                        "法规危险性分类": "EVERSHINE"}},
    ])
    monkeypatch.setattr(
        "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
        lambda: fake,
    )
    report = await get_hazardous_report(db_session, days=90)
    names = [r["material_name"] for r in report["items"]]
    assert names == ["高锰酸钾", "硫酸"]  # 出库降序；包材/EVERSHINE 不命中
    by_name = {r["material_name"]: r for r in report["items"]}
    assert by_name["高锰酸钾"]["legal_class"] == "危化品&易制爆"
    assert by_name["高锰酸钾"]["outbound_qty"] == 5.0
    assert by_name["高锰酸钾"]["current_stock"] == 7.0
    assert by_name["硫酸"]["outbound_qty"] == 0.0  # 无本地数据保留分类行


class TestAnnualGenerator:
    async def test_card_with_stubbed_llm(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeAdapter:
            async def search_records_page(self, *a: Any, **k: Any) -> dict[str, Any]:
                return {"records": [], "total": 0, "page_token": None}

        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: _FakeAdapter(),
        )
        monkeypatch.setattr(
            generators, "_llm_summarize", _fake_llm_ok
        )
        now = datetime(2026, 1, 1, 8, 30, tzinfo=CN_TZ)
        card = await generators._generate_annual_report(db_session, now)
        assert card["header"]["title"]["content"] == "仓储年报 · 2025"
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "原辅料 2025 年度" in text
        assert "年度解读" in text
        assert "桩解读" in text

    async def test_llm_failure_degrades(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class _FakeAdapter:
            async def search_records_page(self, *a: Any, **k: Any) -> dict[str, Any]:
                return {"records": [], "total": 0, "page_token": None}

        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: _FakeAdapter(),
        )

        async def _boom(_prompt: str) -> str:
            raise RuntimeError("llm down")

        monkeypatch.setattr(generators, "_llm_summarize", _boom)
        now = datetime(2026, 1, 1, 8, 30, tzinfo=CN_TZ)
        card = await generators._generate_annual_report(db_session, now)
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "详见 Web 报表中心年报页" in text


async def _fake_llm_ok(_prompt: str) -> str:
    return "桩解读：年度运行平稳。"


class TestYearlySlot:
    """yearly 调度槽位（V3.0 分期D 新增第五态）。"""

    SCHEDULE = {"type": "yearly", "month": 1, "day": 1, "time": "08:30"}

    def test_on_jan1_morning_in_window(self) -> None:
        now = datetime(2026, 1, 1, 9, 0, tzinfo=CN_TZ)
        slot, window = _calendar_slot(self.SCHEDULE, now)
        assert slot == datetime(2026, 1, 1, 8, 30, tzinfo=CN_TZ)
        assert window == 60

    def test_before_jan1_uses_last_year_slot(self) -> None:
        now = datetime(2025, 12, 15, 10, 0, tzinfo=CN_TZ)
        slot, _ = _calendar_slot(self.SCHEDULE, now)
        assert slot == datetime(2025, 1, 1, 8, 30, tzinfo=CN_TZ)

    def test_outside_window_no_trigger(self) -> None:
        now = datetime(2026, 3, 1, 8, 45, tzinfo=CN_TZ)
        slot, _ = _calendar_slot(self.SCHEDULE, now)
        assert slot == datetime(2026, 1, 1, 8, 30, tzinfo=CN_TZ)
