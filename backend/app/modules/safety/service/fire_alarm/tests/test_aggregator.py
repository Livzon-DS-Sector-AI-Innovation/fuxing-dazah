"""消防报警分析 — 聚合纯函数单测（MagicMock 记录，无 DB 依赖）。

覆盖：aggregate_daily / aggregate_weekly 分布统计、部门负责人映射、
周级 recurring_patterns 重复问题识别、空值不计入、get_natural_week_range。
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.modules.safety.service.fire_alarm.aggregator import (
    aggregate_daily,
    aggregate_weekly,
    get_natural_week_range,
)

REF_DATE = date(2026, 3, 12)  # 周四
WEEK_START = date(2026, 3, 9)  # 周一
WEEK_END = date(2026, 3, 15)  # 周日


def make_record(**kw) -> MagicMock:
    """构造最小 FireAlarmRecord 替身（仅暴露聚合用到的属性）。"""
    r = MagicMock()
    r.alarm_type = kw.get("alarm_type", "火灾报警")
    r.alarm_nature = kw.get("alarm_nature", "误报")
    r.ai_dimension = kw.get("ai_dimension", None)
    r.department = kw.get("department", "动力车间")
    r.department_leader_name = kw.get("leader", "张三")
    r.building = kw.get("building", "1号装置")
    r.location = kw.get("location", "压缩机房")
    r.ai_dimension = kw.get("ai_dimension", None)  # 仅用于记录输入，聚合不再统计维度
    return r


class TestAggregateDaily:
    def test_distributions_and_total(self):
        records = [
            make_record(alarm_type="火灾报警", alarm_nature="误报"),
            make_record(alarm_type="手动报警", alarm_nature="真实报警"),
            make_record(alarm_type="火灾报警", alarm_nature="误报"),
            make_record(alarm_type=None, alarm_nature="误报"),  # 类型 None → 不计入
        ]
        agg = aggregate_daily(records, REF_DATE)
        assert agg.target_date == REF_DATE
        assert agg.total == 4
        assert agg.nature_distribution == {"误报": 3, "真实报警": 1}
        assert agg.type_distribution == {"火灾报警": 2, "手动报警": 1}
        assert agg.department_distribution == {"动力车间": 4}
        assert agg.records == records

    def test_dept_leader_names_first_non_empty(self):
        records = [
            make_record(department="动力车间", leader="张三"),
            make_record(department="动力车间", leader=None),
            make_record(department="仓储部", leader="李四"),
            make_record(department="仓储部", leader="王五"),  # 首个非空保留
            make_record(department="无负责人部门", leader=None),
        ]
        agg = aggregate_daily(records, REF_DATE)
        assert agg.dept_leader_names == {
            "动力车间": "张三",
            "仓储部": "李四",
        }, "同名部门取首个非空负责人"

    def test_empty_records(self):
        agg = aggregate_daily([], REF_DATE)
        assert agg.total == 0
        assert agg.nature_distribution == {}
        assert agg.type_distribution == {}
        assert agg.department_distribution == {}
        assert agg.dept_leader_names == {}


class TestAggregateWeekly:
    """周报聚合（ticket 06）：统计分布 + recurring_patterns 重复问题识别。"""

    def test_distributions_and_recurring_patterns(self):
        records = [
            make_record(  # 重复问题 A：同楼栋/部位/类型 ×2
                alarm_type="火灾报警", alarm_nature="误报",
                department="动力车间",
            ),
            make_record(  # 重复问题 A 第 2 次
                alarm_type="火灾报警", alarm_nature="误报",
                department="动力车间",
            ),
            make_record(  # 同类型不同位置 → 单次不构成重复
                alarm_type="火灾报警", alarm_nature="误报",
                department="仓储部", leader="李四",
                building="成品库", location="配电室",
            ),
            make_record(alarm_type="手动报警", alarm_nature="真实报警"),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert agg.week_start == WEEK_START
        assert agg.week_end == WEEK_END
        assert agg.total == 4
        assert agg.nature_distribution == {"误报": 3, "真实报警": 1}
        assert agg.type_distribution == {"火灾报警": 3, "手动报警": 1}
        assert agg.department_distribution == {"动力车间": 3, "仓储部": 1}
        assert agg.dept_leader_names == {"动力车间": "张三", "仓储部": "李四"}
        # 仅 count>=2 的模式进入重复问题
        assert agg.recurring_patterns == [{
            "pattern": "1号装置/压缩机房-火灾报警",
            "count": 2,
            "departments": ["动力车间"],
        }]

    def test_single_occurrence_not_recurring(self):
        agg = aggregate_weekly([make_record()], WEEK_START, WEEK_END)
        assert agg.recurring_patterns == []

    def test_place_label_fallbacks_building_only(self):
        records = [
            make_record(building="1号装置", location=None),
            make_record(building="1号装置", location=None),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert agg.recurring_patterns == [{
            "pattern": "1号装置-火灾报警",
            "count": 2,
            "departments": ["动力车间"],
        }]

    def test_place_label_fallbacks_location_only(self):
        records = [
            make_record(building=None, location="配电室"),
            make_record(building=None, location="配电室"),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert agg.recurring_patterns == [{
            "pattern": "配电室-火灾报警",
            "count": 2,
            "departments": ["动力车间"],
        }]

    def test_place_label_fallbacks_unknown(self):
        records = [
            make_record(building=None, location=None),
            make_record(building=None, location=None),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert agg.recurring_patterns == [{
            "pattern": "部位待确认-火灾报警",
            "count": 2,
            "departments": ["动力车间"],
        }]

    def test_sorted_by_count_desc_then_pattern(self):
        records = [
            make_record(building="A栋", location=None),  # 3 次
            make_record(building="A栋", location=None),
            make_record(building="A栋", location=None),
            make_record(building="B栋", location=None),  # 2 次
            make_record(building="B栋", location=None),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert [p["pattern"] for p in agg.recurring_patterns] == [
            "A栋-火灾报警", "B栋-火灾报警",
        ]
        assert agg.recurring_patterns[0]["count"] == 3
        assert agg.recurring_patterns[1]["count"] == 2

    def test_departments_deduped_and_sorted(self):
        records = [
            make_record(department="动力车间"),
            make_record(department="仓储部"),
            make_record(department="动力车间"),
            make_record(department=None),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert agg.recurring_patterns == [{
            "pattern": "1号装置/压缩机房-火灾报警",
            "count": 4,
            "departments": ["仓储部", "动力车间"],
        }]

    def test_missing_alarm_type_excluded_from_recurring(self):
        records = [
            make_record(alarm_type=None),
            make_record(alarm_type=None),
        ]
        agg = aggregate_weekly(records, WEEK_START, WEEK_END)
        assert agg.recurring_patterns == []
        assert agg.type_distribution == {}  # None 不计入分布

    def test_empty_records(self):
        agg = aggregate_weekly([], WEEK_START, WEEK_END)
        assert agg.total == 0
        assert agg.nature_distribution == {}
        assert agg.type_distribution == {}
        assert agg.department_distribution == {}
        assert agg.dept_leader_names == {}
        assert agg.recurring_patterns == []


class TestGetNaturalWeekRange:
    def test_mid_week(self):
        # 2026-03-12 是周四 → 周一 03-09 / 周日 03-15
        assert get_natural_week_range(date(2026, 3, 12)) == (
            date(2026, 3, 9), date(2026, 3, 15),
        )

    def test_monday_and_sunday_edges(self):
        assert get_natural_week_range(date(2026, 3, 9)) == (
            date(2026, 3, 9), date(2026, 3, 15),
        )
        assert get_natural_week_range(date(2026, 3, 15)) == (
            date(2026, 3, 9), date(2026, 3, 15),
        )

    def test_week_crossing_month(self):
        # 2026-07-01 是周三 → 周一 06-29 / 周日 07-05
        assert get_natural_week_range(date(2026, 7, 1)) == (
            date(2026, 6, 29), date(2026, 7, 5),
        )
