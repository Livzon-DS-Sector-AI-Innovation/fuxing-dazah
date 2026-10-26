"""提炼四/五/六部监护补贴台账(Bitable 第二数据源族)适配单测。

纯函数 build_ledger_plan 的行级规则(2026-10-08 五部口径, 2026-10-26 四/六部
同口径接入):类型别名归一、级别只认台账登记(不回退证书台账;六部无级别列)、
月份过滤、时间兜底/跳过、未登级别按 A 证暂计、同日重叠去重(与平台源同规则)、
四/六部「日期+时间段文本」解析(全角冒号/波浪线/「一」/点分/多段/链式/带日期
前缀/跨零点)、六部多类型行取单价最高类型。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.modules.safety.service.subsidy_dept_ledgers import (
    LEDGER_SOURCES,
    _ms_to_datetime,
    _parse_date_text,
    _parse_period_segments,
    _pick_primary_op_type,
    build_ledger_plan,
    match_ledger_source,
)

TZ = ZoneInfo("Asia/Shanghai")


def _src(department: str):
    return next(s for s in LEDGER_SOURCES if s.department == department)


SRC4 = _src("提炼工程四部")
SRC5 = _src("提炼工程五部")
SRC6 = _src("提炼工程六部")


class _Unset:
    """哨兵:区分「未传时间参数(用默认值)」与「显式 None(字段缺失)」。"""


_UNSET = _Unset()


def _ts(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=TZ).timestamp() * 1000)


def _text(value: str) -> list[dict]:
    """Text 列形态 list[{text}]。"""
    return [{"text": value, "type": "text"}]


# ── 行夹具:三表结构各异 ─────────────────────────────────────────────


def _row5(
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


def _row4(
    *,
    guardian: str | None = "李小兰",
    level: str | None = "A证",
    op_type: str = "动火作业",
    op_level: str = "一级",
    day: str = "2026-09-10",
    period: str = "09:15-11:30，13:10-17:10",
    location: str = "车间一管道打磨",
) -> dict:
    base = datetime.fromisoformat(day)
    return {
        "fields": {
            "姓名": _text(guardian) if guardian else [],
            "监护证类别": level,
            "特殊作业类型": op_type,
            "作业级别": op_level,
            "日期": _ts(base.year, base.month, base.day, 0),
            "时间段（写全：如8:30-11:00  13:30-17:00）": _text(period),
            "监护内容（具体到作业位置）": _text(location),
        }
    }


def _row6(
    *,
    guardian: str | None = "池守城",
    op_types: list[str] | None = None,
    op_level: str = "一级",
    day: str = "2026.09.10",
    period: str = "09:10-17:10",
    location: str = "二期车间更换灯具",
) -> dict:
    return {
        "fields": {
            "姓名": _text(guardian) if guardian else [],
            "特殊作业类型": op_types if op_types is not None else ["动火作业"],
            "作业级别": op_level,
            "作业地点及内容": _text(location),
            "日期": _text(day),
            "时间段": _text(period),
        }
    }


# ═══════════════════════════════════════════════════════════════════
# 路由:match_ledger_source
# ═══════════════════════════════════════════════════════════════════


def test_match_ledger_source() -> None:
    assert match_ledger_source("提炼四部") is SRC4
    assert match_ledger_source("四部").department == "提炼工程四部"
    assert match_ledger_source("统计一下提炼工程六部9月补贴").department == "提炼工程六部"
    assert match_ledger_source("提炼五部监护补贴").department == "提炼工程五部"
    assert match_ledger_source("环保") is None       # 非台账部门 → 平台源
    assert match_ledger_source("") is None
    assert match_ledger_source("四部和五部") is None  # 多命中 → 回落平台源


# ═══════════════════════════════════════════════════════════════════
# 时间段文本解析(_parse_period_segments / _parse_date_text)
# ═══════════════════════════════════════════════════════════════════


def test_period_variants_single_segment() -> None:
    base = date(2026, 9, 10)

    def seg(text: str):
        return _parse_period_segments(text, base)

    # 半角/全角冒号/波浪线/「一」/点分
    r = seg("09:10-17:10")
    assert (r[0].hour, r[0].minute, r[1].hour, r[1].minute, r[2]) == (9, 10, 17, 10, 0.0)
    assert r[0].date() == base and r[1].date() == base
    assert seg("08：30-18：00")[0].hour == 8
    assert seg("9:00～18:00")[1].hour == 18
    assert seg("9：45一18：00")[0].minute == 45
    assert seg("08.20一18.00") == seg("08:20-18:00")
    assert seg("09：20—17：19")[0].minute == 20  # em dash
    assert seg("09:00--11：30")[0].hour == 9     # 连续双横线

    # 带完整日期前缀:日期取段内自带值
    r = seg("2026.09.10 09:10-2026.09.10 18:00")
    assert (r[0].day, r[0].hour) == (10, 9) and (r[1].day, r[1].hour) == (10, 18)

    # 跨零点兜底:结束时刻不晚于开始 → 顺延一天
    r = seg("22:00-02:00")
    assert r[1].date() != r[0].date() and r[1].hour == 2

    # 无法解析:无时间 token / 奇数个 token
    assert _parse_period_segments("随叫随到", base) is None
    assert _parse_period_segments("09:10", base) is None
    assert _parse_period_segments("", base) is None


def test_period_multi_segment_interval() -> None:
    base = date(2026, 9, 10)
    # 换行分段:09:15-11:30 + 13:10-17:10 → 空档 = 11:30→13:10 = 1h40m
    start, end, interval = _parse_period_segments("09：15-11：30\n13：10-17:10", base)
    assert (start.hour, start.minute) == (9, 15)
    assert (end.hour, end.minute) == (17, 10)
    assert interval == 1.67

    # 逗号/空格分隔同义:空档 = 11:30→13:00 = 1.5h
    assert _parse_period_segments("9:10-11:30，13:00-17:09", base)[2] == 1.5
    # 空格分隔:空档 = 11:00→13:00 = 2h
    assert _parse_period_segments("09:25-11:00  13:00-17:07", base)[2] == 2.0

    # 链式四时间(实测写法)→ 两段,空档 1.5h
    assert _parse_period_segments("09:16-11:30-13:00-17:10", base)[2] == 1.5


def test_parse_date_text() -> None:
    assert _parse_date_text("2026.09.03") == date(2026, 9, 3)
    assert _parse_date_text("2026.09.06-2026.09.07") == date(2026, 9, 6)  # 区间取首日
    assert _parse_date_text("2026-09-03") == date(2026, 9, 3)
    assert _parse_date_text("not a date") is None


def test_pick_primary_op_type() -> None:
    assert _pick_primary_op_type(["动火作业"], "一级") == "动火作业"
    # 动火一级 10 元/半小时 > 高处一级 5 元 → 动火
    assert _pick_primary_op_type(["动火作业", "高处作业"], "一级") == "动火作业"
    # 受限空间默认 10 = 动火一级 10 → 同价取表内第一个
    assert _pick_primary_op_type(["受限空间", "动火作业"], "一级") == "受限空间"
    assert _pick_primary_op_type([], "一级") == ""


# ═══════════════════════════════════════════════════════════════════
# 五部(start_end 布局,口径回归自旧 test_subsidy_t5_log)
# ═══════════════════════════════════════════════════════════════════


def test_ms_to_datetime_and_invalid() -> None:
    dt = _ms_to_datetime(_ts(2026, 9, 1, 8))
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 9, 1, 8)
    assert _ms_to_datetime(None) is None
    assert _ms_to_datetime("bad") is None


def test_basic_record_and_type_alias() -> None:
    rows = [
        _row5(guardian="张三", level="A证"),                          # 动火作业(直名)
        _row5(guardian="李四", level="A证", op_type="动土作业"),      # 别名 → 动土
        _row5(guardian="王五", level="A证", op_type="盲板抽堵"),      # 别名 → 抽堵盲板(按次)
        _row5(guardian="赵六", level="A证", op_type="断路作业"),      # 别名 → 断路
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 4
    assert {r.operation_type for r in plan.records} == {"动火作业", "动土", "抽堵盲板", "断路"}
    assert all(r.department == "提炼工程五部" for r in plan.records)
    assert plan.records[0].ticket_no == "09-01 张三"  # 台账无票号,以行标识代替


def test_sheet_level_is_authority() -> None:
    """证书以台账为准:级别取表内登记(同名多行以最后一次登记为准)。"""
    rows = [
        _row5(guardian="李四", level="B证"),
        _row5(guardian="李四", level="A证"),  # 后登记者为准
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert all(r.guardian_level == "A证" for r in plan.records)


def test_uncertified_counted_and_listed() -> None:
    """未登级别 → 暂计 A证 + 进待核对;uncertified_level=None 则不计入。"""
    rows = [
        _row5(guardian="路人甲"),                                              # 09-01
        _row5(guardian="路人甲", op_type="吊装作业", start=_ts(2026, 9, 2, 8)),  # 09-02(不同日不触去重)
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 2
    assert all(r.guardian_level == "A证" for r in plan.records)
    assert plan.unmatched_tickets == 2
    assert [u.name for u in plan.unmatched] == ["路人甲"]

    legacy = build_ledger_plan(SRC5, rows, 2026, 9, uncertified_level=None)
    assert legacy.matched_tickets == 0
    assert legacy.unmatched_tickets == 2


def test_month_filter_by_start_time() -> None:
    rows = [
        _row5(start=_ts(2026, 8, 31, 23), end=_ts(2026, 9, 1, 2)),   # 8 月开始 → 忽略
        _row5(start=_ts(2026, 9, 30, 20), end=_ts(2026, 10, 1, 2)),  # 9 月开始 → 计入
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 1


def test_missing_time_rules() -> None:
    rows = [
        _row5(level="A证", start=None),                    # 缺开始 → 跳过
        _row5(level="A证", end=None, op_type="受限空间"),  # 非按次缺结束 → 跳过
        _row5(level="A证", end=None, op_type="临时用电"),  # 按次缺结束 → 兜底计入
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 1
    assert plan.records[0].operation_type == "临时用电"
    assert plan.records[0].start_time == plan.records[0].end_time  # end=start 兜底
    reasons = sorted(s.reason for s in plan.skipped)
    assert reasons == ["缺少开始时间", "缺少结束时间"]


def test_no_guardian_and_unknown_type_skipped() -> None:
    rows = [_row5(level="A证", guardian=None), _row5(level="A证", op_type="新型作业")]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 0
    assert sorted(s.reason for s in plan.skipped) == ["无监护人", "未知作业类型"]


def test_overlapping_rows_deduped_keep_highest() -> None:
    """同监护人同日时间重叠 → 与平台源同规则,保留补贴最高一行(白班 8h > 晚班 2.8h)。"""
    rows = [
        _row5(level="A证", start=_ts(2026, 9, 1, 8), end=_ts(2026, 9, 1, 16, 10)),
        _row5(level="A证", start=_ts(2026, 9, 1, 15, 10), end=_ts(2026, 9, 1, 18)),
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 1
    kept = plan.records[0]
    assert kept.start_time.startswith("2026-09-01T08:00")
    assert len(plan.skipped) == 1
    assert "同日时间重叠" in plan.skipped[0].reason
    assert plan.skipped[0].ticket_no == "09-01 张三"


def test_non_overlapping_and_cross_day_not_deduped() -> None:
    """同日先后不重叠 / 不同日 → 全保留。"""
    rows = [
        _row5(level="A证", start=_ts(2026, 9, 1, 8), end=_ts(2026, 9, 1, 10)),
        _row5(level="A证", start=_ts(2026, 9, 1, 10), end=_ts(2026, 9, 1, 12)),  # 相接不重叠
        _row5(level="A证", start=_ts(2026, 9, 2, 15, 10), end=_ts(2026, 9, 2, 18)),
    ]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.matched_tickets == 3
    assert plan.skipped == []


def test_row_id_format_for_skipped() -> None:
    """跳过行标识 = 'MM-DD 姓名'(表无票号)。"""
    rows = [_row5(guardian="王五", level="A证", start=None)]
    plan = build_ledger_plan(SRC5, rows, 2026, 9)
    assert plan.skipped[0].ticket_no == "(不完整行)"  # 缺开始时间无法拼日期标识
    rows2 = [_row5(guardian="王五", level="A证", end=None, op_type="受限空间")]
    plan2 = build_ledger_plan(SRC5, rows2, 2026, 9)
    assert plan2.skipped[0].ticket_no == "09-01 王五"


# ═══════════════════════════════════════════════════════════════════
# 四部(datetime 日期列 + 多段时间段文本 + 监护证类别列)
# ═══════════════════════════════════════════════════════════════════


def test_dept4_multi_segment_interval_passed_to_engine() -> None:
    """多段行:空档(11:30→13:10=1.67h)经 interval_hours 交给引擎扣除(不重复扣午休)。"""
    plan = build_ledger_plan(SRC4, [_row4()], 2026, 9)
    assert plan.matched_tickets == 1
    record = plan.records[0]
    assert record.interval_hours == "1.67"
    assert record.start_time.startswith("2026-09-10T09:15")
    assert record.end_time.startswith("2026-09-10T17:10")
    assert record.guardian_level == "A证"  # 监护证类别列
    assert record.department == "提炼工程四部"


def test_dept4_single_segment_and_level_last_wins() -> None:
    rows = [
        _row4(guardian="陈涛", level="B证", period="09:20-17:19"),
        _row4(guardian="陈涛", level="A证", day="2026-09-11", period="08:30-11:30"),
    ]
    plan = build_ledger_plan(SRC4, rows, 2026, 9)
    assert plan.matched_tickets == 2
    assert all(r.guardian_level == "A证" for r in plan.records)  # 最后登记为准
    assert plan.records[0].interval_hours == "0"  # 单段 → 引擎自行扣午休


def test_dept4_name_trailing_whitespace_normalized() -> None:
    rows = [_row4(guardian="欧阳佳华\n", period="15:40-18:00")]
    plan = build_ledger_plan(SRC4, rows, 2026, 9)
    assert plan.records[0].guardian_name == "欧阳佳华"


def test_dept4_unparseable_period_skipped() -> None:
    rows = [
        _row4(period="待定"),          # 有时间段文本但解析不出 → 时间段无法解析
        _row4(period=""),              # 无时间段 → 缺少开始时间
        _row4(day="2026-08-31", period="09:00-11:00"),  # 非目标月 → 忽略
    ]
    plan = build_ledger_plan(SRC4, rows, 2026, 9)
    assert plan.matched_tickets == 0
    assert sorted(s.reason for s in plan.skipped) == ["时间段无法解析", "缺少开始时间"]
    assert plan.skipped[0].ticket_no == "09-10 李小兰"  # 行标识带日期


# ═══════════════════════════════════════════════════════════════════
# 六部(文本日期列 + MultiSelect 类型 + 无级别列)
# ═══════════════════════════════════════════════════════════════════


def test_dept6_all_unmatched_due_to_no_level_column() -> None:
    """六部表无级别列 → 全员进待核对并按 A 证暂计(与平台源口径一致)。"""
    rows = [
        _row6(guardian="池守城", day="2026.09.10", period="09:10-17:10"),
        _row6(guardian="彭飞琼", day="2026.09.10", period="08：35-18：30"),
    ]
    plan = build_ledger_plan(SRC6, rows, 2026, 9)
    assert plan.matched_tickets == 2
    assert all(r.guardian_level == "A证" for r in plan.records)
    assert plan.unmatched_tickets == 2
    assert {u.name for u in plan.unmatched} == {"池守城", "彭飞琼"}


def test_dept6_multi_type_row_picks_highest_rate() -> None:
    """MultiSelect 组合行(动火|受限)按该级别单价最高类型计费(同价取第一个)。"""
    rows = [
        _row6(guardian="肖剑", op_types=["动火作业", "受限空间"], day="2026.07.09",
              period="09:05-17:00"),
    ]
    plan = build_ledger_plan(SRC6, rows, 2026, 7)
    assert plan.records[0].operation_type == "动火作业"  # 同价 10 元 → 表内第一个

    rows2 = [
        _row6(guardian="肖剑", op_types=["高处作业", "动火作业"], day="2026.09.11",
              period="09:05-17:00"),
    ]
    plan2 = build_ledger_plan(SRC6, rows2, 2026, 9)
    assert plan2.records[0].operation_type == "动火作业"  # 10 元 > 5 元


def test_dept6_text_date_month_filter() -> None:
    """月份按文本日期归集;年份笔误(2056)行非目标年直接忽略,不进任何清单。"""
    rows = [
        _row6(guardian="高梦媛", day="2026.09.03", period="9:00～18:00"),   # 计入
        _row6(guardian="高梦媛", day="2026.08.31", period="9:00～18:00"),   # 8 月忽略
        _row6(guardian="彭飞琼", day="2056.09.12", period="09:35-17:35"),   # 年份笔误忽略
    ]
    plan = build_ledger_plan(SRC6, rows, 2026, 9)
    assert plan.matched_tickets == 1
    assert plan.skipped == []


def test_dept6_date_range_uses_first_date() -> None:
    """日期区间(09.06-09.07)取首日为基准;时段未跨零点则按同日处理。"""
    rows = [_row6(guardian="罗利梅", op_types=["高处作业"], day="2026.09.06-2026.09.07",
                  period="08：30-18：00")]
    plan = build_ledger_plan(SRC6, rows, 2026, 9)
    assert plan.matched_tickets == 1
    assert plan.records[0].start_time.startswith("2026-09-06T08:30")
    assert plan.records[0].end_time.startswith("2026-09-06T18:00")


def test_dept6_missing_level_none_not_counted() -> None:
    """uncertified_level=None → 六部无级别列全行不计入,只留待核对名单。"""
    rows = [_row6(guardian="池守城", day="2026.09.10", period="09:10-17:10")]
    plan = build_ledger_plan(SRC6, rows, 2026, 9, uncertified_level=None)
    assert plan.matched_tickets == 0
    assert plan.unmatched_tickets == 1
