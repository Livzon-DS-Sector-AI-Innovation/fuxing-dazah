"""监护补贴只读 API 测试（subsidy_router：sources / guardian-summary）。

接缝（spec §5）：monkeypatch ``api.subsidy.fetch_ledger_rows``——其余
（build_ledger_plan / SubsidyService.calculate / b_cert_adjusted_total）走真实
纯函数链，与 Agent 生成、月报私发同口径。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.safety.api import subsidy as subsidy_api

TZ = ZoneInfo("Asia/Shanghai")


def _ts(y: int, m: int, d: int, h: int = 0, minute: int = 0) -> int:
    return int(datetime(y, m, d, h, minute, tzinfo=TZ).timestamp() * 1000)


def _row4(
    name: str = "吴家达",
    level: str = "A证",
    op_level: str = "一级",
    date_ms: int | None = None,
    period: str = "09:15-17:10",
) -> dict[str, Any]:
    return {"fields": {
        "姓名": [{"text": name, "type": "text"}],
        "监护证类别": level,
        "特殊作业类型": "动火作业",
        "作业级别": op_level,
        "日期": date_ms if date_ms is not None else _ts(2026, 9, 3),
        "时间段（写全：如8:30-11:00  13:30-17:00）": [{"text": period, "type": "text"}],
        "监护内容（具体到作业位置）": [{"text": "车间一管道打磨", "type": "text"}],
    }}


def _row6(
    name: str = "池守城",
    period: str = "09:10-17:10",
    day: str = "2026.09.10",
) -> dict[str, Any]:
    return {"fields": {
        "姓名": [{"text": name, "type": "text"}],
        "特殊作业类型": ["动火作业"],
        "作业级别": "一级",
        "作业地点及内容": [{"text": "二期车间更换灯具", "type": "text"}],
        "日期": [{"text": day, "type": "text"}],
        "时间段": [{"text": period, "type": "text"}],
    }}


def _set_rows(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    async def fake_fetch(source: Any) -> list[dict[str, Any]]:
        return rows
    monkeypatch.setattr(subsidy_api, "fetch_ledger_rows", fake_fetch)


# ── sources ─────────────────────────────────────────────────────────


async def test_sources_returns_three_ledger_departments(client) -> None:
    resp = await client.get("/api/v1/safety/subsidy/sources")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [d["department"] for d in data] == [
        "提炼工程四部", "提炼工程五部", "提炼工程六部",
    ]
    assert all(d["source"] == "dept_ledger" for d in data)


# ── guardian-summary：台账路径 ──────────────────────────────────────


async def test_summary_ledger_path_structure_and_dual_amount(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """四部两行（A/B 证各一）→ 结构齐全；折算前 ≠ 折算后（B 证 0.5）。"""
    _set_rows(monkeypatch, [
        _row4(name="吴家达", level="A证", date_ms=_ts(2026, 9, 3), period="09:15-17:10"),
        _row4(name="徐瑞芬", level="B证", date_ms=_ts(2026, 9, 4), period="08:30-11:30"),
    ])

    resp = await client.get(
        "/api/v1/safety/subsidy/guardian-summary",
        params={"department": "提炼工程四部", "year": 2026, "month": 9},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["department"] == "提炼工程四部"
    assert (data["year"], data["month"]) == (2026, 9)
    assert data["source"] == "dept_ledger"

    stats = data["stats"]
    assert stats["matched"] == 2
    assert stats["guardians"] == 2
    assert stats["total_amount"] == sum(d["subsidy_amount"] for d in data["details"])
    assert stats["adjusted_total"] < stats["total_amount"]       # B 证 0.5 折算后更少
    assert stats["unmatched"] == 0 and stats["skipped"] == 0

    # 按监护人汇总：姓名/级别/合计
    names = {s["guardian_name"]: s for s in data["summaries"]}
    assert set(names) == {"吴家达", "徐瑞芬"}
    assert names["吴家达"]["guardian_level"] == "A证"
    assert names["吴家达"]["total"] > 0

    # 明细：票号=台账行标识、金额与备注透传
    detail = next(d for d in data["details"] if d["guardian_name"] == "吴家达")
    assert detail["ticket_no"] == "09-03 吴家达"
    assert detail["operation_type"] == "动火作业"
    assert detail["subsidy_amount"] > 0
    assert "billing_units" in detail and "remark" in detail


async def test_summary_unmatched_and_skipped_lists(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """六部无级别列→全员待核对；坏时间段→跳过并给原因。"""
    _set_rows(monkeypatch, [
        _row6(name="池守城", period="09:10-17:10"),
        _row6(name="彭飞琼", period="08：35-18：30"),
        _row6(name="罗利梅", period="待定", day="2026.09.12"),  # 解析失败→跳过
    ])

    resp = await client.get(
        "/api/v1/safety/subsidy/guardian-summary",
        params={"department": "提炼工程六部", "year": 2026, "month": 9},
    )
    data = resp.json()["data"]

    assert data["stats"]["matched"] == 2
    assert data["stats"]["unmatched"] == 2
    assert data["stats"]["unmatched_people"] == 2
    assert data["stats"]["skipped"] == 1
    assert {u["name"] for u in data["unmatched"]} == {"池守城", "彭飞琼"}
    assert data["skipped"][0]["reason"] == "时间段无法解析"
    assert data["skipped"][0]["ticket_no"] == "09-12 罗利梅"


# ── 错误分支 ────────────────────────────────────────────────────────


async def test_summary_invalid_month(client) -> None:
    resp = await client.get(
        "/api/v1/safety/subsidy/guardian-summary",
        params={"department": "提炼工程四部", "year": 2026, "month": 13},
    )
    body = resp.json()
    assert body["code"] == 400
    assert "月份" in body["message"]


async def test_summary_unknown_department_hints_agent(client) -> None:
    """非台账部门 → 错误 + 引导 AI 助手（拍板点 A）。"""
    resp = await client.get(
        "/api/v1/safety/subsidy/guardian-summary",
        params={"department": "环保部", "year": 2026, "month": 9},
    )
    body = resp.json()
    assert body["code"] == 404
    assert "AI 助手" in body["message"]


async def test_summary_fetch_failure_degrades(
    client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(source: Any) -> list[dict[str, Any]]:
        raise RuntimeError("bitable 凭据失效")
    monkeypatch.setattr(subsidy_api, "fetch_ledger_rows", boom)

    resp = await client.get(
        "/api/v1/safety/subsidy/guardian-summary",
        params={"department": "提炼工程四部", "year": 2026, "month": 9},
    )
    body = resp.json()
    assert body["code"] == 502
    assert "台账" in body["message"]
