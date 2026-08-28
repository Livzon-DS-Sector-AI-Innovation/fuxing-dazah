"""检定到期提醒 API 端点功能测试。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.modules.meter.conftest import create_instrument


class TestCalibrationAlerts:
    async def test_alerts_list(self, api_context: tuple[AsyncClient, Any]) -> None:
        """提醒接口应返回含字段的提醒列表。"""
        client, db = api_context
        dept = f"TEST-ALERT-{uuid4().hex[:8]}"
        await create_instrument(
            db, department=dept, next_calibration_date=date.today() + timedelta(days=10)
        )
        resp = await client.get(
            "/api/v1/meter/calibration/alerts",
            params={"department": dept, "days_before": 30},
        )
        assert resp.status_code == 200
        alerts = resp.json()["data"]
        assert len(alerts) == 1
        assert alerts[0]["source"] == "instrument"
        assert alerts[0]["days_until_due"] == 10

    async def test_invalid_source_returns_422(self, api_context: tuple[AsyncClient, Any]) -> None:
        """非法 source 应返回 422。"""
        client, _ = api_context
        resp = await client.get(
            "/api/v1/meter/calibration/alerts", params={"source": "other"}
        )
        assert resp.status_code == 422

    async def test_days_before_bounds(self, api_context: tuple[AsyncClient, Any]) -> None:
        """days_before 超出 0-365 应返回 422。"""
        client, _ = api_context
        resp = await client.get(
            "/api/v1/meter/calibration/alerts", params={"days_before": 400}
        )
        assert resp.status_code == 422

    async def test_export_excel(self, api_context: tuple[AsyncClient, Any]) -> None:
        """提醒导出应为 spreadsheetml 类型。"""
        client, _ = api_context
        resp = await client.get("/api/v1/meter/calibration/alerts/export-excel")
        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]
