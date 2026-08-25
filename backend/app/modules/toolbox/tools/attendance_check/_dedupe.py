"""打卡核对工具：误报异常消除。

原样迁移自 attendance-checking 项目 scripts/remove_duty_missing_clock.py 的
消除函数，消除逻辑不可做任何变更。
"""

from datetime import datetime, timedelta
from typing import Any

from ._core import parse_time_str


def remove_duty_anomalies(result_data: list[dict[str, Any]], duty_records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """消除值班/调休日的所有异常（缺卡、迟到、早退全部消除）"""
    duty_index = set()
    for rec in duty_records:
        duty_index.add((rec["工号"], rec["调休日期"]))

    print(f"值班记录数量: {len(duty_index)}")

    removed_count = 0

    for emp in result_data:
        emp_id = emp.get("工号")
        anomalies = emp.get("异常", [])

        if not anomalies:
            continue

        new_anomalies = []
        for anomaly in anomalies:
            date_str = anomaly.get("日期")

            if (emp_id, date_str) in duty_index:
                types = anomaly.get("异常类型", [])
                print(f"消除值班异常: 工号={emp_id}, 日期={date_str}, 异常类型={types}")
                removed_count += 1
                continue

            new_anomalies.append(anomaly)

        emp["异常"] = new_anomalies

    return result_data, removed_count


def remove_actual_clock_anomalies(result_data: list[dict[str, Any]], actual_records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """消除实际有打卡但超出有效时间的异常

    Args:
        actual_records: 包含工号、异常日期、备注（缺上班卡/缺下班卡，实际有打卡）
    """
    # 构建索引：(工号, 日期, 类型) -> True
    # 类型: "上班卡" 或 "下班卡"
    actual_index = set()
    for rec in actual_records:
        remark = rec["备注"]
        if "缺上班卡" in remark:
            actual_index.add((rec["工号"], rec["异常日期"], "上班卡"))
        elif "缺下班卡" in remark:
            actual_index.add((rec["工号"], rec["异常日期"], "下班卡"))

    print(f"实际打卡记录数量: {len(actual_index)}")

    removed_count = 0

    for emp in result_data:
        emp_id = emp.get("工号")
        anomalies = emp.get("异常", [])

        if not anomalies:
            continue

        new_anomalies = []
        for anomaly in anomalies:
            date_str = anomaly.get("日期")
            missing = anomaly.get("缺卡")

            if not missing:
                new_anomalies.append(anomaly)
                continue

            # 检查是否有实际打卡记录匹配
            new_missing = []
            for m in missing:
                if (emp_id, date_str, m) in actual_index:
                    print(f"消除实际打卡异常: 工号={emp_id}, 日期={date_str}, 类型=缺{m}")
                    removed_count += 1
                else:
                    new_missing.append(m)

            if not new_missing:
                # 所有缺卡都被消除，跳过这条异常
                continue

            if len(new_missing) < len(missing):
                # 部分缺卡被消除
                anomaly["缺卡"] = new_missing
                if "旷工" in anomaly.get("异常类型", []):
                    anomaly["异常类型"] = ["缺卡"]

            new_anomalies.append(anomaly)

        emp["异常"] = new_anomalies

    return result_data, removed_count


def remove_overtime_missing_clock(
    result_data: list[dict[str, Any]],
    swipe_by_emp: dict[str, list[dict[str, Any]]],
    hours: int = 12,
) -> tuple[list[dict[str, Any]], int]:
    """消除加班导致的缺下班卡异常

    如果某人有缺下班卡异常，但在应下班时间后 hours 小时内还有打卡记录，
    说明是加班超出 offset_minutes 窗口导致的误报，消除该异常。
    """
    removed_count = 0

    for emp in result_data:
        emp_id = emp.get("工号")
        if not emp_id:
            continue
        anomalies = emp.get("异常", [])
        swipes = swipe_by_emp.get(emp_id, [])

        if not anomalies or not swipes:
            continue

        new_anomalies = []
        for anomaly in anomalies:
            missing = anomaly.get("缺卡")
            if not missing or "下班卡" not in missing:
                new_anomalies.append(anomaly)
                continue

            date_str = anomaly.get("日期")
            off_time_str = anomaly.get("应下班时间")
            on_time_str = anomaly.get("应上班时间")

            if not date_str or not off_time_str:
                new_anomalies.append(anomaly)
                continue

            check_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            off_time = parse_time_str(off_time_str)
            on_time = parse_time_str(on_time_str) if on_time_str else None

            if not off_time:
                new_anomalies.append(anomaly)
                continue

            # 跨天判断：上班时间 > 下班时间（如 18:00 > 08:00）
            if on_time and on_time > off_time:
                expected_off = datetime.combine(check_date + timedelta(days=1), off_time)
            else:
                expected_off = datetime.combine(check_date, off_time)

            window_end = expected_off + timedelta(hours=hours)

            # 检查是否有刷卡记录在 [expected_off, expected_off + hours] 内
            has_late_swipe = any(
                expected_off <= s["刷卡时间"] <= window_end
                for s in swipes
            )

            if has_late_swipe:
                new_missing = [m for m in missing if m != "下班卡"]
                if new_missing:
                    anomaly["缺卡"] = new_missing
                    if "旷工" in anomaly.get("异常类型", []):
                        anomaly["异常类型"] = ["缺卡"]
                    new_anomalies.append(anomaly)
                # 全部缺卡被消除 → 跳过该异常
                print(f"消除加班缺下班卡: 工号={emp_id}, 日期={date_str}, 应下班={off_time_str}")
                removed_count += 1
            else:
                new_anomalies.append(anomaly)

        emp["异常"] = new_anomalies

    return result_data, removed_count


def remove_false_early_leave(
    result_data: list[dict[str, Any]],
    swipe_by_emp: dict[str, list[dict[str, Any]]],
    hours: int = 6,
) -> tuple[list[dict[str, Any]], int]:
    """消除误报的早退异常

    如果某人有早退异常，但在应下班时间后 hours 小时内还有打卡记录，
    说明是工作时间内的误打卡导致的误报，消除该早退异常。
    """
    removed_count = 0

    for emp in result_data:
        emp_id = emp.get("工号")
        if not emp_id:
            continue
        anomalies = emp.get("异常", [])
        swipes = swipe_by_emp.get(emp_id, [])

        if not anomalies or not swipes:
            continue

        new_anomalies = []
        for anomaly in anomalies:
            anomaly_types = anomaly.get("异常类型", [])
            if "早退" not in anomaly_types:
                new_anomalies.append(anomaly)
                continue

            date_str = anomaly.get("日期")
            off_time_str = anomaly.get("应下班时间")
            on_time_str = anomaly.get("应上班时间")

            if not date_str or not off_time_str:
                new_anomalies.append(anomaly)
                continue

            check_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            off_time = parse_time_str(off_time_str)
            on_time = parse_time_str(on_time_str) if on_time_str else None

            if not off_time:
                new_anomalies.append(anomaly)
                continue

            # 跨天判断：上班时间 > 下班时间（如 18:00 > 08:00）
            if on_time and on_time > off_time:
                expected_off = datetime.combine(check_date + timedelta(days=1), off_time)
            else:
                expected_off = datetime.combine(check_date, off_time)

            window_end = expected_off + timedelta(hours=hours)

            # 检查是否有刷卡记录在 [expected_off, expected_off + hours] 内
            has_late_swipe = any(
                expected_off <= s["刷卡时间"] <= window_end
                for s in swipes
            )

            if has_late_swipe:
                new_types = [t for t in anomaly_types if t != "早退"]
                anomaly["早退"] = None
                if new_types:
                    anomaly["异常类型"] = new_types
                    new_anomalies.append(anomaly)
                # 异常类型列表为空 → 整条跳过
                print(f"消除误报早退: 工号={emp_id}, 日期={date_str}, 应下班={off_time_str}")
                removed_count += 1
            else:
                new_anomalies.append(anomaly)

        emp["异常"] = new_anomalies

    return result_data, removed_count
