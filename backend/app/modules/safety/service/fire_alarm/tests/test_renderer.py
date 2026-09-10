"""消防报警日报/周报 — Markdown 渲染纯函数单测（无 DB / 无环境依赖）。

覆盖：日报渲染结构（标题/统计/明细/整改提醒）、AI 汇总块可选、_at @提及与纯文本兜底；
周报渲染结构（标题/周起止/统计/重复问题/AI 周级分析/整改提醒）、未分析记录显示。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmWeeklyAgg,
)
from app.modules.safety.service.fire_alarm.renderer import (
    DIVIDER,
    _at,
    render_daily_report,
    render_weekly_report,
)

TARGET_DATE = date(2026, 3, 12)
WEEK_START = date(2026, 3, 9)
WEEK_END = date(2026, 3, 15)


def make_record(**kw) -> MagicMock:
    """构造最小 FireAlarmRecord 替身（仅暴露渲染用到的属性）。"""
    r = MagicMock()
    r.alarm_time = kw.get("alarm_time", datetime(2026, 3, 12, 2, 0, tzinfo=UTC))
    r.alarm_type = kw.get("alarm_type", "火灾报警")
    r.alarm_nature = kw.get("alarm_nature", "误报")
    r.ai_dimension = kw.get("ai_dimension", "equipment")
    r.department = kw.get("department", "动力车间")
    r.building = kw.get("building", "1号装置")
    r.location = kw.get("location", "压缩机房")
    r.cause_description = kw.get("cause_description", "传感器老化误触发")
    r.ai_reason_analysis = kw.get("reason", "传感器老化导致误报")
    r.ai_rectification_direction = kw.get("direction", "更换传感器并定期校验")
    r.ai_analyzed_at = kw.get("analyzed_at", datetime(2026, 3, 12, 3, 0, tzinfo=UTC))
    return r


def make_agg(records, **kw) -> FireAlarmDailyAgg:
    return FireAlarmDailyAgg(
        target_date=TARGET_DATE,
        records=records,
        total=len(records),
        nature_distribution=kw.get("nature", {"误报": 2}),
        type_distribution=kw.get("types", {"火灾报警": 2}),
        department_distribution=kw.get("depts", {"动力车间": 2}),
        dept_leader_names=kw.get("leaders", {"动力车间": "张三"}),
    )


class TestAt:
    def test_with_open_id(self):
        assert _at("张三", {"张三": "ou_zhangsan"}) == '<at id=ou_zhangsan></at>'

    def test_plain_text_when_no_open_id(self):
        assert _at("张三", {}) == "张三"
        assert _at("张三", {"李四": "ou_lisi"}) == "张三"

    def test_empty_name_returns_pending(self):
        assert _at("", {"张三": "ou"}) == "待维护"
        assert _at(None, {}) == "待维护"


class TestRenderDailyReport:
    def test_structure_with_ai_summary(self):
        agg = make_agg([make_record()])
        md = render_daily_report(
            agg,
            {"张三": "ou_zhangsan"},
            ai_summary={
                "summary": "当日报警集中于动力车间设备设施类误报。",
                "key_issues": ["传感器类设备老化是主要诱因"],
                "rectification_suggestions": ["加强传感器巡检"],
            },
        )
        assert "🔥 **消防报警日报**" in md
        assert f"🔥 **消防报警日报** · {TARGET_DATE.isoformat()}" in md
        assert "**📊 当日报警统计**" in md
        assert "报警总数：**1 起**" in md
        # 明细按部门分组（部门标题 @负责人）
        assert "**动力车间**" in md
        # AI 维度前缀（英文枚举 → 中文）
        assert "**设备设施**" in md
        # 明细字段：报警原因/原因分析(AI)/整改建议 + 查看记录
        assert "压缩机房" in md
        assert "① **报警原因**" in md
        assert "② **原因分析（AI）**" in md
        assert "传感器老化导致误报" in md
        assert "③ **整改建议**" in md
        assert "更换传感器并定期校验" in md
        # AI 汇总分析已删除（需求 5）
        assert "🧠 **AI 汇总分析**" not in md
        # 整改提醒已删除，改为明细内呈现
        assert "**⚠️ 整改提醒**" not in md
        assert '<at id=ou_zhangsan></at>' in md
        assert DIVIDER in md

    def test_ai_summary_none_omits_block(self):
        md = render_daily_report(make_agg([make_record()]), {}, ai_summary=None)
        assert "🧠 **AI 汇总分析**" not in md
        # 其余结构照常
        assert "**📊 当日报警统计**" in md
        assert "**动力车间**" in md

    def test_at_fallback_plain_text(self):
        md = render_daily_report(make_agg([make_record()]), {}, ai_summary=None)
        assert "**动力车间**" in md
        assert "张三" in md  # 无 open_id → 纯文本
        assert "<at" not in md

    def test_dimension_unknown_and_unanalyzed(self):
        records = [
            make_record(ai_dimension=None, reason=None, direction=None),
            make_record(ai_dimension="weird_value", reason=None, direction=None),
        ]
        md = render_daily_report(make_agg(records), {}, ai_summary=None)
        assert md.count("**未分析**") == 2
        assert "② **原因分析（AI）**" not in md  # 无 AI 分析则省略该行

    def test_empty_records(self):
        md = render_daily_report(make_agg([]), {}, ai_summary=None)
        assert "报警总数：**0 起**" in md

    def test_no_leader_fallback_message(self):
        agg = make_agg([make_record()], leaders={})
        md = render_daily_report(agg, {}, ai_summary=None)
        assert "（无部门负责人信息，请各责任部门自行跟进）" in md


def make_weekly_agg(records, **kw) -> FireAlarmWeeklyAgg:
    return FireAlarmWeeklyAgg(
        week_start=WEEK_START,
        week_end=WEEK_END,
        records=records,
        total=len(records),
        nature_distribution=kw.get("nature", {"误报": 2}),
        type_distribution=kw.get("types", {"火灾报警": 2}),
        department_distribution=kw.get("depts", {"动力车间": 2}),
        dept_leader_names=kw.get("leaders", {"动力车间": "张三"}),
        recurring_patterns=kw.get(
            "recurring",
            [{"pattern": "1号装置/压缩机房-火灾报警", "count": 2, "departments": ["动力车间"]}],
        ),
    )


class TestRenderWeeklyReport:
    """周报渲染（ticket 06）：标题→周起止→统计→重复问题→AI 周级分析→整改提醒。"""

    def _weekly_ai_summary(self) -> dict:
        return {
            "summary": "本周报警集中在动力车间设备设施类误报，呈现重复趋势。",
            "typical_issues": [
                {"title": "传感器老化误报", "evidence": "1号装置压缩机房本周发生 2 次火灾报警"},
            ],
            "recurring_issues": [
                {"pattern": "1号装置/压缩机房-火灾报警", "count": 2, "departments": ["动力车间"]},
            ],
            "systemic_suggestions": [
                {"issue": "同批次传感器老化", "suggestion": "统一更换并建立周期校验台账"},
            ],
            "trend": {"summary": "本周报警总量较上周持平", "trend": "平稳"},
        }

    def test_structure_with_ai_summary(self):
        agg = make_weekly_agg([make_record()])
        md = render_weekly_report(
            agg,
            {"张三": "ou_zhangsan"},
            ai_summary=self._weekly_ai_summary(),
        )
        assert "🔥 **消防报警周报**" in md
        assert "🔥 **消防报警周报** · 2026-03-09 ~ 2026-03-15" in md
        assert "📅 周一~周日" in md
        assert "**📊 本周报警统计**" in md
        assert "报警总数：**1 起**" in md
        # 重复/集中问题块（count>=2 的模式）
        assert "**🔁 重复/集中问题**" in md
        assert "· ① 1号装置/压缩机房-火灾报警（**2 次**）涉及：动力车间" in md
        # 周级 AI 分析（需求保留：重复报警未采取措施 + @负责人跟进）
        assert "**🔁 重复报警（未采取措施）**" in md
        assert "1. 传感器老化误报：1号装置压缩机房本周发生 2 次火灾报警" in md
        assert "**✅ 系统性整改建议**" in md
        assert "1. 同批次传感器老化：统一更换并建立周期校验台账" in md
        assert "**📈 趋势**：本周报警总量较上周持平；趋势：**平稳**" in md
        # 明细按部门分组，无文末整改提醒（需求 5/6）
        assert "**⚠️ 整改提醒**" not in md
        assert '<at id=ou_zhangsan></at>' in md
        assert DIVIDER in md

    def test_ai_summary_none_omits_weekly_block(self):
        md = render_weekly_report(make_weekly_agg([make_record()]), {}, ai_summary=None)
        assert "🧠 **AI 周级分析**" not in md
        # 其余结构照常
        assert "**📊 本周报警统计**" in md
        assert "**🔁 重复/集中问题**" in md

    def test_no_recurring_patterns_message(self):
        agg = make_weekly_agg([make_record()], recurring=[])
        md = render_weekly_report(agg, {}, ai_summary=None)
        # 无重复报警 → 不显示重复提示块
        assert "**🔁 重复报警（未采取措施）**" not in md
        assert "**🔁 重复/集中问题**" not in md

    def test_unanalyzed_records_shown_in_stats(self):
        """兼容 ai_dimension=None 记录：统计显示未分析条数。"""
        records = [
            make_record(ai_dimension=None, reason=None, direction=None, analyzed_at=None),
            make_record(ai_dimension="equipment"),
        ]
        agg = make_weekly_agg(records)
        md = render_weekly_report(agg, {}, ai_summary=None)
        assert "AI 分析覆盖：1/2 条已分析（**1 条未分析**）" in md

    def test_all_analyzed_no_unanalyzed_suffix(self):
        md = render_weekly_report(make_weekly_agg([make_record()]), {}, ai_summary=None)
        assert "AI 分析覆盖：1/1 条已分析" in md
        assert "未分析" not in md

    def test_empty_week(self):
        md = render_weekly_report(make_weekly_agg([], recurring=[]), {}, ai_summary=None)
        assert "报警总数：**0 起**" in md
        assert "（本周暂无明显重复/集中问题）" in md
        assert "AI 分析覆盖" not in md  # 无记录不显示覆盖行

    def test_at_fallback_plain_text(self):
        md = render_weekly_report(make_weekly_agg([make_record()]), {}, ai_summary=None)
        assert "动力车间" in md
        assert "张三" in md
        assert "<at" not in md

