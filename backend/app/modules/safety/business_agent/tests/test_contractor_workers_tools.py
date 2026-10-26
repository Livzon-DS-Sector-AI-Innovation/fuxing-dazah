"""承包商在册人员 / 岗位字典 Agent 只读工具单测（3.x 平台关联 F1）。

接缝（照 test_read_detail_tools 惯例）：
- 直接调用工具函数（不走 core.pipeline），service 单例用 monkeypatch 替换；
- registry TOOL_KIND / _all_read_funcs 接线 + 按需不进常驻；
- tool_selector 关键词激活；viewer 权限。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.business_agent import tool_selector
from app.modules.safety.business_agent.core.permissions import (
    ROLE_VIEWER,
    allowed_tools,
)
from app.modules.safety.business_agent.tools import registry
from app.modules.safety.business_agent.tools.read_tools import (
    query_contractor_workers,
    query_org_posts,
)

NEW_TOOLS = ["query_contractor_workers", "query_org_posts"]


def _ctx() -> Any:
    return SimpleNamespace(deps=SimpleNamespace(db=None))


# ── 接线：registry / 常驻面 / selector / 权限 ──────────────────────


def test_registry_wiring() -> None:
    for name in NEW_TOOLS:
        assert registry.TOOL_KIND[name] is False  # False=只读
        assert name in registry._FUNC_BY_NAME


def test_not_in_resident_tools() -> None:
    # 拍板口径：按需工具，常驻 38 不动（一期减法 ≤38）
    for name in NEW_TOOLS:
        assert name not in registry.RESIDENT_TOOLS


def test_tool_group_registered() -> None:
    group = tool_selector.TOOL_GROUPS.get("contractor_workers", [])
    for name in NEW_TOOLS:
        assert name in group


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("现在有哪些承包商的电工在册", "query_contractor_workers"),
        ("保险没覆盖的外包人员名单", "query_contractor_workers"),
        ("厂里冻干岗位有哪些", "query_org_posts"),
        ("查一下岗位字典", "query_org_posts"),
    ],
)
def test_tool_selector_activates(message: str, expected: str) -> None:
    names = tool_selector.select_tool_names(message)
    assert expected in names


def test_viewer_allowed() -> None:
    allowed = allowed_tools(ROLE_VIEWER)
    for name in NEW_TOOLS:
        assert name in allowed


# ── 工具行为：过滤 + 打码 + 信封透传 ────────────────────────────────


def _payload() -> dict[str, Any]:
    def row(rid: str, **kw: Any) -> dict[str, Any]:
        base = {
            "id": rid,
            "name": kw.get("name", "施瑞国"),
            "contractor_name": kw.get("contractor_name", "福清市一建建筑工程有限公司"),
            "work_type": kw.get("work_type", "焊工"),
            "age": kw.get("age", 45),
            "join_job_date": "2025-12-01",
            "card_no_masked": kw.get("card_no_masked", "350***92"),
            "phone_masked": "139***67",
            "insurance_status": kw.get("insurance_status", "covered"),
            "insurance_expire_date": "2027-06-01",
            "insurance_days_left": 300,
            "insurance_source_company": "福清市一建建筑工程有限公司",
            "cert_status": kw.get("cert_status", "hit"),
            "cert_project": kw.get("cert_project"),
            "cert_next_review_date": kw.get("cert_next_review_date"),
            "age_flag": kw.get("age_flag", "none"),
            "anomalies": kw.get("anomalies", []),
        }
        return base

    return {
        "status": "live",
        "fetched_at": "2026-10-26T10:00:00+08:00",
        "message": None,
        "stats": {
            "total": 3,
            "contractors": 3,
            "insurance_covered_pct": 33,
            "special_total": 2,
            "cert_covered_pct": 50,
            "overage_count": 1,
            "overage_warn_count": 0,
        },
        "workers": [
            row("r1"),
            row(
                "r2",
                name="李四",
                contractor_name="江苏天目建设集团有限公司",
                work_type="普工",
                age=61,
                insurance_status="uncovered",
                cert_status="nonspecial",
                age_flag="red",
                anomalies=["超龄", "保险未覆盖"],
            ),
            row(
                "r3",
                name="王五",
                work_type="电工",
                age=57,
                insurance_status="expiring",
                cert_status="missing",
                age_flag="yellow",
                anomalies=["保险临期", "未见持证记录"],
            ),
        ],
    }


class _StubService:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def get_payload(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_query_contractor_workers_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.safety.service.contractor_workers.open_service",
        lambda: _StubService(_payload()),
    )
    result = await query_contractor_workers(_ctx(), work_type="电工")
    assert result["status"] == "live"
    assert result["total"] == 1
    assert result["items"][0]["name"] == "王五"
    # 打码口径与页面一致
    assert result["items"][0]["card_no_masked"] == "350***92"

    result2 = await query_contractor_workers(_ctx(), insurance_missing=True)
    # 口径与统计卡一致：临期（王五）不算缺失，只有未覆盖（李四）命中
    assert {i["name"] for i in result2["items"]} == {"李四"}

    result3 = await query_contractor_workers(_ctx(), cert_missing_only=True)
    assert {i["name"] for i in result3["items"]} == {"王五"}

    result4 = await query_contractor_workers(_ctx(), age_above=55)
    assert {i["name"] for i in result4["items"]} == {"李四", "王五"}

    result5 = await query_contractor_workers(_ctx(), contractor="天目")
    assert {i["name"] for i in result5["items"]} == {"李四"}


@pytest.mark.asyncio
async def test_query_contractor_workers_page_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.safety.service.contractor_workers.open_service",
        lambda: _StubService(_payload()),
    )
    result = await query_contractor_workers(_ctx(), page=1, page_size=2)
    assert result["page_size"] == 2
    assert len(result["items"]) == 2
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_query_contractor_workers_empty_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.safety.service.contractor_workers.open_service",
        lambda: _StubService(
            {
                "status": "empty",
                "fetched_at": None,
                "message": "平台接口暂不可用",
                "stats": None,
                "workers": [],
            }
        ),
    )
    result = await query_contractor_workers(_ctx())
    assert result["status"] == "empty"
    assert result["items"] == []
    assert result["message"] == "平台接口暂不可用"


@pytest.mark.asyncio
async def test_query_org_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubOrg:
        async def get_payload(
            self, *, dept: str | None = None, keyword: str | None = None
        ) -> dict[str, Any]:
            posts = [
                {"post_name": "1#冻干线冻干出料操作工", "dept_names": ["精制工程一部", "精制工程二部"], "headcount": 2},
                {"post_name": "电工", "dept_names": ["动力部"], "headcount": 1},
            ]
            if keyword:
                posts = [p for p in posts if keyword in p["post_name"]]
            if dept:
                posts = [p for p in posts if any(dept in d for d in p["dept_names"])]
            return {
                "status": "live",
                "fetched_at": "2026-10-26T10:00:00+08:00",
                "message": None,
                "posts": posts,
            }

    monkeypatch.setattr(
        "app.modules.safety.service.org_directory.open_org_posts_service",
        lambda: _StubOrg(),
    )
    result = await query_org_posts(_ctx(), keyword="冻干")
    assert result["status"] == "live"
    assert result["total"] == 1
    assert result["posts"][0]["post_name"] == "1#冻干线冻干出料操作工"
    assert result["posts"][0]["dept_names"] == ["精制工程一部", "精制工程二部"]
