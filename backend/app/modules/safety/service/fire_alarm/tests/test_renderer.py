"""消防报警日报/月报 — Markdown 渲染纯函数单测（无 DB / 无环境依赖）。

覆盖：日报渲染结构（标题/统计/明细/整改提醒）、AI 汇总块可选、_at @提及与纯文本兜底；
月报渲染结构（标题/月起止/统计/重复问题/AI 月度分析三板块/整改提醒）、
AI 字段格式异常降级、用户定制 2026-09-22（AI 板块只围绕重复问题/原因/整改建议）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmMonthlyAgg,
)
from app.modules.safety.service.fire_alarm.renderer import (
    DIVIDER,
    _at,
    render_daily_report,
    render_monthly_report,
)

TARGET_DATE = date(2026, 3, 12)
MONTH_START = date(2026, 3, 1)
MONTH_END = date(2026, 3, 31)


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

    def test_dm_recipients_block_rendered(self) -> None:
        dm = {
            "动力车间": {"部门负责人": "张三", "分管安全员": "李四", "分管领导": "王五"},
            "仓储部": {},
        }
        md = render_daily_report(
            make_agg([make_record()]), {}, ai_summary=None, dm_recipients=dm,
        )
        assert "**📨 每日私发推送**" in md
        assert "· 动力车间：张三（负责人）、李四（分管安全员）、王五（分管领导）" in md
        assert "· 仓储部：（未配置收件人，跳过私发）" in md
        assert "· 每条报警一卡一条私发至上述人员（负责人 + 分管安全员）" in md
        # 板块位于部门明细之后、文末整改提醒之前
        assert md.index("**📨 每日私发推送**") > md.index("**动力车间**")
        assert md.index("**📨 每日私发推送**") < md.index("各部门负责人请核实")

    def test_dm_recipients_none_or_empty_omits_block(self) -> None:
        md = render_daily_report(
            make_agg([make_record()]), {}, ai_summary=None, dm_recipients=None,
        )
        assert "📨" not in md
        md_empty = render_daily_report(
            make_agg([make_record()]), {}, ai_summary=None, dm_recipients={},
        )
        assert "📨" not in md_empty

    def test_extra_mentions_at_leader_side(self) -> None:
        """EXTRA_DM_RECIPIENTS 命中部门：部门块在 @负责人之外追加 @（如 @分管领导）。"""
        md = render_daily_report(
            make_agg([make_record()]),
            {"张三": "ou_zhangsan", "王五": "ou_wangwu"},
            ai_summary=None,
            extra_mentions={"动力车间": ["王五"]},
        )
        dept_head = next(
            line for line in md.splitlines() if line.startswith("**动力车间**")
        )
        assert dept_head.index('<at id=ou_zhangsan></at>') < dept_head.index(
            '<at id=ou_wangwu></at>'
        )

    def test_extra_mentions_dedupe_leader(self) -> None:
        """额外名单与负责人同名时只 @ 一次。"""
        md = render_daily_report(
            make_agg([make_record()]),
            {"张三": "ou_zhangsan"},
            ai_summary=None,
            extra_mentions={"动力车间": ["张三"]},
        )
        dept_head = next(
            line for line in md.splitlines() if line.startswith("**动力车间**")
        )
        assert dept_head.count('<at id=ou_zhangsan></at>') == 1


def make_monthly_agg(records, **kw) -> FireAlarmMonthlyAgg:
    return FireAlarmMonthlyAgg(
        month_start=MONTH_START,
        month_end=MONTH_END,
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


class TestRenderMonthlyReport:
    """月报渲染（2026-09-22 周报改月报）：标题→月起止→统计→重复问题→AI 月度分析→整改提醒。"""

    def _monthly_ai_summary(self) -> dict:
        return {
            "recurring_issues": [
                {
                    "pattern": "1号装置/压缩机房-火灾报警",
                    "count": 3,
                    "cause": "同一批次传感器老化漂移导致连续误触发",
                    "suggestion": "整批更换该型传感器并建立季度标定台账",
                },
            ],
            "cause_summary": "本月误报集中于压缩机房传感器类设备故障，属设备设施维度共性问题。",
            "rectification_suggestions": [
                {
                    "issue": "压缩机房传感器批量老化误报",
                    "suggestion": "两周内完成整批更换并逐台标定，每季度校验一次",
                    "departments": ["动力车间"],
                },
            ],
        }

    def test_structure_with_ai_summary(self):
        agg = make_monthly_agg([make_record()])
        md = render_monthly_report(
            agg,
            {"张三": "ou_zhangsan"},
            ai_summary=self._monthly_ai_summary(),
        )
        assert "🔥 **消防报警月报**" in md
        assert "🔥 **消防报警月报** · 2026-03-01 ~ 2026-03-31" in md
        assert "📅 自然月（1 日~月末）" in md
        assert "**📊 上月报警统计**" in md
        assert "报警总数：**1 起**" in md
        # 重复/集中问题块（count>=2 的模式，@负责人跟进）
        assert "**🔁 重复/集中问题**" in md
        assert "· ① 1号装置/压缩机房-火灾报警（**2 次**）涉及：动力车间" in md
        assert '<at id=ou_zhangsan></at>' in md
        # AI 月度分析三板块（用户定制 2026-09-22：只围绕重复问题/原因/整改建议）
        assert "🧠 **AI 月度分析**" in md
        assert "**🔁 重复问题与原因**" in md
        assert "① 1号装置/压缩机房-火灾报警（**3 次**）" in md
        assert "原因：同一批次传感器老化漂移导致连续误触发" in md
        assert "整改：整批更换该型传感器并建立季度标定台账" in md
        assert "**📌 原因归纳**" in md
        assert "本月误报集中于压缩机房传感器类设备故障" in md
        assert "**✅ 整改建议**" in md
        assert "1. 压缩机房传感器批量老化误报：两周内完成整批更换并逐台标定，每季度校验一次（牵头：动力车间）" in md
        # 旧板块已删除（防跑题）
        assert "🧠 **AI 周级分析**" not in md
        assert "典型问题" not in md
        assert "📈 趋势" not in md
        # 无部门明细板块（需求沿用 2026-09-21）
        assert "**⚠️ 整改提醒**" not in md
        assert DIVIDER in md
        assert "**各部门负责人请及时跟进并落实整改措施。**" in md
        assert "① **报警原因**" not in md

    def test_ai_summary_none_omits_monthly_block(self):
        md = render_monthly_report(make_monthly_agg([make_record()]), {}, ai_summary=None)
        assert "🧠 **AI 月度分析**" not in md
        # 其余结构照常
        assert "**📊 上月报警统计**" in md
        assert "**🔁 重复/集中问题**" in md

    def test_no_recurring_patterns_message(self):
        agg = make_monthly_agg([make_record()], recurring=[])
        md = render_monthly_report(agg, {}, ai_summary=None)
        # 无重复报警 → 不显示重复提示块
        assert "**🔁 重复/集中问题**" not in md
        assert "（上月暂无明显重复/集中问题）" in md

    def test_ai_malformed_fields_degrade(self):
        summary = self._monthly_ai_summary()
        summary["recurring_issues"] = "not-a-list"  # 格式异常
        summary["cause_summary"] = {"bad": "type"}
        md = render_monthly_report(
            make_monthly_agg([make_record()]), {}, ai_summary=summary,
        )
        assert "🧠 **AI 月度分析**" in md
        assert "**🔁 重复问题与原因**" not in md  # 异常板块省略
        assert "**📌 原因归纳**" not in md
        # 正常板块照常渲染
        assert "**✅ 整改建议**" in md
        assert "（AI 输出格式异常，异常部分已省略）" in md

    def test_ai_empty_recurring_no_block_title_when_all_empty(self):
        summary = {"recurring_issues": [], "cause_summary": "", "rectification_suggestions": []}
        md = render_monthly_report(
            make_monthly_agg([make_record()]), {}, ai_summary=summary,
        )
        assert "🧠 **AI 月度分析**" not in md

    def test_unanalyzed_records_not_shown(self):
        """用户定制 2026-09-21 沿用：无「AI 分析覆盖」统计行与「未分析」前缀。"""
        records = [
            make_record(ai_dimension=None, reason=None, direction=None, analyzed_at=None),
            make_record(ai_dimension="equipment"),
        ]
        agg = make_monthly_agg(records)
        md = render_monthly_report(agg, {}, ai_summary=None)
        assert "AI 分析覆盖" not in md
        assert "未分析" not in md

    def test_empty_month(self):
        md = render_monthly_report(make_monthly_agg([], recurring=[]), {}, ai_summary=None)
        assert "报警总数：**0 起**" in md
        assert "（上月暂无明显重复/集中问题）" in md
        assert "AI 分析覆盖" not in md

    def test_at_fallback_plain_text(self):
        md = render_monthly_report(make_monthly_agg([make_record()]), {}, ai_summary=None)
        assert "动力车间" in md
        assert "张三" in md
        assert "<at" not in md

