"""作业票审核速递卡构建器测试（纯结构验证，不依赖网络）。"""

from __future__ import annotations

import json
from datetime import datetime

from app.modules.safety.feishu.workticket_digest import build_workticket_digest
from app.modules.safety.workticket_review.parser import WorkTicket
from app.modules.safety.workticket_review.rule_engine import Violation

D = "2026-09-15"


def _ticket(no: str, ttype: str = "hot_work", dept: str = "提炼工程四部") -> WorkTicket:
    return WorkTicket(
        ticket_type=ttype,
        ticket_no=no,
        apply_unit=dept,
        work_site="管廊区",
        work_content="管线更换",
        start_time=datetime(2026, 9, 15, 1, 0),
    )


def _violation(detail: str = "start_time 早于 approve_time，存在倒签") -> Violation:
    return Violation(
        rule_no="TIME_ORDER", rule_name="时间顺序链", detail=detail,
        key_times=["申请 09:00", "开始 08:00"],
    )


STATS = {"total": 14, "reviewed": 12, "violation_count": 2,
         "compliant_count": 11, "data_insufficient": 1}

FULL_MD = "📋 【作业票审核日报】 2026-09-15\n\n📊 审核概要\n• 今日标准 8 类作业票数: 14 项\n"


async def test_basic_structure() -> None:
    tickets = [
        _ticket("DH-20260915-003"),
        _ticket("GC-20260915-007", "height_work", "质量控制部QC/菌种中心"),
        _ticket("SX-20260915-001", "confined_space", "发酵工程部"),
        _ticket("DY-20260915-009", "temporary_electricity", "仪表车间"),
    ]
    violations = {
        "DH-20260915-003": [_violation()],
        "SX-20260915-001": [_violation("数据不足：缺少 gas_analysis 记录")],
    }
    card = build_workticket_digest(D, tickets, violations, STATS, FULL_MD)
    assert card is not None

    assert card.title == "📋 作业票审核速递 | 2026-09-15"
    assert card.header_template == "blue"
    assert card.subtitle == "今日审核 14 票 ｜ 通过 11 · 驳回 2 · 待补 1"
    assert "今日作业票审核 **14** 张" in card.content
    assert "动火作业 1 · 受限空间作业 1 · 高处作业 1 · 临时用电作业 1" in card.content

    column_sets = [e for e in card.elements if e["tag"] == "column_set"]
    assert len(column_sets) == 2  # 1 驳回 + 1 待补
    first_md = column_sets[0]["columns"][0]["elements"][0]["content"]
    assert "<text_tag color='red'>驳回</text_tag>" in first_md
    assert "<text_tag color='orange'>动火作业</text_tag>" in first_md
    assert "**DH-20260915-003**" in first_md
    assert "时间顺序链" in first_md

    # 待补票用黄色标签
    second_md = column_sets[1]["columns"][0]["elements"][0]["content"]
    assert "<text_tag color='yellow'>待补数据</text_tag>" in second_md

    # 通过聚合 + 折叠面板（收纳去标题行的旧长卡）
    contents = [e["content"] for e in card.elements if e["tag"] == "markdown"]
    assert any("<text_tag color='green'>通过</text_tag>" in c and "**2 票**" in c for c in contents)
    panel = card.elements[-1]
    assert panel["tag"] == "collapsible_panel"
    assert panel["expanded"] is False
    panel_md = panel["elements"][0]["content"]
    assert "审核概要" in panel_md
    assert not panel_md.startswith("📋")
    card_json = json.dumps(card.elements, ensure_ascii=False)
    assert '"img"' not in card_json  # 纯文字，不带图片


async def test_unknown_type_fallback_and_type_summary() -> None:
    tickets = [_ticket("XX-001", "unknown_type"), _ticket("DH-002")]
    card = build_workticket_digest(D, tickets, {}, {"total": 2, "compliant_count": 2}, FULL_MD)
    assert card is not None
    contents = [e["content"] for e in card.elements if e["tag"] == "markdown"]
    assert any("通过" in c and "unknown_type ×1" in c for c in contents)


async def test_more_than_max_problem_items_truncated() -> None:
    tickets = [_ticket(f"DH-{i:03d}") for i in range(8)]
    violations = {t.ticket_no: [_violation()] for t in tickets}
    card = build_workticket_digest(
        D, tickets, violations, {"total": 8, "violation_count": 8}, FULL_MD,
    )
    assert card is not None
    column_sets = [e for e in card.elements if e["tag"] == "column_set"]
    assert len(column_sets) == 6
    contents = [e["content"] for e in card.elements if e["tag"] == "markdown"]
    assert any("其余 2 张问题票" in c for c in contents)


async def test_oversize_returns_none() -> None:
    tickets = [_ticket("DH-001")]
    card = build_workticket_digest(
        D, tickets, {}, STATS, FULL_MD + "x" * 30_000,
    )
    assert card is None
