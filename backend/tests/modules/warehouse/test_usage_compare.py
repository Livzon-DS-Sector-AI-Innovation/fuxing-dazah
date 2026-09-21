"""月度实际vs预期用量对比测试（V3.0 分期D Ticket 05，§4.4⑥）。"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.warehouse.push_center import generators
from app.modules.warehouse.reports import get_usage_compare
from tests.modules.warehouse.conftest import (
    create_location,
    create_material,
    create_movement,
)

CN_TZ = ZoneInfo("Asia/Shanghai")


class FakeMasterAdapter:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    async def search_records_page(self, table_key: str, **kwargs: Any) -> dict[str, Any]:
        assert table_key == "material_master"
        return {"records": self.rows, "total": len(self.rows), "page_token": None}


async def test_usage_compare_deviation_and_baseline(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    mat_a = await create_material(db_session, name="硫酸")
    mat_b = await create_material(db_session, name="鱼蛋白胨")
    await create_material(db_session, name="柠檬酸三铵")  # 有基准无用量
    location = await create_location(db_session)
    # 硫酸：实际 50，预期 100 → 偏差 50%；鱼蛋白胨：实际 10，无基准；
    # 柠檬酸三铵：无实际，预期 20（有基准无用量行）
    for mat, qty in ((mat_a, "50"), (mat_b, "10")):
        await create_movement(
            db_session, mat, location, direction="outbound", quantity=Decimal(qty),
            occurred_at=datetime(2026, 8, 10, tzinfo=CN_TZ),
        )
    # 窗口外噪声
    await create_movement(
        db_session, mat_a, location, direction="outbound", quantity=Decimal("999"),
        occurred_at=datetime(2026, 7, 31, tzinfo=CN_TZ),
    )

    fake = FakeMasterAdapter([
        {"record_id": "m1", "fields": {"物料名称": "硫酸", "月度预期用量": 100}},
        {"record_id": "m2", "fields": {"物料名称": "鱼蛋白胨", "月度预期用量": None}},
        {"record_id": "m3", "fields": {"物料名称": "柠檬酸三铵", "月度预期用量": 20}},
        {"record_id": "m4", "fields": {"物料名称": "零基准物料", "月度预期用量": 0}},
    ])
    monkeypatch.setattr(
        "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
        lambda: fake,
    )
    report = await get_usage_compare(db_session, 2026, 8)
    assert report["total"] == 2  # 鱼蛋白胨（无基准）不进行偏差计算不进 items
    assert report["no_baseline_with_usage"] == 1
    by_name = {r["material_name"]: r for r in report["items"]}
    assert by_name["硫酸"]["actual_qty"] == 50.0
    assert by_name["硫酸"]["deviation"] == 0.5
    assert by_name["柠檬酸三铵"]["deviation"] is None  # 有基准无用量
    # 偏差行在前，无偏差行殿后
    assert report["items"][0]["material_name"] == "硫酸"


class TestUsageCompareGenerator:
    async def test_card_with_deviations(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mat = await create_material(db_session, name="硫酸")
        location = await create_location(db_session)
        await create_movement(
            db_session, mat, location, direction="outbound", quantity=Decimal("50"),
            occurred_at=datetime(2026, 8, 10, tzinfo=CN_TZ),
        )
        fake = FakeMasterAdapter([
            {"record_id": "m1", "fields": {"物料名称": "硫酸", "月度预期用量": 100}},
        ])
        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: fake,
        )

        async def _fake_llm(_prompt: str) -> str:
            return "桩建议：控制硫酸领用。"

        monkeypatch.setattr(generators, "_llm_summarize", _fake_llm)
        now = datetime(2026, 9, 1, 9, 30, tzinfo=CN_TZ)
        card = await generators._generate_usage_compare(db_session, now)
        assert card["header"]["title"]["content"] == "物料用量对比 · 2026-08"
        assert card["header"]["template"] == "orange"
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "实际 50 / 预期 100（偏差 50%）" in text
        assert "桩建议" in text

    async def test_card_without_baseline_hint(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = FakeMasterAdapter([])
        monkeypatch.setattr(
            "app.modules.warehouse.bitable_adapter.WarehouseBitableAdapter",
            lambda: fake,
        )
        now = datetime(2026, 9, 1, 9, 30, tzinfo=CN_TZ)
        card = await generators._generate_usage_compare(db_session, now)
        assert card["header"]["template"] == "blue"
        text = "\n".join(
            str(el.get("content") or "") for el in card["body"]["elements"]
        )
        assert "月度预期用量" in text  # 引导维护基准
