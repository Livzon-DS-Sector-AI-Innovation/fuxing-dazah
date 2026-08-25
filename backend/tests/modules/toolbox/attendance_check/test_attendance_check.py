"""打卡核对工具测试：核心核对逻辑迁移自 attendance-checking 项目的 test_check_attendance.py。

核对逻辑（check_attendance_for_day）必须与原脚本行为完全一致，测试场景原样保留。
"""

from datetime import date, datetime
from typing import Any

from app.modules.toolbox.tools.attendance_check._core import check_attendance_for_day


def make_swipe(emp_id: str, name: str, dt: datetime) -> dict[str, Any]:
    return {"工号": emp_id, "姓名": name, "刷卡时间": dt}


def make_leave(emp_id: str, start: datetime, end: datetime, leave_type: str = "事假") -> dict[str, Any]:
    return {"工号": emp_id, "开始时间": start, "结束时间": end, "请假类型": leave_type}


def make_overtime(emp_id: str, name: str, start: datetime, end: datetime) -> dict[str, Any]:
    return {"工号": emp_id, "姓名": name, "开始时间": start, "结束时间": end}


def test_late_and_early() -> None:
    """测试迟到和早退场景"""

    # 标准班次: 08:30上班, 17:30下班, 无休息时间
    shift: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "17:30",
        "休息时间": None,
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 15  # 15分钟缓冲

    # 场景1: 正常打卡
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 正常打卡应无异常

    # 场景2: 迟到5分钟 (08:35打卡)
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 35)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 5, "早退": None, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected  # 迟到5分钟

    # 场景3: 早退3分钟 (17:27打卡)
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 27)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_2: dict[str, Any] = {"异常类型": ["早退"], "缺卡": None, "迟到": None, "早退": 3, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected_2  # 早退3分钟

    # 场景4: 迟到10分钟 + 早退5分钟
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 40)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 25)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_3: dict[str, Any] = {"异常类型": ["迟到", "早退"], "缺卡": None, "迟到": 10, "早退": 5, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected_3  # 迟到10分钟+早退5分钟

    # 场景5: 缺卡 (无打卡记录)
    swipes = []
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_4: dict[str, Any] = {"异常类型": ["旷工"], "缺卡": ["上班卡", "下班卡"], "迟到": None, "早退": None, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected_4  # 缺卡-上下班都缺→旷工

    # 场景6: 只有上班卡，缺下班卡
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_5: dict[str, Any] = {"异常类型": ["缺卡"], "缺卡": ["下班卡"], "迟到": None, "早退": None, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected_5  # 缺卡-只缺下班卡


def test_leave_coverage() -> None:
    """测试请假覆盖场景"""

    # 标准班次: 08:30上班, 17:30下班, 休息时间 12:00-13:30
    shift: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "17:30",
        "休息时间": "12:00-13:30",
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 15

    # 场景1: 请假早上 (08:30-12:00), 上班卡13:24 → 正常 (12:00-13:30是休息)
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 13, 24)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    leaves = [
        make_leave("001", datetime(2026, 5, 14, 8, 30), datetime(2026, 5, 14, 12, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 请假早上+休息时间覆盖,13:24打卡正常

    # 场景2: 请假早上 (08:30-12:00), 上班卡13:34 → 迟到4分钟
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 13, 34)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    leaves = [
        make_leave("001", datetime(2026, 5, 14, 8, 30), datetime(2026, 5, 14, 12, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    expected_6: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 4, "早退": None, "应上班时间": "13:30", "应下班时间": "17:30"}
    assert result == expected_6  # 请假早上+休息覆盖,13:34打卡迟到4分钟

    # 场景3: 请全天假, 无打卡 → 正常
    swipes = []
    leaves = [
        make_leave("001", datetime(2026, 5, 14, 8, 30), datetime(2026, 5, 14, 17, 30)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 请全天假无打卡正常

    # 场景4: 请全天假, 有打卡 → 正常 (有打卡但被覆盖)
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 10, 0)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 15, 0)),
    ]
    leaves = [
        make_leave("001", datetime(2026, 5, 14, 8, 30), datetime(2026, 5, 14, 17, 30)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 请全天假有打卡正常

    # 场景5: 请假→休息→请假链式覆盖 (bug修复: 第二段请假之前被忽略)
    # 请假8:30-12:00(覆盖上班) + 休息12:00-13:30 + 请假13:30-14:30(调休)
    # → reasonable_in 应迭代推进到 14:30, 14:21打卡提前9分钟, 正常
    shift5: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "18:00",
        "休息时间": "12:00-13:30",
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 14, 21)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 11)),
    ]
    leaves = [
        make_leave("001", datetime(2026, 5, 14, 8, 30), datetime(2026, 5, 14, 12, 0)),
        make_leave("001", datetime(2026, 5, 14, 13, 30), datetime(2026, 5, 14, 14, 30)),
    ]
    result = check_attendance_for_day(shift5, swipes, leaves, check_date, offset)
    assert result is None  # 请假→休息→请假链式覆盖,14:21打卡应正常(应上班14:30)

    # 场景6: 全天请假拆分为上午+下午(被午休隔开), 无打卡 → 应正常
    # bug: 之前全天判断只检查单个leave区间, 两个被午休隔开的leave无法检测为全天
    # 严晶晶(111001830) 2026-07-02 真实案例
    check_date2 = date(2026, 7, 2)
    shift2: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "18:00",
        "休息时间": "12:00-13:30",
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }
    swipes2: list[dict[str, Any]] = []  # 全天调休, 无打卡
    leaves2 = [
        make_leave("001", datetime(2026, 7, 2, 8, 30), datetime(2026, 7, 2, 12, 0), "调休"),
        make_leave("001", datetime(2026, 7, 2, 13, 30), datetime(2026, 7, 2, 18, 0), "调休"),
    ]
    result = check_attendance_for_day(shift2, swipes2, leaves2, check_date2, 180)
    assert result is None  # 全天请假拆分为上午+下午(午休隔开),无打卡应正常


def test_morning_leave_no_clock_in() -> None:
    """测试早上请假后无上班卡的场景（用户提出的bug场景）"""

    # 标准班次: 08:30上班, 18:00下班, 休息时间 12:00-13:30
    shift: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "18:00",
        "休息时间": "12:00-13:30",
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 30
    leaves = [
        make_leave("001", datetime(2026, 5, 14, 8, 30), datetime(2026, 5, 14, 12, 0)),
    ]

    # 场景1: 请假8:30-12:00, 只有下班卡17:50, 无上班卡 → 缺上班卡+早退10分钟
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 50)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    expected_7: dict[str, Any] = {"异常类型": ["缺卡", "早退"], "缺卡": ["上班卡"], "迟到": None, "早退": 10, "应上班时间": "13:30", "应下班时间": "18:00"}
    assert result == expected_7  # 请假早上+无上班卡+下班卡17:50→缺上班卡+早退10分钟

    # 场景2: 请假8:30-12:00, 上班卡13:20, 下班卡18:00 → 正常
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 13, 20)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 请假早上+13:20上班卡+18:00下班卡→正常

    # 场景3: 请假8:30-12:00, 上班卡13:35, 下班卡18:00 → 迟到5分钟
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 13, 35)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    expected_8: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 5, "早退": None, "应上班时间": "13:30", "应下班时间": "18:00"}
    assert result == expected_8  # 请假早上+13:35上班卡+18:00下班卡→迟到5分钟


def test_cross_day_shift() -> None:
    """测试跨天班次场景"""

    # 夜班: 18:00上班, 次日08:00下班, 休息时间 00:00-00:30
    shift: dict[str, Any] = {
        "班次类型": "夜班",
        "考勤对应标识": "正常",
        "班次编码": "NIGHT",
        "应上班时间": "18:00",
        "应下班时间": "08:00",
        "休息时间": "00:00-00:30",
        "工作日工作时段": ["18:00-次日08:00"],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)  # 5月14日晚上18:00开始
    offset = 15

    # 场景1: 正常打卡 (18:00上班, 次日08:00下班)
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 14, 17, 55)),  # 上班卡
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),    # 下班卡(次日)
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 跨天班次正常打卡

    # 场景2: 迟到10分钟 (18:10上班)
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 14, 18, 10)),
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_9: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 10, "早退": None, "应上班时间": "18:00", "应下班时间": "08:00"}
    assert result == expected_9  # 跨天班次迟到10分钟

    # 场景3: 早退5分钟 (07:55下班)
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 14, 17, 55)),
        make_swipe("002", "李四", datetime(2026, 5, 15, 7, 55)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_10: dict[str, Any] = {"异常类型": ["早退"], "缺卡": None, "迟到": None, "早退": 5, "应上班时间": "18:00", "应下班时间": "08:00"}
    assert result == expected_10  # 跨天班次早退5分钟


def test_cross_day_shift_with_leave() -> None:
    """测试跨天班次请假场景"""

    # 夜班: 18:00上班, 次日08:00下班, 休息时间 00:00-00:30
    shift: dict[str, Any] = {
        "班次类型": "夜班",
        "考勤对应标识": "正常",
        "班次编码": "NIGHT",
        "应上班时间": "18:00",
        "应下班时间": "08:00",
        "休息时间": "00:00-00:30",
        "工作日工作时段": ["18:00-次日08:00"],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)  # 5月14日晚上18:00开始
    offset = 15

    # 场景1: 请假18:00-次日02:00, 上班卡01:55 → 正常 (在请假+休息覆盖内)
    # 请假覆盖: 18:00-02:00, 休息覆盖: 00:00-00:30 (包含在请假内)
    # 合理上班时间: 02:00
    # 01:55 < 02:00, 在覆盖范围内, 正常
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 15, 1, 55)),  # 上班卡
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),   # 下班卡
    ]
    leaves = [
        make_leave("002", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 15, 2, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 跨天请假18:00-02:00,上班卡01:55正常

    # 场景2: 请假18:00-次日02:00, 上班卡02:04 → 迟到4分钟
    # 合理上班时间: 02:00
    # 02:04 > 02:00, 迟到4分钟
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 15, 2, 4)),   # 上班卡
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),   # 下班卡
    ]
    leaves = [
        make_leave("002", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 15, 2, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    expected_11: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 4, "早退": None, "应上班时间": "02:00", "应下班时间": "08:00"}
    assert result == expected_11  # 跨天请假18:00-02:00,上班卡02:04迟到4分钟

    # 场景3: 请假18:00-次日02:00, 上班卡02:00 → 正常 (刚好在边界)
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 15, 2, 0)),   # 上班卡
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),   # 下班卡
    ]
    leaves = [
        make_leave("002", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 15, 2, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 跨天请假18:00-02:00,上班卡02:00正常

    # 场景4: 请假次日00:00-06:00, 上班卡05:55 → 正常
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 15, 5, 55)),  # 上班卡
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),   # 下班卡
    ]
    leaves = [
        make_leave("002", datetime(2026, 5, 15, 0, 0), datetime(2026, 5, 15, 6, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    assert result is None  # 跨天请假00:00-06:00,上班卡05:55正常

    # 场景5: 请假次日00:00-06:00, 上班卡06:05 → 迟到5分钟
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 15, 6, 5)),   # 上班卡
        make_swipe("002", "李四", datetime(2026, 5, 15, 8, 5)),   # 下班卡
    ]
    leaves = [
        make_leave("002", datetime(2026, 5, 15, 0, 0), datetime(2026, 5, 15, 6, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    expected_12: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 5, "早退": None, "应上班时间": "06:00", "应下班时间": "08:00"}
    assert result == expected_12  # 跨天请假00:00-06:00,上班卡06:05迟到5分钟

    # 场景6: 请假在班次前半段(当天20:00开始), 无打卡 → 旷工
    # 请假在班次开始后不久即开始，不应推后reasonable_in，只应提前reasonable_out
    # 修复前Bug: reasonable_in被错误推到请假结束后(次日08:15)，上班卡被误判为"覆盖"
    swipes = []
    leaves = [
        make_leave("002", datetime(2026, 5, 14, 20, 0), datetime(2026, 5, 16, 8, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, leaves, check_date, offset)
    expected_13: dict[str, Any] = {"异常类型": ["旷工"], "缺卡": ["上班卡", "下班卡"], "迟到": None, "早退": None, "应上班时间": "18:00", "应下班时间": "20:00"}
    assert result == expected_13  # 跨天请假当天20:00开始,无打卡→旷工(上班卡不应被覆盖)


def test_duplicate_swipes() -> None:
    """测试重复打卡场景"""

    shift: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "17:30",
        "休息时间": None,
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 15

    # 场景1: 多次打卡, 有准时卡则优先选取
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 7, 0)),   # 太早
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 20)),  # 接近
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 28)),  # 最接近(不晚于8:30)
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 25)), # 接近
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 32)), # 最接近(不早于17:30)
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 0)),  # 太晚
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 重复打卡取最接近的正常打卡

    # 场景2: 上班8:25和8:31打卡 → 优先选8:25(不晚于8:30), 正常
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 31)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 上班8:25+8:31打卡→选8:25,正常

    # 场景3: 下班17:29和17:35打卡 → 优先选17:35(不早于17:30), 正常
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 29)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 下班17:29+17:35打卡→选17:35,正常

    # 场景4: 上班只有迟到卡 8:32和8:35 → 取最早的8:32, 迟到2分钟
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 32)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 35)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 35)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_14: dict[str, Any] = {"异常类型": ["迟到"], "缺卡": None, "迟到": 2, "早退": None, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected_14  # 上班只有迟到卡8:32+8:35→取最早8:32,迟到2分钟

    # 场景5: 下班只有早退卡 17:25和17:28 → 取最晚的17:28, 早退2分钟
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 28)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_15: dict[str, Any] = {"异常类型": ["早退"], "缺卡": None, "迟到": None, "早退": 2, "应上班时间": "08:30", "应下班时间": "17:30"}
    assert result == expected_15  # 下班只有早退卡17:25+17:28→取最晚17:28,早退2分钟


def test_rest_day() -> None:
    """测试休息日"""

    shift: dict[str, Any] = {
        "班次类型": "休息",
        "考勤对应标识": "休",
        "班次编码": "W-REST",
        "应上班时间": None,
        "应下班时间": None,
        "休息时间": None,
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 15

    # 休息日无论有无打卡都正常
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 10, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 休息日有打卡正常

    result = check_attendance_for_day(shift, [], [], check_date, offset)
    assert result is None  # 休息日无打卡正常


def test_late_clock_out() -> None:
    """测试下班时间7:30，打卡时间7:39的场景"""

    shift: dict[str, Any] = {
        "班次类型": "早班",
        "考勤对应标识": "正常",
        "班次编码": "EARLY",
        "应上班时间": "06:00",
        "应下班时间": "07:30",
        "休息时间": None,
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 15

    # 场景1: 下班时间7:30，打卡7:39，在有效窗口[7:15, 7:45]内，不算早退
    swipes = [
        make_swipe("003", "王五", datetime(2026, 5, 14, 6, 0)),   # 上班卡正常
        make_swipe("003", "王五", datetime(2026, 5, 14, 7, 39)),  # 下班卡7:39
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    assert result is None  # 下班7:30打卡7:39应正常(在有效窗口内)

    # 场景2: 下班时间7:30，打卡7:14，在有效窗口[7:15, 7:45]外，缺卡
    swipes = [
        make_swipe("003", "王五", datetime(2026, 5, 14, 6, 0)),   # 上班卡正常
        make_swipe("003", "王五", datetime(2026, 5, 14, 7, 14)),  # 下班卡7:14
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_16: dict[str, Any] = {"异常类型": ["缺卡"], "缺卡": ["下班卡"], "迟到": None, "早退": None, "应上班时间": "06:00", "应下班时间": "07:30"}
    assert result == expected_16  # 下班7:30打卡7:14应缺卡(在有效窗口外)

    # 场景3: 下班时间7:30，打卡7:20，在有效窗口内，早退10分钟
    swipes = [
        make_swipe("003", "王五", datetime(2026, 5, 14, 6, 0)),   # 上班卡正常
        make_swipe("003", "王五", datetime(2026, 5, 14, 7, 20)),  # 下班卡7:20
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset)
    expected_17: dict[str, Any] = {"异常类型": ["早退"], "缺卡": None, "迟到": None, "早退": 10, "应上班时间": "06:00", "应下班时间": "07:30"}
    assert result == expected_17  # 下班7:30打卡7:20应早退10分钟


def test_overtime() -> None:
    """测试加班登记场景"""

    # 标准班次: 08:30上班, 18:00下班
    shift: dict[str, Any] = {
        "班次类型": "标准班次",
        "考勤对应标识": "正常",
        "班次编码": "STD",
        "应上班时间": "08:30",
        "应下班时间": "18:00",
        "休息时间": None,
        "工作日工作时段": [],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date = date(2026, 5, 14)
    offset = 30
    gap = 60

    # 场景1: 加班18:00-23:00, gap=60 → 应下班时间变为23:00, 下班卡23:05正常
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 23, 5)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 14, 23, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    assert result is None  # 加班18:00-23:00,下班卡23:05应正常

    # 场景2: 加班18:00-23:00, gap=60 → 应下班时间变为23:00, 下班卡22:30 → 正常
    # 打卡核对基准是班次下班时间18:00, 22:30在18:00之后, 不判早退
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 22, 30)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 14, 23, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    assert result is None  # 加班18:00-23:00,下班卡22:30应正常(核对基准18:00)

    # 场景3: 加班6:00-7:00, gap=60 → 间隔90>m, 忽略加班
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 5)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 6, 0), datetime(2026, 5, 14, 7, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    assert result is None  # 加班6:00-7:00间隔90>m,忽略,正常

    # 场景4: 加班6:30-8:00, gap=60 → 间隔30≤m, 应上班时间变为6:30
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 6, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 5)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 6, 30), datetime(2026, 5, 14, 8, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    assert result is None  # 加班6:30-8:00间隔30≤m,上班卡6:25应正常

    # 场景5: 加班6:30-8:00, gap=60 → 应上班时间变为6:30, 上班卡7:00 → 正常
    # 打卡核对基准是班次上班时间8:30, 7:00在8:30之前, 不判迟到
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 7, 0)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 5)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 6, 30), datetime(2026, 5, 14, 8, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    assert result is None  # 加班6:30-8:00,上班卡7:00应正常(核对基准08:30)

    # === 跨天班次测试 ===
    shift_cross: dict[str, Any] = {
        "班次类型": "夜班",
        "考勤对应标识": "正常",
        "班次编码": "NIGHT",
        "应上班时间": "19:00",
        "应下班时间": "07:00",
        "休息时间": None,
        "工作日工作时段": ["19:00-次日07:00"],
        "备注": None,
        "班次类型-考勤标识": None,
    }

    check_date_cross = date(2026, 5, 14)  # 5月14日19:00开始

    # 场景6: 跨天班次, day2加班07:00-09:00 → 应下班时间变为09:00
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 14, 18, 55)),
        make_swipe("002", "李四", datetime(2026, 5, 15, 9, 5)),
    ]
    overtimes = [
        make_overtime("002", "李四", datetime(2026, 5, 15, 7, 0), datetime(2026, 5, 15, 9, 0)),
    ]
    result = check_attendance_for_day(shift_cross, swipes, [], check_date_cross, offset, overtimes, gap)
    assert result is None  # 跨天班次day2加班07:00-09:00,下班卡09:05应正常

    # 场景7: 跨天班次, day2加班05:00-07:00 → reasonable_in不变(19:00), reasonable_out不变(07:00)
    # 05:05的打卡在下班卡窗口[06:30,07:30]之外,缺下班卡
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 14, 18, 55)),
        make_swipe("002", "李四", datetime(2026, 5, 15, 5, 5)),
    ]
    overtimes = [
        make_overtime("002", "李四", datetime(2026, 5, 15, 5, 0), datetime(2026, 5, 15, 7, 0)),
    ]
    result = check_attendance_for_day(shift_cross, swipes, [], check_date_cross, offset, overtimes, gap)
    expected_18: dict[str, Any] = {"异常类型": ["缺卡"], "缺卡": ["下班卡"], "迟到": None, "早退": None, "应上班时间": "19:00", "应下班时间": "07:00"}
    assert result == expected_18  # 跨天班次day2加班05:00-07:00,05:05不在下班窗口内→缺下班卡

    # 场景7b: 跨天班次, day2加班05:00-07:00, 下班卡07:05正常
    swipes = [
        make_swipe("002", "李四", datetime(2026, 5, 14, 18, 55)),
        make_swipe("002", "李四", datetime(2026, 5, 15, 7, 5)),
    ]
    overtimes = [
        make_overtime("002", "李四", datetime(2026, 5, 15, 5, 0), datetime(2026, 5, 15, 7, 0)),
    ]
    result = check_attendance_for_day(shift_cross, swipes, [], check_date_cross, offset, overtimes, gap)
    assert result is None  # 跨天班次day2加班05:00-07:00,下班卡07:05应正常

    # 场景8: 无加班记录时 overtime_records=None 应正常工作
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 18, 5)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, None, 0)
    assert result is None  # 无加班记录时应正常工作

    # 场景9: 加班18:00-21:00, 下班卡19:00 → 应正常 (核对基准18:00, 不判早退)
    # 用户场景: 加班超出offset窗口, 但实际有打卡
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 19, 0)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 14, 21, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    assert result is None  # 加班18:00-21:00,下班卡19:00应正常(核对基准18:00)

    # 场景10: 加班18:00-21:00, 下班卡17:50 → 早退10分钟 (核对基准18:00, 应下班时间21:00)
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
        make_swipe("001", "张三", datetime(2026, 5, 14, 17, 50)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 14, 21, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    expected_19: dict[str, Any] = {"异常类型": ["早退"], "缺卡": None, "迟到": None, "早退": 10, "应上班时间": "08:30", "应下班时间": "21:00"}
    assert result == expected_19  # 加班18:00-21:00,下班卡17:50应早退10分钟(应下班时间仍为21:00)

    # 场景11: 加班18:00-21:00, 无下班卡 → 缺下班卡 (加班不消除缺卡)
    swipes = [
        make_swipe("001", "张三", datetime(2026, 5, 14, 8, 25)),
    ]
    overtimes = [
        make_overtime("001", "张三", datetime(2026, 5, 14, 18, 0), datetime(2026, 5, 14, 21, 0)),
    ]
    result = check_attendance_for_day(shift, swipes, [], check_date, offset, overtimes, gap)
    expected_20: dict[str, Any] = {"异常类型": ["缺卡"], "缺卡": ["下班卡"], "迟到": None, "早退": None, "应上班时间": "08:30", "应下班时间": "21:00"}
    assert result == expected_20  # 加班18:00-21:00,无下班卡应缺下班卡(应下班时间21:00)
