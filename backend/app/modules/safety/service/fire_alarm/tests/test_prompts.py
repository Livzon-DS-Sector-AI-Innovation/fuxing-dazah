"""消防报警分析 — prompt 构造纯函数单测（MagicMock，无 DB）。

覆盖：前缀缓存规则（system 稳定 / user 动态末尾）、EXPECTED_KEYS 常量、
build_per_record_messages / build_daily_summary_messages / build_weekly_summary_messages。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmWeeklyAgg,
)
from app.modules.safety.service.fire_alarm.prompts import (
    EXPECTED_KEYS_DAILY_SUMMARY,
    EXPECTED_KEYS_PER_RECORD,
    EXPECTED_KEYS_WEEKLY_SUMMARY,
    build_daily_summary_messages,
    build_per_record_messages,
    build_weekly_summary_messages,
)

REF_DATE = date(2026, 3, 12)


def make_record(**kw) -> MagicMock:
    r = MagicMock()
    r.alarm_time = kw.get("alarm_time", datetime(2026, 3, 12, 2, 0, tzinfo=UTC))
    r.alarm_type = kw.get("alarm_type", "火灾报警")
    r.department = kw.get("department", "动力车间")
    r.building = kw.get("building", "1号装置")
    r.location = kw.get("location", "压缩机房")
    r.alarm_nature = kw.get("alarm_nature", "误报")
    r.cause_category = kw.get("cause_category", "设备故障")
    r.cause_description = kw.get("cause_description", "传感器老化误触发")
    r.ai_dimension = kw.get("ai_dimension", "equipment")
    return r


def make_daily_agg() -> FireAlarmDailyAgg:
    return FireAlarmDailyAgg(
        target_date=REF_DATE,
        records=[make_record()],
        total=1,
        nature_distribution={"误报": 1},
        type_distribution={"火灾报警": 1},
        dimension_distribution={"equipment": 1},
        department_distribution={"动力车间": 1},
        dept_leader_names={"动力车间": "张三"},
    )


def make_weekly_agg() -> FireAlarmWeeklyAgg:
    return FireAlarmWeeklyAgg(
        week_start=REF_DATE.replace(day=9),
        week_end=REF_DATE.replace(day=15),
        records=[make_record()],
        total=1,
        nature_distribution={"误报": 1},
        type_distribution={"火灾报警": 1},
        dimension_distribution={"equipment": 1},
        department_distribution={"动力车间": 1},
        dept_leader_names={"动力车间": "张三"},
        recurring_patterns=[{"pattern": "1号装置-火灾报警", "count": 2, "departments": ["动力车间"]}],
    )


class TestExpectedKeys:
    def test_constants(self):
        assert EXPECTED_KEYS_PER_RECORD == [
            "dimension", "reason_analysis", "rectification_direction",
        ]
        assert EXPECTED_KEYS_DAILY_SUMMARY == [
            "summary", "key_issues", "rectification_suggestions",
        ]
        assert EXPECTED_KEYS_WEEKLY_SUMMARY == [
            "summary", "typical_issues", "recurring_issues",
            "systemic_suggestions", "trend",
        ]


class TestBuildPerRecordMessages:
    def test_system_stable_user_dynamic(self):
        r1 = make_record()
        r2 = make_record(cause_description="原因B" * 300)  # 超长截断 200
        m1 = build_per_record_messages(r1, "法规文本" * 500)  # 超长截断 1500
        m2 = build_per_record_messages(r2, "")
        assert [x["role"] for x in m1] == ["system", "user"]
        # 前缀缓存规则：system 完全一致（稳定常量），user 动态
        assert m1[0]["content"] == m2[0]["content"]
        assert "化工企业消防安全管理专家" in m1[0]["content"]
        assert m1[1]["content"] != m2[1]["content"]
        # 动态数据在 user：记录字段 + RAG 法规（截断）+ 收尾指令
        user1 = m1[1]["content"]
        assert "## 报警记录分析" in user1
        assert "报警部门: 动力车间" in user1
        assert "传感器老化误触发" in user1
        assert "03/12 10:00" in user1  # UTC → 北京时间
        assert len(m1[1]["content"]) <= 1500 + 600  # 法规截断 1500 + 记录字段
        assert user1.endswith("请输出 JSON。")
        # 无 rag_md → user 不含参考法规行
        assert "参考法规" not in m2[1]["content"]

    def test_missing_fields_placeholder(self):
        m = build_per_record_messages(
            make_record(alarm_time=None, department=None), "",
        )
        assert "报警时间: ?" in m[1]["content"]
        assert "报警部门: ?" in m[1]["content"]


class TestBuildDailySummaryMessages:
    def test_structure_and_stats(self):
        m = build_daily_summary_messages(make_daily_agg(), ["报警03/12 动力车间 - 原因"])
        assert [x["role"] for x in m] == ["system", "user"]
        assert "化工企业消防安全管理专家" in m[0]["content"]
        user = m[1]["content"]
        assert '"报警总数": 1' in user
        assert '"部门分布"' in user
        assert "报警03/12 动力车间 - 原因" in user
        assert user.endswith("请输出 JSON（不要输出其他内容）。")


class TestBuildWeeklySummaryMessages:
    def test_structure_includes_recurring_and_records(self):
        m = build_weekly_summary_messages(make_weekly_agg())
        assert [x["role"] for x in m] == ["system", "user"]
        assert "周级汇总分析" in m[0]["content"]
        user = m[1]["content"]
        assert '"周起止": "2026-03-09 ~ 2026-03-15"' in user
        assert '"重复问题清单"' in user
        assert "1号装置-火灾报警" in user
        assert '"cause_description": "传感器老化误触发"' in user
        assert user.endswith("请输出 JSON（不要输出其他内容）。")
