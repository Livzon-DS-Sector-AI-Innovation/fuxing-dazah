"""监护补贴月报私发单测（subsidy_dispatch）。

覆盖：上一自然月计算、DEPT_CONFIG 分管安全员名单、单部门 Excel 构建
（无记录跳过）、开关关闭跳过、三部门端到端私发（mock 拉数/身份/发送）、
调度注册（每月 1 日 08:30 + dom 回归防线）。
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG
from app.modules.safety.scheduler import SCHEDULED_JOBS
from app.modules.safety.service import subsidy_dispatch
from app.modules.safety.service.subsidy_dept_ledgers import LEDGER_SOURCES
from app.modules.safety.service.subsidy_dispatch import (
    build_monthly_excel,
    build_summary_card,
    previous_month,
    run_monthly_subsidy_dispatch,
    subsidy_recipient,
)


def _src(department: str):
    return next(s for s in LEDGER_SOURCES if s.department == department)


# ── 行夹具（四/六部布局各异）───────────────────────────────────────


def _row6(name: str, day: str, period: str) -> dict[str, Any]:
    """六部布局：文本日期+时间段，类型 MultiSelect，无级别列。"""
    return {"fields": {
        "姓名": [{"text": name, "type": "text"}],
        "特殊作业类型": ["动火作业"],
        "作业级别": "一级",
        "作业地点及内容": [{"text": "二期车间更换灯具", "type": "text"}],
        "日期": [{"text": day, "type": "text"}],
        "时间段": [{"text": period, "type": "text"}],
    }}


def _row4(name: str, day: str, period: str) -> dict[str, Any]:
    """四部布局：datetime 日期列 + 监护证类别列。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Shanghai")
    y, m, d = (int(x) for x in day.split("."))
    ms = int(datetime(y, m, d, 0, 0, tzinfo=tz).timestamp() * 1000)
    return {"fields": {
        "姓名": [{"text": name, "type": "text"}],
        "监护证类别": "A证",
        "特殊作业类型": "动火作业",
        "作业级别": "一级",
        "日期": ms,
        "时间段（写全：如8:30-11:00  13:30-17:00）": [{"text": period, "type": "text"}],
        "监护内容（具体到作业位置）": [{"text": "车间一管道打磨", "type": "text"}],
    }}


# ═══════════════════════════════════════════════════════════════════
# 纯函数
# ═══════════════════════════════════════════════════════════════════


def test_previous_month() -> None:
    assert previous_month(date(2026, 11, 1)) == (2026, 10)   # 每月 1 日触发
    assert previous_month(date(2027, 1, 1)) == (2026, 12)    # 跨年
    assert previous_month(date(2026, 10, 26)) == (2026, 9)


def test_subsidy_recipient_override_scoped_to_business() -> None:
    """补贴收件人=业务专属名单优先（四部林锴彬/六部孙长宽），不改全局分管安全员。

    2026-10-26 用户口径：两人只负责补贴业务，DEPARTMENT_CONFIG 的
    safety_officer（四部杨昆/六部陈美丽）保持原样供其他消费方使用。
    """
    assert subsidy_recipient("提炼工程四部") == "林锴彬"
    assert subsidy_recipient("提炼工程六部") == "孙长宽"
    # 未覆盖部门回退 DEPARTMENT_CONFIG safety_officer
    assert subsidy_recipient("提炼工程五部") == "蔡嘉旺"
    assert subsidy_recipient("不存在的部门") == ""
    # 全局名单未被补贴业务改写（过度修改回归防线）
    assert DEPARTMENT_CONFIG["提炼工程四部"]["safety_officer"] == "杨昆"
    assert DEPARTMENT_CONFIG["提炼工程六部"]["safety_officer"] == "陈美丽"


def test_build_monthly_excel_and_empty_skip() -> None:
    src = _src("提炼工程六部")
    rows = [
        _row6("池守城", "2026.09.10", "09:10-17:10"),
        _row6("彭飞琼", "2026.09.10", "08：35-18：30"),
    ]
    built = build_monthly_excel(rows, src, 2026, 9)
    assert built is not None
    excel_bytes, file_name, summary = built
    assert file_name == "提炼工程六部 2026年9月 监护补贴统计.xlsx"
    assert excel_bytes[:2] == b"PK"  # xlsx zip 头
    assert summary["matched"] == 2
    assert summary["guardians"] == 2
    assert summary["amount"] > 0
    assert summary["unmatched_people"] == 2  # 六部无级别列 → 全员待核对

    # 无目标月记录 → None（跳过不空发）
    assert build_monthly_excel(rows, src, 2026, 8) is None
    assert build_monthly_excel([], src, 2026, 9) is None

    title, content = build_summary_card(src, 2026, 9, summary)
    assert "提炼工程六部" in title
    assert "2026年9月" in content
    assert "待核对 2 条" in content


# ═══════════════════════════════════════════════════════════════════
# 端到端（mock 拉数 / 身份 / 发送）
# ═══════════════════════════════════════════════════════════════════


def _patch_pipeline(monkeypatch: pytest.MonkeyPatch, *, rows_by_dept: dict[str, list]):
    """替身：台账拉取 + open_id 解析 + 发送；返回发送记录。"""
    async def fake_fetch(source: Any) -> list[dict[str, Any]]:
        return rows_by_dept.get(source.department, [])

    async def fake_resolve(names: Any) -> dict[str, str]:
        return {n: f"on_{n}" for n in names}

    sent_cards: list[tuple[str, str]] = []
    sent_files: list[tuple[str, bytes, str]] = []

    async def fake_card(open_id: str, title: str, content: str, **kw: Any) -> str:
        sent_cards.append((open_id, title))
        return "om_ok"

    async def fake_file(uid: str, data: bytes, name: str, **kw: Any) -> bool:
        sent_files.append((uid, data, name))
        return True

    monkeypatch.setattr(subsidy_dispatch, "fetch_ledger_rows", fake_fetch)
    monkeypatch.setattr(subsidy_dispatch, "resolve_open_ids", fake_resolve)
    monkeypatch.setattr(subsidy_dispatch, "send_user_card", fake_card)
    monkeypatch.setattr(subsidy_dispatch, "send_file_to_chat", fake_file)
    return sent_cards, sent_files


@pytest.mark.asyncio
async def test_dispatch_sends_per_dept_and_skips_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """四部/六部有记录 → 各私发分管安全员；五部空 → 跳过；七等其他部门不发。"""
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "true")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={
        "提炼工程四部": [_row4("吴家达", "2026.09.03", "09:15-17:10")],
        "提炼工程五部": [],  # 当月无记录
        "提炼工程六部": [_row6("池守城", "2026.09.10", "09:10-17:10")],
    })

    stats = await run_monthly_subsidy_dispatch(year=2026, month=9)

    assert stats == {"sent": 2, "skipped_empty": 1, "errors": 0, "unresolved": 0}
    # 收件人 = 补贴业务专属名单（open_id 链）
    assert {uid for uid, _ in cards} == {"on_林锴彬", "on_孙长宽"}
    assert {name for _, _, name in files} == {
        "提炼工程四部 2026年9月 监护补贴统计.xlsx",
        "提炼工程六部 2026年9月 监护补贴统计.xlsx",
    }
    # 卡先于文件、同部门同收件人
    assert len(cards) == 2 and len(files) == 2


@pytest.mark.asyncio
async def test_dispatch_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "false")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={})  # 不应被触达

    stats = await run_monthly_subsidy_dispatch(year=2026, month=9)

    assert stats is None
    assert cards == [] and files == []


@pytest.mark.asyncio
async def test_dispatch_unresolved_officer_skips_dept(monkeypatch: pytest.MonkeyPatch) -> None:
    """安全员未解析到 open_id → unresolved 计数，文件不发。"""
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "true")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={
        "提炼工程六部": [_row6("池守城", "2026.09.10", "09:10-17:10")],
    })

    async def no_resolve(names: Any) -> dict[str, str]:
        return {}

    monkeypatch.setattr(subsidy_dispatch, "resolve_open_ids", no_resolve)

    stats = await run_monthly_subsidy_dispatch(year=2026, month=9)

    assert stats == {"sent": 0, "skipped_empty": 2, "errors": 0, "unresolved": 1}
    assert cards == [] and files == []


@pytest.mark.asyncio
async def test_dispatch_file_send_failure_counts_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """文件发送失败 → errors 计数不抛（避免补发窗口重试造成重复收件）。"""
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "true")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={
        "提炼工程四部": [_row4("吴家达", "2026.09.03", "09:15-17:10")],
    })

    async def fail_file(uid: str, data: bytes, name: str, **kw: Any) -> bool:
        return False

    monkeypatch.setattr(subsidy_dispatch, "send_file_to_chat", fail_file)

    stats = await run_monthly_subsidy_dispatch(year=2026, month=9)

    assert stats == {"sent": 0, "skipped_empty": 2, "errors": 1, "unresolved": 0}
    assert len(cards) == 1  # 摘要卡已发（失败仅文件）


# ═══════════════════════════════════════════════════════════════════
# 调度注册（dom 回归防线，见 test_scheduler_dom 背景）
# ═══════════════════════════════════════════════════════════════════


def test_scheduler_job_registered() -> None:
    job = next(j for j in SCHEDULED_JOBS if j["name"] == "监护补贴月报")
    assert job["hour"] == 8 and job["minute"] == 30
    assert job["dom"] == 1
    assert job["target_type"] == "person"
    assert job["retry_until_hour"] == 23 and job["retry_until_minute"] == 30
    assert "SAFETY_SUBSIDY_MONTHLY_DM_ENABLED" in job["description"]
