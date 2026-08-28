"""全局设置 API 端点功能测试。

契约：HH:MM 格式（schema 正则）；数值越界（25:99）由 service 拒绝返回 400；
更新端点内部 commit，用 client_with_noop_commit 隔离。
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient


class TestGetSettings:
    async def test_get_settings(self, api_context: tuple[AsyncClient, Any]) -> None:
        """获取设置应返回默认提醒时间（不存在时自动创建 17:45）。"""
        client, _ = api_context
        resp = await client.get("/api/v1/meter/settings")
        assert resp.status_code == 200
        assert resp.json()["data"]["notify_time"] == "17:45"


class TestUpdateSettings:
    async def test_update_valid_time(self, client_with_noop_commit: AsyncClient) -> None:
        """合法时间应更新成功并返回新值。"""
        resp = await client_with_noop_commit.put(
            "/api/v1/meter/settings", json={"notify_time": "08:30"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["notify_time"] == "08:30"

    async def test_out_of_range_time_returns_400(self, client_with_noop_commit: AsyncClient) -> None:
        """格式合法但数值越界（25:99）应返回 400。"""
        resp = await client_with_noop_commit.put(
            "/api/v1/meter/settings", json={"notify_time": "25:99"}
        )
        assert resp.status_code == 400

    async def test_malformed_time_returns_422(self, client_with_noop_commit: AsyncClient) -> None:
        """不符合 HH:MM 格式应被 schema 拒绝返回 422。"""
        resp = await client_with_noop_commit.put(
            "/api/v1/meter/settings", json={"notify_time": "8点30"}
        )
        assert resp.status_code == 422
