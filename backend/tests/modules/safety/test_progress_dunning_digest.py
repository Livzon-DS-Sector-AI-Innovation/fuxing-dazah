"""未更新进展催办 → 「安全速递」格子的单元测试。

纯内存桩验证，不依赖 Redis / 飞书网络：催办结果应作为 ``progress_dunning``
格子投进当日总卡——有命中投催办简报（含已私发对象），0 命中投
「今日无需催办」简报（有无均报，口径对齐消防报警日报）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.feishu import daily_digest, mention, notification, progress_card
from app.modules.safety.feishu.daily_digest import DigestCell
from app.modules.safety.service.hazard_direct import progress_dunning
from app.modules.safety.service.hazard_direct.bitable_repo import HazardView


def _view(no: str, dept: str = "设备工程部") -> HazardView:
    return HazardView(
        record_id=f"rec_{no}", hazard_no=no,
        description="未按期更新整改进展", department=dept,
    )


def _person(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, user_id=f"u_{name}", open_id=f"ou_{name}")


def _stats(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "total": 2, "sent": 0, "skipped": 0, "errors": 0,
        "marked": 2, "recipients": 0,
    }
    base.update(over)
    return base


def test_progress_dunning_registered_in_cell_order() -> None:
    assert "progress_dunning" in daily_digest.CELL_ORDER


def test_build_cell_all_sent() -> None:
    v1, v2 = _view("HZ-001"), _view("HZ-002")
    plan = [
        (v1, "责任人", _person("张三")),
        (v1, "分管安全员", _person("李四")),
        (v2, "责任人", _person("李四")),
    ]
    cell = progress_dunning._build_dunning_cell(
        [v1, v2], plan, plan, [], _stats(sent=3, recipients=2),
    )
    assert isinstance(cell, DigestCell)
    assert cell.tag_color == "orange"
    assert cell.tag_text == "进展催办"
    assert cell.stats == "未更新进展 **2** 项 ｜ 已私发 **2** 人（3 张卡送达）"

    detail = cell.detail
    assert "**已私发对象（2 人）**" in detail
    assert "- 张三（责任人）：HZ-001" in detail
    # 李四既是 HZ-001 的安全员又是 HZ-002 的责任人 → 角色合并、隐患去重
    assert "- 李四（分管安全员/责任人）：HZ-001、HZ-002" in detail
    assert "**催办明细（2 项）**" in detail
    assert (
        "- **HZ-001**（设备工程部）未按期更新整改进展 "
        "→ 责任人 张三 ｜ 分管安全员 李四" in detail
    )
    assert "未送达" not in detail
    assert "可在卡片内直接提交进展" in cell.zone


def test_build_cell_partial_failure_marks_unsent() -> None:
    v1, v2 = _view("HZ-001"), _view("HZ-002")
    plan = [
        (v1, "责任人", _person("张三")),
        (v2, "责任人", _person("李四")),
    ]
    sent_plan = plan[:1]  # HZ-002 私发失败
    failed_plan = plan[1:]
    cell = progress_dunning._build_dunning_cell(
        [v1, v2], plan, sent_plan, failed_plan, _stats(sent=1, skipped=1),
    )
    detail = cell.detail
    assert "- 张三（责任人）：HZ-001" in detail
    assert "已私发 **1** 人（1 张卡送达）" in cell.stats
    assert "⚠️ 未送达 1 张：HZ-002（责任人 李四）" in detail


def test_build_cell_no_recipients_resolved() -> None:
    v1 = _view("HZ-001")
    cell = progress_dunning._build_dunning_cell(
        [v1], [], [], [], _stats(),
    )
    detail = cell.detail
    assert "**已私发对象（0 人）**" in detail
    assert "- 无（全部发送失败或收件人解析失败）" in detail
    assert "- **HZ-001**（设备工程部）未按期更新整改进展 → 收件人解析失败" in detail


def test_build_cell_truncates_long_description() -> None:
    v = HazardView(
        record_id="rec_x", hazard_no="HZ-003",
        description="长" * 60, department="设备工程部",
    )
    plan = [(v, "责任人", _person("张三"))]
    cell = progress_dunning._build_dunning_cell([v], plan, plan, [], _stats(sent=1))
    assert "…" in cell.detail
    assert "长" * 60 not in cell.detail


async def test_send_dynamic_upserts_digest_cell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v1, v2 = _view("HZ-001"), _view("HZ-002")
    plan = [
        (v1, "责任人", _person("张三")),
        (v1, "分管安全员", _person("李四")),
        (v2, "责任人", _person("李四")),
    ]

    async def fake_overview() -> tuple[list[HazardView], int]:
        return [v1, v2], 42

    async def fake_resolve(views: list[HazardView]) -> list[Any]:
        return plan

    async def fake_mention(names: Any) -> dict[str, str]:
        return {n: f"ou_{n}" for n in names}

    def fake_card(view: Any, mention_id: str) -> tuple[str, list[dict[str, Any]]]:
        return "content", []

    async def fake_send(**kw: Any) -> bool:
        return True

    captured: list[tuple[Any, str, DigestCell]] = []

    async def fake_upsert(
        report_date: Any, key: str, cell: DigestCell, **kw: Any,
    ) -> bool:
        captured.append((report_date, key, cell))
        return True

    monkeypatch.setattr(progress_dunning, "find_dunning_overview", fake_overview)
    monkeypatch.setattr(progress_dunning, "resolve_dunning_recipients", fake_resolve)
    monkeypatch.setattr(mention, "resolve_open_ids", fake_mention)
    monkeypatch.setattr(progress_card, "build_progress_card", fake_card)
    monkeypatch.setattr(notification, "send_user_card", fake_send)
    monkeypatch.setattr(daily_digest, "upsert_daily_digest", fake_upsert)

    stats = await progress_dunning.send_progress_dunning_dynamic()

    assert stats["sent"] == 3
    assert stats["digest_upserted"] is True
    assert len(captured) == 1
    report_date, key, cell = captured[0]
    assert key == "progress_dunning"
    bj_today = (datetime.now(UTC) + timedelta(hours=8)).date()
    assert report_date == bj_today
    assert "已私发对象（2 人）" in cell.detail
    assert "张三" in cell.detail and "李四" in cell.detail


async def test_send_dynamic_no_hazards_still_upserts_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0 命中不发卡，但仍投「今日无需催办」速递格子（有无均报）。"""
    async def fake_overview() -> tuple[list[HazardView], int]:
        return [], 44

    captured: list[tuple[Any, str, DigestCell]] = []

    async def fake_upsert(
        report_date: Any, key: str, cell: DigestCell, **kw: Any,
    ) -> bool:
        captured.append((report_date, key, cell))
        return True

    monkeypatch.setattr(progress_dunning, "find_dunning_overview", fake_overview)
    monkeypatch.setattr(daily_digest, "upsert_daily_digest", fake_upsert)

    stats = await progress_dunning.send_progress_dunning_dynamic()

    assert stats["total"] == 0
    assert stats["candidates"] == 44
    assert stats["digest_upserted"] is True
    assert len(captured) == 1
    report_date, key, cell = captured[0]
    assert key == "progress_dunning"
    bj_today = (datetime.now(UTC) + timedelta(hours=8)).date()
    assert report_date == bj_today
    assert cell.tag_color == "orange"
    assert cell.tag_text == "进展催办"
    assert "督办中隐患 **44** 条" in cell.stats
    assert "未更新进展 **0** 项" in cell.stats
    assert "无需催办" in cell.zone
    assert "已私发对象" not in cell.detail
    assert "催办明细" not in cell.detail


def test_build_cell_zero_hits_with_candidates() -> None:
    cell = progress_dunning._build_dunning_cell(
        [], [], [], [], _stats(total=0, marked=0, candidates=44),
    )
    assert cell.tag_text == "进展催办"
    assert cell.stats == "督办中隐患 **44** 条 ｜ 未更新进展 **0** 项"
    assert cell.zone == "各督办隐患整改进展均正常更新，今日无需催办"
    assert "未发现「未更新进展」隐患" in cell.detail


def test_build_cell_zero_hits_without_candidates() -> None:
    cell = progress_dunning._build_dunning_cell(
        [], [], [], [], _stats(total=0, marked=0, candidates=0),
    )
    assert cell.stats == "督办中隐患 **0** 条 ｜ 未更新进展 **0** 项"
    assert "无督办中隐患" in cell.zone
    assert "无督办中（红色/一般预警且未关闭）隐患" in cell.detail
