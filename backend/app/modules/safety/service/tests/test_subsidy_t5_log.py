"""提炼五部监护补贴台账(Bitable 第二数据源)适配单测。

纯函数 build_t5_plan 的行级规则(2026-10-08 口径):类型别名归一、
级别只认台账登记(不回退证书台账)、月份过滤、时间兜底/跳过、
未登级别按 A 证暂计、同日重叠去重(与平台源同规则)。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.modules.safety.service.subsidy_t5_log import (
    DEPARTMENT,
    _ms_to_datetime,
    build_t5_plan,
)

TZ = ZoneInfo("Asia/Shanghai")


class _Unset:
    """哨兵:区分「未传时间参数(用默认值)」与「显式 None(字段缺失)」。"""


_UNSET = _Unset()


def _ts(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=TZ).timestamp() * 1000)


def _row(
    *,
    guardian: str | None = "张三",
    level: str | None = None,
    op_type: str = "动火作业",
    op_level: str = "一级",
    start: int | None | _Unset = _UNSET,
    end: int | None | _Unset = _UNSET,
    location: str = "车间一动火焊接",
) -> dict:
    return {
        "fields": {
            "监护人": [{"id": "ou_x", "name": guardian}] if guardian else [],
            "监护人级别": level,
            "特殊作业类型": op_type,
            "作业级别": op_level,
            "开始时间": _ts(2026, 9, 1, 8) if start is _UNSET else start,
            "结束时间": _ts(2026, 9, 1, 12) if end is _UNSET else end,
            "作业地点+作业内容": location,
        }
    }


def test_ms_to_datetime_and_invalid() -> None:
    dt = _ms_to_datetime(_ts(2026, 9, 1, 8))
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 9, 1, 8)
    assert _ms_to_datetime(None) is None
    assert _ms_to_datetime("bad") is None


def test_basic_record_and_type_alias() -> None:
    rows = [
        _row(guardian="张三", level="A证"),                          # 动火作业(直名)
        _row(guardian="李四", level="A证", op_type="动土作业"),      # 别名 → 动土
        _row(guardian="王五", level="A证", op_type="盲板抽堵", end=None),  # 别名 → 抽堵盲板(按次,缺 end 兜底)
        _row(guardian="赵六", level="A证", op_type="断路作业"),      # 别名 → 断路
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 4
    assert {r.operation_type for r in plan.records} == {"动火作业", "动土", "抽堵盲板", "断路"}
    assert all(r.department == DEPARTMENT for r in plan.records)
    assert plan.records[0].ticket_no == "09-01 张三"  # 台账无票号,以行标识代替


def test_sheet_level_is_authority() -> None:
    """证书以台账为准:级别取表内登记(同名多行以最后一次登记为准)。"""
    rows = [
        _row(guardian="李四", level="B证"),
        _row(guardian="李四", level="A证"),  # 后登记者为准
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert all(r.guardian_level == "A证" for r in plan.records)


def test_uncertified_counted_and_listed() -> None:
    """未登级别 → 暂计 A证 + 进待核对;uncertified_level=None 则不计入。"""
    rows = [
        _row(guardian="路人甲"),                                              # 09-01
        _row(guardian="路人甲", op_type="吊装作业", start=_ts(2026, 9, 2, 8)),  # 09-02(不同日不触去重)
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 2
    assert all(r.guardian_level == "A证" for r in plan.records)
    assert plan.unmatched_tickets == 2
    assert [u.name for u in plan.unmatched] == ["路人甲"]

    legacy = build_t5_plan(rows, 2026, 9, uncertified_level=None)
    assert legacy.matched_tickets == 0
    assert legacy.unmatched_tickets == 2


def test_month_filter_by_start_time() -> None:
    rows = [
        _row(start=_ts(2026, 8, 31, 23), end=_ts(2026, 9, 1, 2)),   # 8 月开始 → 忽略
        _row(start=_ts(2026, 9, 30, 20), end=_ts(2026, 10, 1, 2)),  # 9 月开始 → 计入
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 1


def test_missing_time_rules() -> None:
    rows = [
        _row(level="A证", start=None),                    # 缺开始 → 跳过
        _row(level="A证", end=None, op_type="受限空间"),  # 非按次缺结束 → 跳过
        _row(level="A证", end=None, op_type="临时用电"),  # 按次缺结束 → 兜底计入
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 1
    assert plan.records[0].operation_type == "临时用电"
    assert plan.records[0].start_time == plan.records[0].end_time  # end=start 兜底
    reasons = sorted(s.reason for s in plan.skipped)
    assert reasons == ["缺少开始时间", "缺少结束时间"]


def test_no_guardian_and_unknown_type_skipped() -> None:
    rows = [_row(level="A证", guardian=None), _row(level="A证", op_type="新型作业")]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 0
    assert sorted(s.reason for s in plan.skipped) == ["无监护人", "未知作业类型"]


def test_overlapping_rows_deduped_keep_highest() -> None:
    """同监护人同日时间重叠 → 与平台源同规则,保留补贴最高一行(白班 8h > 晚班 2.8h)。"""
    rows = [
        _row(level="A证", start=_ts(2026, 9, 1, 8), end=_ts(2026, 9, 1, 16, 10)),
        _row(level="A证", start=_ts(2026, 9, 1, 15, 10), end=_ts(2026, 9, 1, 18)),
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 1
    kept = plan.records[0]
    assert kept.start_time.startswith("2026-09-01T08:00")
    assert len(plan.skipped) == 1
    assert "同日时间重叠" in plan.skipped[0].reason
    assert plan.skipped[0].ticket_no == "09-01 张三"


def test_non_overlapping_and_cross_day_not_deduped() -> None:
    """同日先后不重叠 / 不同日 → 全保留。"""
    rows = [
        _row(level="A证", start=_ts(2026, 9, 1, 8), end=_ts(2026, 9, 1, 10)),
        _row(level="A证", start=_ts(2026, 9, 1, 10), end=_ts(2026, 9, 1, 12)),  # 相接不重叠
        _row(level="A证", start=_ts(2026, 9, 2, 15, 10), end=_ts(2026, 9, 2, 18)),
    ]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.matched_tickets == 3
    assert plan.skipped == []


def test_row_id_format_for_skipped() -> None:
    """跳过行标识 = 'MM-DD 姓名'(表无票号)。"""
    rows = [_row(guardian="王五", level="A证", start=None)]
    plan = build_t5_plan(rows, 2026, 9)
    assert plan.skipped[0].ticket_no == "(不完整行)"  # 缺开始时间无法拼日期标识
    rows2 = [_row(guardian="王五", level="A证", end=None, op_type="受限空间")]
    plan2 = build_t5_plan(rows2, 2026, 9)
    assert plan2.skipped[0].ticket_no == "09-01 王五"
