"""打卡核对核心逻辑。

原样迁移自 attendance-checking 项目 scripts/utils.py 的「班次与打卡核对」段，
核对逻辑不可做任何变更。飞书数据获取与文件读取见 _attendance_feishu / _attendance_files。
"""

import calendar
from datetime import date, datetime, time, timedelta
from typing import Any, cast


def parse_time_str(time_str: str | None) -> time | None:
    """解析时间字符串，如 '9:00', '18:00', '7:30'"""
    if not time_str:
        return None
    time_str = time_str.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    return None


def parse_rest_time(rest_str: str | None) -> list[tuple[time, time]]:
    """解析休息时间字段，如 '12:00-13:30' → [(time(12,0), time(13,30))]
    支持多段用 ';' 分隔，如 '12:00-13:30;17:00-17:30'
    """
    if not rest_str or not isinstance(rest_str, str):
        return []
    # 全角冒号替换为半角
    rest_str = rest_str.replace("：", ":")
    results = []
    for segment in rest_str.split(";"):
        segment = segment.strip()
        if not segment or "-" not in segment:
            continue
        parts = segment.split("-", 1)
        if len(parts) != 2:
            continue
        t_start = parse_time_str(parts[0])
        t_end = parse_time_str(parts[1])
        if t_start and t_end:
            results.append((t_start, t_end))
    return results


def merge_time_intervals(intervals: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """合并重叠/相邻的时间区间"""
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    for current in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        curr_start, curr_end = current
        if curr_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, curr_end))
        else:
            merged.append(current)
    return merged


def _is_time_covered(t: datetime, merged: list[tuple[datetime, datetime]]) -> bool:
    """检查时间点是否在任何覆盖区间内"""
    for start, end in merged:
        if start <= t < end:
            return True
    return False


def is_cross_day_shift(shift: dict[str, Any]) -> bool:
    """判断班次是否跨天"""
    # 方法1：工作日工作时段含"次日"
    periods = shift.get("工作日工作时段", [])
    if isinstance(periods, list):
        for p in periods:
            if "次日" in str(p):
                return True
    # 方法2：应上班时间 > 应下班时间（如 18:00 > 7:30）
    t1 = parse_time_str(shift.get("应上班时间"))
    t2 = parse_time_str(shift.get("应下班时间"))
    if t1 and t2 and t1 > t2:
        return True
    return False


def is_rest_day(shift: dict[str, Any]) -> bool:
    """判断是否为休息日"""
    tag = shift.get("考勤对应标识", "")
    code = shift.get("班次编码", "")
    return tag in ["休", "占"] or code in ["W-REST", "W-PLACEHOLDER"]


def check_attendance_for_day(
    shift: dict[str, Any],
    swipe_events: list[dict[str, Any]],
    leave_records: list[dict[str, Any]],
    check_date: date,
    offset_minutes: int,
    overtime_records: list[dict[str, Any]] | None = None,
    overtime_gap_minutes: int = 0,
) -> dict[str, Any] | None:
    """
    核对某人某天的刷卡情况。

    返回:
        None = 正常（休息日、无班次、或被覆盖）
        dict = {"异常类型": [...], "缺卡": [...] | None, "迟到": int|None, "早退": int|None}
    """
    if is_rest_day(shift):
        return None

    t1 = parse_time_str(shift.get("应上班时间"))
    t2 = parse_time_str(shift.get("应下班时间"))
    if t1 is None or t2 is None:
        return None

    cross_day = is_cross_day_shift(shift)
    offset = timedelta(minutes=offset_minutes)

    # 构建时间锚点
    t1_dt = datetime.combine(check_date, t1)
    t2_dt = datetime.combine(check_date + timedelta(days=1), t2) if cross_day else datetime.combine(check_date, t2)

    # 基础有效窗口
    base_clock_in_start = t1_dt - offset
    base_clock_in_end = t1_dt + offset
    base_clock_out_start = t2_dt - offset
    base_clock_out_end = t2_dt + offset

    # 构建覆盖区间（请假 + 休息）
    # 解析休息时间
    rest_periods = parse_rest_time(shift.get("休息时间"))
    rest_intervals = []
    for rs, re in rest_periods:
        rs_dt = datetime.combine(check_date, rs)
        re_dt = datetime.combine(check_date, re)
        # 跨天班次且休息时间 < 应上班时间 → 视为次日休息
        if cross_day and rs < t1:
            rs_dt += timedelta(days=1)
            re_dt += timedelta(days=1)
        if re_dt < rs_dt:
            re_dt += timedelta(days=1)
        rest_intervals.append((rs_dt, re_dt))

    # 获取请假记录，clamp 到班次时间范围
    leave_intervals = []
    for lv in leave_records:
        if lv["开始时间"] <= t2_dt + offset and lv["结束时间"] >= t1_dt - offset:
            lv_start = max(lv["开始时间"], t1_dt - offset)
            lv_end = min(lv["结束时间"], t2_dt + offset)
            if lv_start < lv_end:
                leave_intervals.append((lv_start, lv_end))

    # 合并相邻/重叠的请假区间，避免 reasonable_out 计算错误
    leave_intervals = merge_time_intervals(leave_intervals)

    # 合并所有覆盖区间（请假+休息），用于全天判断和窗口扩展
    all_coverage = rest_intervals + leave_intervals
    merged_coverage = merge_time_intervals(all_coverage)

    # 全天覆盖判断：请假+休息合并后完全覆盖班次 → 跳过
    for cov_start, cov_end in merged_coverage:
        if cov_start <= t1_dt and cov_end >= t2_dt:
            return None

    # 计算合理上下班时间（仅基于请假区间，休息时间不影响合理时间）
    # 如果请假结束时间落在休息时间内，则合理上班时间顺延到休息结束
    # 迭代直到 stable：处理请假→休息→请假链式覆盖
    reasonable_in = t1_dt
    while True:
        old = reasonable_in
        for lv_start, lv_end in leave_intervals:
            if lv_start <= reasonable_in < lv_end:
                if lv_end > reasonable_in:
                    reasonable_in = lv_end
            elif cross_day and lv_start > t1_dt and lv_start < t2_dt and lv_start.date() > check_date:
                if lv_end > reasonable_in:
                    reasonable_in = lv_end
        for rs_start, rs_end in rest_intervals:
            if rs_start <= reasonable_in < rs_end:
                reasonable_in = rs_end
                break
        if reasonable_in == old:
            break

    reasonable_out = t2_dt
    for lv_start, lv_end in reversed(leave_intervals):
        if lv_end >= t2_dt and lv_start < t2_dt:
            if lv_start < reasonable_out:
                reasonable_out = lv_start
    # 如果 reasonable_out 落在休息时间内，前移到休息开始
    for rs_start, rs_end in rest_intervals:
        if rs_start < reasonable_out <= rs_end:
            reasonable_out = rs_start
            break

    # 保存请假+休息调整后的基准时间（不含加班），用于打卡早晚判断
    check_in_ref = reasonable_in
    check_out_ref = reasonable_out

    # 加班调整：扩展 reasonable_in / reasonable_out（仅影响应上下班时间展示和有效窗口扩展）
    if overtime_records and overtime_gap_minutes > 0:
        gap = timedelta(minutes=overtime_gap_minutes)
        if cross_day:
            # 跨天班次：day2 加班记录可能在班次前(凌晨)或班次后(白天)
            for ot in overtime_records:
                ot_start = ot["开始时间"]
                ot_end = ot["结束时间"]
                if ot_start.date() == check_date + timedelta(days=1):
                    # 加班在班次后 (开始时间在 [t2, t2+m])
                    if t2_dt <= ot_start <= t2_dt + gap:
                        if ot_end > reasonable_out:
                            reasonable_out = ot_end
                    # 加班在班次前 (结束时间在 [t2-m, t2]) — 凌晨加班延伸到班次结束
                    elif t2_dt - gap <= ot_end <= t2_dt:
                        if ot_start < reasonable_in:
                            reasonable_in = ot_start
        else:
            # 同天班次
            for ot in overtime_records:
                ot_start = ot["开始时间"]
                ot_end = ot["结束时间"]
                if ot_start.date() == check_date:
                    # 加班在班次后 (开始时间在 [t2, t2+m])
                    if t2_dt <= ot_start <= t2_dt + gap:
                        if ot_end > reasonable_out:
                            reasonable_out = ot_end
                    # 加班在班次前 (结束时间在 [t1-m, t1])
                    elif t1_dt - gap <= ot_end <= t1_dt:
                        if ot_start < reasonable_in:
                            reasonable_in = ot_start

    # 扩展有效窗口：如果有覆盖，窗口扩展到覆盖结束时间 + 缓冲
    # 上班卡有效窗口: [min(t1-n, reasonable_in - n), max(t1+n, reasonable_in + n)]
    clock_in_start = min(base_clock_in_start, reasonable_in - offset)
    clock_in_end = max(base_clock_in_end, reasonable_in + offset)
    # 下班卡有效窗口: [min(t2-n, reasonable_out - n), max(t2+n, reasonable_out + n)]
    # 窗口起点基于 check_out_ref（不含加班），避免正常打卡被排除在窗口外
    if check_out_ref > t2_dt:
        clock_out_start = t2_dt
    else:
        clock_out_start = min(base_clock_out_start, check_out_ref - offset)
    # 窗口终点仍用 reasonable_out（含加班），确保加班时段打卡能被匹配到
    clock_out_end = max(base_clock_out_end, reasonable_out + offset)

    # 收集刷卡记录
    day_swipes = get_swipe_events_on_date(swipe_events, check_date)
    if cross_day or reasonable_out.date() > check_date:
        next_day_swipes = get_swipe_events_on_date(swipe_events, check_date + timedelta(days=1))
        all_swipes = day_swipes + next_day_swipes
    else:
        all_swipes = day_swipes

    # 选择最佳上班卡：取最接近 reasonable_in 的卡
    on_time_in = []
    late_in = []
    for sw in all_swipes:
        if clock_in_start <= sw <= clock_in_end:
            if sw <= t1_dt:
                on_time_in.append(sw)
            else:
                late_in.append(sw)
    if on_time_in:
        best_in = max(on_time_in)
    elif late_in:
        best_in = min(late_in)
    else:
        best_in = None

    # 选择最佳下班卡：优先选合理时间之后的卡（取最接近的），若没有则选最接近的早退卡
    after_out = []
    before_out = []
    for sw in all_swipes:
        if clock_out_start <= sw <= clock_out_end:
            if sw >= check_out_ref:
                after_out.append(sw)
            else:
                before_out.append(sw)
    if after_out:
        best_out = min(after_out, key=lambda x: abs(x - check_out_ref))
    elif before_out:
        best_out = min(before_out, key=lambda x: abs(x - check_out_ref))
    else:
        best_out = None

    # 分类异常
    anomaly_types = []
    missing_types = []
    late_minutes = None
    early_minutes = None

    # 上班卡检查：只看请假是否覆盖，休息时间不算
    if best_in is None:
        if not _is_time_covered(check_in_ref, leave_intervals):
            missing_types.append("上班卡")
            anomaly_types.append("缺卡")
    else:
        late_minutes = int((best_in - check_in_ref).total_seconds() // 60)
        if late_minutes > 0:
            anomaly_types.append("迟到")
        else:
            late_minutes = None

    # 下班卡检查：leave 开始时间用严格小于（leave 从 check_out_ref 开始不算覆盖）
    if best_out is None:
        covered_by_leave = any(
            lv_start < check_out_ref <= lv_end for lv_start, lv_end in leave_intervals
        )
        if not covered_by_leave:
            missing_types.append("下班卡")
            if "缺卡" not in anomaly_types:
                anomaly_types.append("缺卡")
    else:
        early_minutes = int((check_out_ref - best_out).total_seconds() // 60)
        if early_minutes > 0:
            anomaly_types.append("早退")
        else:
            early_minutes = None

    if not anomaly_types:
        return None
    # 同时缺上下班卡 → "缺卡"改为"旷工"
    if "上班卡" in missing_types and "下班卡" in missing_types:
        anomaly_types = ["旷工" if t == "缺卡" else t for t in anomaly_types]
    return {
        "异常类型": anomaly_types,
        "缺卡": missing_types if missing_types else None,
        "迟到": late_minutes,
        "早退": early_minutes,
        "应上班时间": reasonable_in.strftime("%H:%M"),
        "应下班时间": reasonable_out.strftime("%H:%M"),
    }


# ── 公共流程 ──────────────────────────────────────────────

def format_date_range(start: date, end: date) -> str:
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()} ~ {end.isoformat()}"


def months_in_range(start: date, end: date) -> list[str]:
    """日期范围涉及的月份列表（YYYY-MM），用于值班/实际打卡记录按月拉取"""
    months: list[str] = []
    d = start.replace(day=1)
    while d <= end:
        months.append(f"{d.year:04d}-{d.month:02d}")
        if d.month == 12:
            d = d.replace(year=d.year + 1, month=1)
        else:
            d = d.replace(month=d.month + 1)
    return months


def find_employee(employees: list[dict[str, Any]], identifier: str) -> dict[str, Any] | None:
    """按工号或姓名查找员工"""
    for e in employees:
        if e["工号"] == identifier or e["姓名"] == identifier:
            return e
    return None


def get_shift_for_day(employee: dict[str, Any], day: int) -> dict[str, Any] | None:
    """获取员工某天的班次，统一使用 str 类型的 key"""
    return cast(dict[str, Any] | None, employee["每日班次"].get(str(day)))


def check_employee_month(employee: dict[str, Any], year: int, month: int,
                         swipe_events: list[dict[str, Any]], leave_records: list[dict[str, Any]],
                         offset: int, overtime_records: list[dict[str, Any]] | None = None,
                         overtime_gap_minutes: int = 0) -> list[dict[str, Any]]:
    """核对某员工整月的异常情况"""
    days_in_month = calendar.monthrange(year, month)[1]
    anomaly_list = []
    for day in range(1, days_in_month + 1):
        check_date = date(year, month, day)
        shift = get_shift_for_day(employee, day)
        if not shift:
            continue
        result = check_attendance_for_day(shift, swipe_events, leave_records, check_date, offset,
                                          overtime_records, overtime_gap_minutes)
        if result:
            anomaly_list.append({
                "日期": check_date.isoformat(),
                "异常类型": result["异常类型"],
                "缺卡": result["缺卡"],
                "迟到": result["迟到"],
                "早退": result["早退"],
                "应上班时间": result["应上班时间"],
                "应下班时间": result["应下班时间"],
            })
    return anomaly_list


def get_swipe_events_on_date(events: list[dict[str, Any]], target: date) -> list[datetime]:
    """获取某人某天的所有刷卡时间"""
    return [r["刷卡时间"] for r in events if r["刷卡时间"].date() == target]
