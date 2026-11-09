"""query_oh(entity=labor) — 劳保用品目录 agent 查询（monkeypatch ledger，不真调飞书）。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.modules.safety.business_agent.tools import read_tools
from app.modules.safety.service.labor_supply import ledger as ls_ledger
from app.modules.safety.service.labor_supply.reader import LaborProductView


def _fake_ctx():
    return SimpleNamespace(deps=SimpleNamespace(db=None))


def _view(**kw) -> LaborProductView:
    base = dict(
        record_id="recL1", name="防尘口罩", model="3M 9502+基础款",
        category="口罩", protection_type="呼吸防护", unit="个", vendor="3M",
        lifespan_years=None, report_attachments=[], manual_attachments=[],
    )
    base.update(kw)
    return LaborProductView(**base)


def _labor_on(monkeypatch, views):
    monkeypatch.setattr(ls_ledger, "enabled", lambda: True)

    async def _p(*a, **kw):
        return views

    monkeypatch.setattr(ls_ledger, "fetch_products", _p)


def test_dispatch_routes_labor_entity(monkeypatch) -> None:
    calls: dict[str, dict] = {}

    async def impl(ctx, **kw):
        calls["labor"] = kw
        return {"items": [], "total": 0}

    monkeypatch.setattr(read_tools, "_query_oh_labor_impl", impl)
    asyncio.run(
        read_tools.query_oh(
            _fake_ctx(), entity="labor", keyword="口罩", category="口罩",
            protection_type="呼吸防护",
        )
    )
    assert calls["labor"] == {
        "keyword": "口罩", "category": "口罩",
        "protection_type": "呼吸防护", "limit": 30,
    }


def test_unknown_entity_error_mentions_labor(monkeypatch) -> None:
    out = asyncio.run(read_tools.query_oh(_fake_ctx(), entity="不存在的"))
    assert "labor" in out["error"]


def test_labor_impl_filters(monkeypatch) -> None:
    _labor_on(
        monkeypatch,
        [
            _view(),
            _view(record_id="recL2", name="防化手套", model="PVA工业A类",
                  vendor="", category="手套", protection_type="手部防护"),
        ],
    )
    out = asyncio.run(
        read_tools._query_oh_labor_impl(
            _fake_ctx(), keyword=None, category=None, protection_type=None, limit=30
        )
    )
    assert out["total"] == 2
    out = asyncio.run(
        read_tools._query_oh_labor_impl(
            _fake_ctx(), keyword="3M", category=None, protection_type=None, limit=30
        )
    )
    assert out["total"] == 1
    assert out["items"][0]["name"] == "防尘口罩"
    # 防护类型精确过滤
    out = asyncio.run(
        read_tools._query_oh_labor_impl(
            _fake_ctx(), keyword=None, category=None,
            protection_type="手部防护", limit=30,
        )
    )
    assert out["total"] == 1
    assert out["items"][0]["name"] == "防化手套"
    # keyword 也匹配防护类型
    out = asyncio.run(
        read_tools._query_oh_labor_impl(
            _fake_ctx(), keyword="手部", category=None, protection_type=None, limit=30
        )
    )
    assert out["total"] == 1
    # 条目字段：目录关键列 + 检测报告有无
    item = out["items"][0]
    assert item["protection_type"] == "手部防护"
    assert item["has_report"] is False


def test_labor_impl_gate_off(monkeypatch) -> None:
    monkeypatch.setattr(ls_ledger, "enabled", lambda: False)
    out = asyncio.run(
        read_tools._query_oh_labor_impl(
            _fake_ctx(), keyword=None, category=None, protection_type=None, limit=30
        )
    )
    assert "未启用" in out["message"]


def test_labor_impl_source_failure(monkeypatch) -> None:
    monkeypatch.setattr(ls_ledger, "enabled", lambda: True)

    async def _boom(*a, **kw):
        raise RuntimeError("bitable down")

    monkeypatch.setattr(ls_ledger, "fetch_products", _boom)
    out = asyncio.run(
        read_tools._query_oh_labor_impl(
            _fake_ctx(), keyword=None, category=None, protection_type=None, limit=30
        )
    )
    assert "不可用" in out["message"]
