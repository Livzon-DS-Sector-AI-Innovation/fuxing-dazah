"""特殊作业速递卡构建器测试（纯结构验证，不依赖 DB / 网络）。

速递卡是日报推送的表现层改造：同一份 records/stats/ai_analysis 输入下，
验证卡片 JSON 结构、图标降级、超限回退与开关语义。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.modules.safety.feishu.special_op_digest import build_special_op_digest
from app.modules.safety.schemas.special_op_daily import AIDailyAnalysisResult
from app.modules.safety.service.special_op_direct import config as direct_config

REPORT_DATE = date(2026, 9, 15)


@dataclass
class _Rec:
    """SpecialOpRecord 协议的最小满足实现（只需日报渲染用到的字段）。"""

    operation_type: str = "hot_work"
    department: str | None = "炼油一部"
    location: str | None = "常压装置区"
    work_description: str | None = "管廊管线更换动火作业"
    daily_risk_level: str | None = "high"
    daily_risk_reason: str | None = "动火作业叠加高处"
    contractor_name: str | None = "某施工单位"
    personnel_type: str | None = "非公司人员"
    planned_start_time: datetime | None = datetime(2026, 9, 15, 1, 0, tzinfo=UTC)
    planned_end_time: datetime | None = datetime(2026, 9, 15, 3, 0, tzinfo=UTC)
    work_duration_hours: float | None = 2.0
    submitted_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime(2026, 9, 14, 23, 0, tzinfo=UTC)
    )
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    feishu_record_id: str | None = "rec001"
    source: str = "bitable"
    other_operation_types: list[Any] | None = None
    inferred_operation_types: list[Any] | None = None
    is_excluded: bool = False
    exclusion_reason: str | None = None
    daily_report_date: date | None = REPORT_DATE
    risk_level: str | None = None
    fire_work_method: str | None = None
    height_work_method: str | None = None
    work_height: float | None = None
    lifting_weight: float | None = None
    is_weekend_holiday: str | None = None
    is_national_holiday: str | None = None


FULL_MARKDOWN = (
    "📋 【特殊作业日报】 2026年09月15日\n"
    "\n📊 作业概况\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "• 今日计划作业: 4 项\n"
)

STATS = {
    "total": 4,
    "effective_total": 4,
    "high": 2,
    "medium": 1,
    "low": 1,
    "excluded": 0,
}


def _sample_reports() -> list[_Rec]:
    return [
        _Rec(operation_type="hot_work", daily_risk_level="high"),
        _Rec(
            operation_type="confined_space",
            department="发酵工程部",
            location="发酵车间",
            work_description="反应釜内清釜作业",
            daily_risk_level="high",
            contractor_name=None,
        ),
        _Rec(
            operation_type="height_work",
            department="机修部",
            work_description="脚手架搭建",
            daily_risk_level="medium",
            contractor_name=None,
        ),
        _Rec(
            operation_type="temporary_electricity",
            department="仪表车间",
            work_description="临时配电",
            daily_risk_level="low",
            contractor_name=None,
        ),
    ]


async def _ok_uploader(op_type: str | None) -> str | None:
    return "img_demo"


async def test_build_digest_basic_structure() -> None:
    built = await build_special_op_digest(
        REPORT_DATE, "today", _sample_reports(), STATS, None, FULL_MARKDOWN,
        icon_uploader=_ok_uploader,
    )
    assert built is not None
    title, greeting, elements = built.title, built.content, built.elements

    # 头部样式：蓝色模板 + 统计副标题
    assert built.header_template == "blue"
    assert built.subtitle == "今日计划 4 项 ｜ 高 2 · 中 1 · 低 1"
    assert built.header_tags is None

    # 标题与问候语
    assert title == "📋 特殊作业速递 | 2026-09-15"
    assert "今日计划特殊作业 **4** 项" in greeting
    assert "高风险 **2** 项" in greeting
    assert "动火作业 1 · 受限空间 1 · 高处作业 1 · 临时用电 1" in greeting

    # 高风险条目卡：2 张 column_set，左文右图（按 _sort_key 稳定排序）
    column_sets = [e for e in elements if e["tag"] == "column_set"]
    assert len(column_sets) == 2
    all_item_md = [c["elements"][0]["content"] for cs in column_sets for c in cs["columns"][:1]]
    assert any("<text_tag color='red'>高风险</text_tag>" in c for c in all_item_md)
    assert any("<text_tag color='orange'>动火作业</text_tag>" in c for c in all_item_md)
    assert any("<text_tag color='indigo'>受限空间</text_tag>" in c for c in all_item_md)
    assert any("**炼油一部｜常压装置区**" in c for c in all_item_md)
    first = column_sets[0]
    assert first["background_style"] == "grey"
    img_col = first["columns"][1]
    assert img_col["elements"][0]["img_key"] == "img_demo"

    # 中/低风险聚合条目
    contents = [
        e["content"] for e in elements
        if e["tag"] == "markdown"
    ]
    assert any("常规作业" in c and "**1 项**" in c for c in contents)
    assert any("低风险" in c and "**1 项**" in c for c in contents)

    # 末位折叠面板：默认收起，收纳去掉标题行的旧长卡全文
    panel = elements[-1]
    assert panel["tag"] == "collapsible_panel"
    assert panel["expanded"] is False
    panel_md = panel["elements"][0]["content"]
    assert "作业概况" in panel_md
    assert not panel_md.startswith("📋")


async def test_icon_failure_degrades_to_no_image() -> None:
    async def _fail_uploader(op_type: str | None) -> str | None:
        return None

    built = await build_special_op_digest(
        REPORT_DATE, "today", _sample_reports()[:2], STATS, None, FULL_MARKDOWN,
        icon_uploader=_fail_uploader,
    )
    assert built is not None
    elements = built.elements
    column_sets = [e for e in elements if e["tag"] == "column_set"]
    assert len(column_sets) == 2
    for cs in column_sets:
        assert len(cs["columns"]) == 1  # 只剩文字列
        assert all(c["elements"][0]["tag"] == "markdown" for c in cs["columns"])


async def test_unknown_type_uses_fallback_icon() -> None:
    seen: list[str | None] = []

    async def _spy_uploader(op_type: str | None) -> str | None:
        seen.append(op_type)
        return "img_fb"

    rec = _Rec(operation_type="unknown_type", daily_risk_level="high")
    built = await build_special_op_digest(
        REPORT_DATE, "today", [rec], STATS, None, FULL_MARKDOWN,
        icon_uploader=_spy_uploader,
    )
    assert built is not None
    assert seen == ["unknown_type"]  # 未知类型原样传给图标层，由其回退 fallback 素材


async def test_oversize_falls_back_to_none() -> None:
    huge_markdown = FULL_MARKDOWN + "x" * 30_000
    built = await build_special_op_digest(
        REPORT_DATE, "today", _sample_reports(), STATS, None, huge_markdown,
        icon_uploader=_ok_uploader,
    )
    assert built is None


async def test_tomorrow_mode_not_supported() -> None:
    built = await build_special_op_digest(
        REPORT_DATE, "tomorrow", _sample_reports(), STATS, None, FULL_MARKDOWN,
        icon_uploader=_ok_uploader,
    )
    assert built is None


async def test_afternoon_header_tag_and_new_ops() -> None:
    afternoon_rec = _Rec(submitted_at=datetime(2026, 9, 15, 6, 0, tzinfo=UTC))
    reports = [r for r in _sample_reports()[:2]] + [afternoon_rec]
    built = await build_special_op_digest(
        REPORT_DATE, "afternoon", reports, STATS, None, FULL_MARKDOWN,
        icon_uploader=_ok_uploader,
    )
    assert built is not None
    _, _, elements = built.title, built.content, built.elements
    # 午后推送带「午后更新」头部标签
    assert built.header_tags == [{
        "tag": "text_tag",
        "text": {"tag": "plain_text", "content": "午后更新"},
        "color": "orange",
    }]
    contents = [e["content"] for e in elements if e["tag"] == "markdown"]
    assert any("新增计划外" in c and "**1 项**" in c for c in contents)


async def test_ai_tips_preferred_over_rule_tips() -> None:
    ai = AIDailyAnalysisResult(
        enhanced_tips=["1. 动火作业落实专人监火", "2. 受限空间先通风再检测"]
    )
    built = await build_special_op_digest(
        REPORT_DATE, "today", _sample_reports(), STATS, ai, FULL_MARKDOWN,
        icon_uploader=_ok_uploader,
    )
    assert built is not None
    contents = [e["content"] for e in built.elements if e["tag"] == "markdown"]
    tips_md = next(c for c in contents if "安全提示" in c)
    assert "动火作业落实专人监火" in tips_md
    assert not tips_md.startswith("1. ")  # 前导编号已剥离


async def test_more_than_max_high_items_truncated() -> None:
    many = [
        _Rec(operation_type="hot_work", feishu_record_id=f"rec{i:03d}")
        for i in range(8)
    ]
    stats = {**STATS, "high": 8}
    built = await build_special_op_digest(
        REPORT_DATE, "today", many, stats, None, FULL_MARKDOWN,
        icon_uploader=_ok_uploader,
    )
    assert built is not None
    column_sets = [e for e in built.elements if e["tag"] == "column_set"]
    assert len(column_sets) == 6
    contents = [e["content"] for e in built.elements if e["tag"] == "markdown"]
    assert any("其余 2 项高风险" in c for c in contents)


def test_digest_flag_default_on_and_kill_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED", raising=False)
    assert direct_config.digest_card_enabled() is True
    monkeypatch.setenv("SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED", "false")
    assert direct_config.digest_card_enabled() is False
