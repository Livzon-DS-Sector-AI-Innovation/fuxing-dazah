"""监护补贴月报私发单测（subsidy_dispatch，2026-11-02 全部门扩面版）。

覆盖：上一自然月计算、收件人名单（多人/回退/不改全局防线）、open_id 三层
解析链、按月分表路由（match_month_table 纯函数）、单部门 Excel 构建（台账/
平台两路 + 无记录跳过）、开关关闭跳过、端到端私发（mock 拉数/身份/发送，
含多收件人与平台路线）、调度注册（每月 1 日 08:30 + dom 回归防线）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG
from app.modules.safety.scheduler import SCHEDULED_JOBS
from app.modules.safety.service import subsidy_dispatch
from app.modules.safety.service.subsidy_dept_ledgers import (
    LEDGER_SOURCES,
    match_month_table,
)
from app.modules.safety.service.subsidy_dispatch import (
    SOURCE_PLATFORM,
    build_monthly_excel,
    build_platform_payloads,
    build_summary_card,
    previous_month,
    resolve_recipient_open_ids,
    run_monthly_subsidy_dispatch,
    subsidy_recipients,
)

TZ = ZoneInfo("Asia/Shanghai")


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
    y, m, d = (int(x) for x in day.split("."))
    ms = int(datetime(y, m, d, 0, 0, tzinfo=TZ).timestamp() * 1000)
    return {"fields": {
        "姓名": [{"text": name, "type": "text"}],
        "监护证类别": "A证",
        "特殊作业类型": "动火作业",
        "作业级别": "一级",
        "日期": ms,
        "时间段（写全：如8:30-11:00  13:30-17:00）": [{"text": period, "type": "text"}],
        "监护内容（具体到作业位置）": [{"text": "车间一管道打磨", "type": "text"}],
    }}


def _ticket(
    guardian: str, apply_unit: str, day: str,
    ticket_no: str = "T-001", ticket_type: str = "hot_work",
) -> Any:
    """平台票夹具（WorkTicket 最小可用形态）。"""
    from app.modules.safety.workticket_review.parser import WorkTicket

    y, m, d = (int(x) for x in day.split("."))
    return WorkTicket(
        ticket_type=ticket_type,
        ticket_no=ticket_no,
        level="一级",
        start_time=datetime(y, m, d, 9, 0, tzinfo=TZ),
        end_time=datetime(y, m, d, 17, 0, tzinfo=TZ),
        guardian=guardian,
        apply_unit=apply_unit,
    )


# ═══════════════════════════════════════════════════════════════════
# 纯函数
# ═══════════════════════════════════════════════════════════════════


def test_previous_month() -> None:
    assert previous_month(date(2026, 11, 1)) == (2026, 10)   # 每月 1 日触发
    assert previous_month(date(2027, 1, 1)) == (2026, 12)    # 跨年
    assert previous_month(date(2026, 10, 26)) == (2026, 9)


def test_subsidy_recipients_multi_and_fallback() -> None:
    """收件人=业务专属名单优先（五部两人），未覆盖回退 safety_officer，不改全局。

    2026-10-26 拍板四部林锴彬/六部孙长宽；2026-11-02 五部增陈卫强（蔡嘉旺保留）。
    DEPARTMENT_CONFIG 的 safety_officer（四部杨昆/六部陈美丽）保持原样供其他消费方。
    """
    assert subsidy_recipients("提炼工程四部") == ("林锴彬",)
    assert subsidy_recipients("提炼工程六部") == ("孙长宽",)
    assert subsidy_recipients("提炼工程五部") == ("蔡嘉旺", "陈卫强")
    # 未覆盖部门回退 DEPARTMENT_CONFIG safety_officer
    assert subsidy_recipients("发酵工程部") == ("邓宇",)
    # 检测组不在 DEPARTMENT_CONFIG → 空元组（发送阶段计 unresolved）
    assert subsidy_recipients("检测组") == ()
    assert subsidy_recipients("不存在的部门") == ()
    # 全局名单未被补贴业务改写（过度修改回归防线）
    assert DEPARTMENT_CONFIG["提炼工程四部"]["safety_officer"] == "杨昆"
    assert DEPARTMENT_CONFIG["提炼工程六部"]["safety_officer"] == "陈美丽"


@pytest.mark.asyncio
async def test_resolve_recipient_open_ids_three_layers(monkeypatch: pytest.MonkeyPatch) -> None:
    """三层链：静态映射 → 本地回退表 → resolve_open_ids；全失败不出现在结果。"""
    async def fake_identity(names: Any) -> dict[str, str]:
        return {n: f"on_{n}" for n in names if n == "虚构人"}

    monkeypatch.setattr(subsidy_dispatch, "resolve_open_ids", fake_identity)

    out = await resolve_recipient_open_ids({"林锴彬", "陈卫强", "虚构人", "查无此人"})
    # 林锴彬：静态映射命中（真实 bitable_open_ids.json）
    assert out["林锴彬"].startswith("ou_")
    # 陈卫强：本地回退表命中
    assert out["陈卫强"] == subsidy_dispatch._SUBSIDY_OPEN_ID_FALLBACK["陈卫强"]
    # 虚构人：两层未中 → identity 链
    assert out["虚构人"] == "on_虚构人"
    # 查无此人：三层全空
    assert "查无此人" not in out


def test_match_month_table_year_anchored_and_legacy() -> None:
    """按月分表路由：年份锚定优先，无年份旧表名兜底，未命中 None。"""
    items = [
        ("tblA", "2026.09月监护作业表"),
        ("tblB", "2026.10月监护作业表"),
        ("tblC", "2026年09月份"),
        ("tblD", "2026年10月份"),
        ("tblE", "10月监护作业"),          # 2024 遗留（无年份）
        ("tblF", "2025.10月监护作业 副本"),
        ("tblG", "数据表"),
    ]
    assert match_month_table(items, 2026, 10) == "tblB"   # 四部式
    assert match_month_table(items, 2026, 9) == "tblA"
    assert match_month_table(items, 2025, 10) == "tblF"
    assert match_month_table([("tblE", "10月监护作业")], 2024, 10) == "tblE"  # 兜底
    assert match_month_table(items, 2024, 10) == "tblE"
    assert match_month_table(items, 2026, 11) is None
    # 六部 2025 单数月无补零写法
    assert match_month_table([("tblH", "2025年9月份")], 2025, 9) == "tblH"


def test_monthly_sources_flagged() -> None:
    """四/六部按月分表标记为 monthly_tables，五部单表不标记。"""
    flags = {s.department: s.monthly_tables for s in LEDGER_SOURCES}
    assert flags == {"提炼工程四部": True, "提炼工程五部": False, "提炼工程六部": True}


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

    title, content = build_summary_card("提炼工程六部", 2026, 9, summary)
    assert "提炼工程六部" in title
    assert "2026年9月" in content
    assert "台账计入" in content
    assert "待核对 2 条" in content

    # 平台票话术分支
    title2, content2 = build_summary_card(
        "发酵工程部", 2026, 10, summary, source=SOURCE_PLATFORM
    )
    assert "平台作业票" in content2
    assert "作业票计入" in content2


# ═══════════════════════════════════════════════════════════════════
# 平台票路线（build_platform_payloads）
# ═══════════════════════════════════════════════════════════════════


def _patch_platform(monkeypatch: pytest.MonkeyPatch, tickets: list[Any]) -> None:
    """替身：平台拉票 + 证书/部门映射（identity 兜底语义：无映射回退申请单位）。"""
    async def fake_fetch(year: int, month: int) -> list[Any]:
        return tickets

    async def fake_cert(db: Any) -> dict[str, str]:
        return {"张三": "A证"}

    async def fake_gd(db: Any) -> dict[str, str]:
        return {}  # 全员回退申请单位归集

    import contextlib

    @contextlib.asynccontextmanager
    async def fake_session():
        yield None

    from app.core import database as core_db

    monkeypatch.setattr(subsidy_dispatch, "_fetch_platform_tickets", fake_fetch)
    monkeypatch.setattr(subsidy_dispatch, "build_certificate_map", fake_cert)
    monkeypatch.setattr(subsidy_dispatch, "build_guardian_department_map", fake_gd)
    monkeypatch.setattr(core_db, "async_session_factory", fake_session)


@pytest.mark.asyncio
async def test_platform_payloads_exclude_ledger_depts(monkeypatch: pytest.MonkeyPatch) -> None:
    """平台路线逐部门出 Excel；台账三部门（含别名归集）排除防双算。"""
    _patch_platform(monkeypatch, tickets=[
        _ticket("张三", "发酵工程部", "2026.10.05", ticket_no="T-1"),
        _ticket("李四", "提炼工程一部", "2026.10.06", ticket_no="T-2"),
        _ticket("王五", "提炼工程四部", "2026.10.07", ticket_no="T-3"),  # 台账部门 → 排除
        _ticket("赵六", "提炼工程二部", "2026.09.01", ticket_no="T-4"),  # 非目标月 → 空跳
    ])

    payloads, skipped = await build_platform_payloads(2026, 10)

    depts = [p.department for p in payloads]
    assert depts == ["发酵工程部", "提炼工程一部"]  # sorted（码序：发<提）；四部被排除
    assert skipped == 1  # 提炼二部 9 月票 → 10 月空跳
    assert all(p.source == SOURCE_PLATFORM for p in payloads)
    assert all(p.file_name.endswith(".xlsx") for p in payloads)
    by_dept = {p.department: p.summary for p in payloads}
    assert by_dept["发酵工程部"]["matched"] == 1
    assert by_dept["发酵工程部"]["amount"] > 0
    # 无证书的李四 → 待核对按 A 证暂计
    assert by_dept["提炼工程一部"]["unmatched_people"] == 1


# ═══════════════════════════════════════════════════════════════════
# 端到端（mock 拉数 / 身份 / 发送）
# ═══════════════════════════════════════════════════════════════════


def _patch_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rows_by_dept: dict[str, list],
    platform_payloads: list[Any] | None = None,
    platform_skipped: int = 0,
):
    """替身：台账拉取 + 平台路线 + open_id 解析 + 发送；返回发送记录。"""
    async def fake_fetch(source: Any, year: int | None = None, month: int | None = None):
        return rows_by_dept.get(source.department, [])

    async def fake_platform(year: int, month: int) -> tuple[list[Any], int]:
        return platform_payloads or [], platform_skipped

    async def fake_resolve(names: set[str]) -> dict[str, str]:
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
    monkeypatch.setattr(subsidy_dispatch, "build_platform_payloads", fake_platform)
    monkeypatch.setattr(subsidy_dispatch, "resolve_recipient_open_ids", fake_resolve)
    monkeypatch.setattr(subsidy_dispatch, "send_user_card", fake_card)
    monkeypatch.setattr(subsidy_dispatch, "send_file_to_chat", fake_file)
    return sent_cards, sent_files


@pytest.mark.asyncio
async def test_dispatch_multi_recipient_and_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """五部有记录 → 蔡嘉旺+陈卫强两人各收一份；平台部门发 safety_officer。"""
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "true")
    platform = [subsidy_dispatch.DeptPayload(
        department="发酵工程部", source=SOURCE_PLATFORM,
        excel_bytes=b"PKfake", file_name="发酵工程部 2026年10月 监护补贴统计.xlsx",
        summary={"matched": 3, "guardians": 2, "amount": 300.0,
                 "unmatched": 0, "skipped": 0, "unmatched_people": 0},
    )]
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={
        "提炼工程五部": [],  # 台账当月无记录
    }, platform_payloads=platform, platform_skipped=2)

    stats = await run_monthly_subsidy_dispatch(year=2026, month=10)

    # skipped_empty = 台账三部门全空(3) + 平台空跳(2)
    assert stats == {"sent": 1, "skipped_empty": 5, "errors": 0, "unresolved": 0}
    assert {uid for uid, _ in cards} == {"on_邓宇"}
    assert len(files) == 1

    # 五部台账有记录 → 两人各收（多收件人路径）
    from app.modules.safety.service.subsidy_dispatch import SOURCE_LEDGER
    platform2 = []
    cards2, files2 = _patch_pipeline(monkeypatch, rows_by_dept={
        "提炼工程五部": [  # start_end 布局：五部行夹具
            {"fields": {
                "监护人": [{"id": "ou_g", "name": "陈卫强"}],
                "监护人级别": "A证",
                "特殊作业类型": "动火作业",
                "作业级别": "一级",
                "开始时间": int(datetime(2026, 10, 5, 9, 0, tzinfo=TZ).timestamp() * 1000),
                "结束时间": int(datetime(2026, 10, 5, 17, 0, tzinfo=TZ).timestamp() * 1000),
                "作业地点+作业内容": "三号罐区动火",
            }},
        ],
    }, platform_payloads=platform2)
    stats2 = await run_monthly_subsidy_dispatch(year=2026, month=10)
    assert stats2 == {"sent": 1, "skipped_empty": 2, "errors": 0, "unresolved": 0}
    assert {uid for uid, _ in cards2} == {"on_蔡嘉旺", "on_陈卫强"}
    assert len(files2) == 2
    assert all(fn.startswith("提炼工程五部") for _, _, fn in files2)
    assert SOURCE_LEDGER == "dept_ledger"


@pytest.mark.asyncio
async def test_dispatch_disabled_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "false")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={})  # 不应被触达

    stats = await run_monthly_subsidy_dispatch(year=2026, month=9)

    assert stats is None
    assert cards == [] and files == []


@pytest.mark.asyncio
async def test_dispatch_unresolved_recipient_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """收件人未解析到 open_id → 该收件人跳过；部门至少一人未解析计 unresolved。"""
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "true")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={
        "提炼工程六部": [_row6("池守城", "2026.09.10", "09:10-17:10")],
    })

    async def no_resolve(names: set[str]) -> dict[str, str]:
        return {}

    monkeypatch.setattr(subsidy_dispatch, "resolve_recipient_open_ids", no_resolve)

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


@pytest.mark.asyncio
async def test_dispatch_all_empty_no_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """台账与平台两路全空 → sent=0 不发任何卡/文件。"""
    monkeypatch.setenv("SAFETY_SUBSIDY_MONTHLY_DM_ENABLED", "true")
    cards, files = _patch_pipeline(monkeypatch, rows_by_dept={}, platform_skipped=5)

    stats = await run_monthly_subsidy_dispatch(year=2026, month=9)

    # skipped_empty = 台账三部门(3) + 平台(5)
    assert stats == {"sent": 0, "skipped_empty": 8, "errors": 0, "unresolved": 0}
    assert cards == [] and files == []


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
    assert "全部门" in job["description"]
