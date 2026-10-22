"""query_standard_compliance 工具测试（S1 体系标准核查）。

接缝照 test_read_detail_tools：ctx=SimpleNamespace(deps=...)，service 层
opener 注入替身；真路径（连接已播种）只测信封不 mock。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.safety.business_agent.tools.read_tools import query_standard_compliance


class _FakeClient:
    def __init__(self, items):
        self._items = items

    async def search_records(self, **kwargs):
        return {"items": self._items, "has_more": False, "page_token": None}


def _std(no: str, *, element: str = "应急管理", metric_key=None, manual=None):
    return {
        "record_id": no,
        "fields": {
            "标准编号": no, "年度": "2099", "标准条款": f"{no} 条款",
            "依据": None, "要素归属": element, "指标键": metric_key,
            "比较符": "≥" if metric_key else None,
            "目标值": "1" if metric_key else None,
            "单位": "次" if metric_key else None,
            "周期": "半年" if metric_key else "年度",
            "责任部门": ["安环部"], "责任人": None,
            "上次完成日期": None, "人工核查结果": manual, "备注": None,
        },
    }


PKG = "app.modules.safety.service.standard_check"


async def test_tool_live_summary_and_groups(monkeypatch) -> None:
    from datetime import UTC, datetime, timedelta

    from app.modules.safety.service import standard_check

    today = (datetime.now(UTC) + timedelta(hours=8)).date()
    items = [
        _std("T-1", metric_key="drill.count.comprehensive_or_special"),
        _std("T-2", element="目标职责", metric_key=None, manual="未完成"),
    ]
    for item in items:
        item["fields"]["年度"] = str(today.year)

    async def fake_page(**kwargs):
        return await standard_check.page.build_standard_check_page(
            opener=lambda d, k: _FakeClient(items), today=today, **kwargs
        )

    monkeypatch.setattr(f"{PKG}.build_standard_check_page", fake_page)

    ctx = SimpleNamespace(deps=SimpleNamespace(db=None))
    result = await query_standard_compliance(ctx)
    assert result["success"] is True
    assert result["summary"]["total"] == 2
    assert result["summary"]["missed"] == 1
    rows = {r["no"]: r for g in result["groups"] for r in g["rows"]}
    assert rows["T-2"]["status"] == "missed"


async def test_tool_not_connected(monkeypatch) -> None:
    async def unconfigured(**kwargs):
        return {"status": "not_connected", "summary": None,
                "groups": [], "departments": [], "errors": []}

    monkeypatch.setattr(f"{PKG}.build_standard_check_page", unconfigured)
    ctx = SimpleNamespace(deps=SimpleNamespace(db=None))
    result = await query_standard_compliance(ctx)
    assert result["success"] is False
    assert "未接入" in result["error"]
