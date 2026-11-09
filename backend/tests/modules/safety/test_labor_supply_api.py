"""labor_supply API 单测（monkeypatch ledger 模块函数，不真调飞书）。"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.modules.safety.service.labor_supply import ledger as ls_ledger
from app.modules.safety.service.labor_supply.reader import (
    LaborProductView,
    coverage_stats,
    to_view,
)


def _view(**overrides: Any) -> LaborProductView:
    base = dict(
        record_id="recA1",
        name="防尘口罩",
        model="3M 9502+基础款",
        category="口罩",
        protection_type="呼吸防护",
        unit="个",
        vendor="3M",
        lifespan_years=2.5,
        report_attachments=[{"file_token": "ftk1", "name": "report.pdf", "size": 100}],
        manual_attachments=[],
    )
    base.update(overrides)
    return LaborProductView(**base)


@pytest.fixture
def two_products(monkeypatch: pytest.MonkeyPatch) -> list[LaborProductView]:
    views = [
        _view(),
        _view(
            record_id="recA2",
            name="防化手套",
            model="PVA工业A类",
            category="手套",
            protection_type="手部防护",
            vendor="",
        ),
    ]
    monkeypatch.setattr(ls_ledger, "enabled", lambda: True)
    monkeypatch.setattr(ls_ledger, "fetch_products", _async_of(views))
    return views


def _async_of(value: Any):
    async def _f(*_: Any, **__: Any) -> Any:
        return value

    return _f


# ── GET /labor-supply/products ──────────────────────────────────

@pytest.mark.asyncio
async def test_products_list_with_stats(client: AsyncClient, two_products) -> None:
    resp = await client.get("/api/v1/safety/labor-supply/products")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    data = body["data"]
    assert data["source"] == "bitable"
    assert data["total"] == 2
    assert data["stats"]["total"] == 2
    assert data["stats"]["protection_types"] == {"呼吸防护": 1, "手部防护": 1}
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_products_filter_protection_type(
    client: AsyncClient, two_products
) -> None:
    resp = await client.get(
        "/api/v1/safety/labor-supply/products",
        params={"protection_type": "手部防护"},
    )
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["name"] == "防化手套"


@pytest.mark.asyncio
async def test_products_filter_keyword(
    client: AsyncClient, two_products
) -> None:
    resp = await client.get(
        "/api/v1/safety/labor-supply/products", params={"keyword": "3M"}
    )
    assert resp.json()["data"]["total"] == 1  # 型号命中
    resp = await client.get(
        "/api/v1/safety/labor-supply/products", params={"keyword": "不存在的东西"}
    )
    assert resp.json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_products_pagination(client: AsyncClient, two_products) -> None:
    resp = await client.get(
        "/api/v1/safety/labor-supply/products",
        params={"page": 2, "page_size": 1},
    )
    data = resp.json()["data"]
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["record_id"] == "recA2"
    assert data["meta"]["page"] == 2


@pytest.mark.asyncio
async def test_products_gate_off_degrades(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ls_ledger, "enabled", lambda: False)

    async def _boom(*_: Any, **__: Any) -> list[LaborProductView]:
        raise AssertionError("开关关闭时不应触达飞书")

    monkeypatch.setattr(ls_ledger, "fetch_products", _boom)
    resp = await client.get("/api/v1/safety/labor-supply/products")
    data = resp.json()["data"]
    assert data["source"] == "not_enabled"
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_products_fetch_failure_degrades(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ls_ledger, "enabled", lambda: True)

    async def _boom(*_: Any, **__: Any) -> list[LaborProductView]:
        raise RuntimeError("bitable unreachable")

    monkeypatch.setattr(ls_ledger, "fetch_products", _boom)
    resp = await client.get("/api/v1/safety/labor-supply/products")
    data = resp.json()["data"]
    assert data["source"] == "degraded"
    assert data["items"] == []


# ── GET /labor-supply/attachments/{record_id} ───────────────────

@pytest.mark.asyncio
async def test_attachment_proxy_streams_bytes(
    client: AsyncClient, two_products, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloaded: dict[str, Any] = {}

    class _FakeBitableClient:
        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        async def get_field_id_by_name(self, name: str) -> str | None:
            return "fldREPORT"

        async def download_attachment(
            self, file_token: str, extra: str | None = None
        ) -> bytes | None:
            downloaded["file_token"] = file_token
            downloaded["extra"] = extra
            return b"%PDF-fake"

    monkeypatch.setattr(
        "app.modules.safety.feishu.bitable_client.SafetyBitableClient",
        _FakeBitableClient,
    )
    resp = await client.get(
        "/api/v1/safety/labor-supply/attachments/recA1",
        params={"field_name": "检测报告", "file_token": "ftk1"},
    )
    assert resp.status_code == 200
    assert resp.content == b"%PDF-fake"
    assert "report.pdf" in resp.headers.get("content-disposition", "")
    assert downloaded["file_token"] == "ftk1"
    assert downloaded["extra"]  # bitablePerm 鉴权参数已带上


@pytest.mark.asyncio
async def test_attachment_unknown_token_rejected(
    client: AsyncClient, two_products
) -> None:
    """file_token 不属于该记录该字段 → 404（防任意 token 探测）。"""
    resp = await client.get(
        "/api/v1/safety/labor-supply/attachments/recA1",
        params={"field_name": "检测报告", "file_token": "not-in-record"},
    )
    assert resp.json()["code"] == 404


@pytest.mark.asyncio
async def test_attachment_bad_field_name_rejected(
    client: AsyncClient, two_products
) -> None:
    resp = await client.get(
        "/api/v1/safety/labor-supply/attachments/recA1",
        params={"field_name": "厂家", "file_token": "ftk1"},
    )
    assert resp.json()["code"] == 400


@pytest.mark.asyncio
async def test_coverage_stats_helper_reused() -> None:
    """coverage_stats 是纯函数，API 与面板共用同一口径。"""
    stats = coverage_stats([])
    assert stats["total"] == 0
    assert to_view({"record_id": "x", "fields": {}}) is None
