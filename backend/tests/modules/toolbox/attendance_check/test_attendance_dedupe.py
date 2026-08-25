"""打卡核对工具：误报消除逻辑测试（行为与原 attendance-checking 脚本一致）。"""

from datetime import datetime
from typing import Any

from app.modules.toolbox.tools.attendance_check._dedupe import (
    remove_actual_clock_anomalies,
    remove_duty_anomalies,
    remove_false_early_leave,
    remove_overtime_missing_clock,
)


def _emp(emp_id: str, anomalies: list[dict[str, Any]]) -> dict[str, Any]:
    return {"员工姓名": f"员工{emp_id}", "工号": emp_id, "异常": anomalies}


def _anomaly(date_str: str, types: list[str], missing: list[str] | None, **extra: Any) -> dict[str, Any]:
    return {
        "日期": date_str,
        "异常类型": types,
        "缺卡": missing,
        "迟到": None,
        "早退": None,
        "应上班时间": "08:30",
        "应下班时间": "17:30",
        **extra,
    }


def test_remove_duty_anomalies() -> None:
    result = [
        _emp("1", [_anomaly("2026-08-01", ["缺卡"], ["下班卡"])]),
        _emp("2", [_anomaly("2026-08-02", ["缺卡"], ["下班卡"])]),
    ]
    duty_records = [{"工号": "1", "调休日期": "2026-08-01"}]
    processed, removed = remove_duty_anomalies(result, duty_records)
    assert removed == 1
    # 员工记录保留，异常列表被清空（"过滤异常为空的记录"在主流程中处理）
    assert processed == [
        _emp("1", []),
        _emp("2", [_anomaly("2026-08-02", ["缺卡"], ["下班卡"])]),
    ]


def test_remove_actual_clock_anomalies_full_remove() -> None:
    result = [_emp("1", [_anomaly("2026-08-01", ["缺卡"], ["下班卡"])])]
    actual_records = [{"工号": "1", "异常日期": "2026-08-01", "备注": "缺下班卡，实际有打卡"}]
    processed, removed = remove_actual_clock_anomalies(result, actual_records)
    assert removed == 1
    assert processed == [_emp("1", [])]  # 异常全消，异常列表为空


def test_remove_actual_clock_anomalies_partial_remove() -> None:
    result = [_emp("1", [_anomaly("2026-08-01", ["旷工"], ["上班卡", "下班卡"])])]
    actual_records = [{"工号": "1", "异常日期": "2026-08-01", "备注": "缺下班卡，实际有打卡"}]
    processed, removed = remove_actual_clock_anomalies(result, actual_records)
    assert removed == 1
    # 部分缺卡被消除："旷工" → "缺卡"，只缺上班卡
    assert processed[0]["异常"] == [_anomaly("2026-08-01", ["缺卡"], ["上班卡"])]


def test_remove_overtime_missing_clock() -> None:
    # 应下班 17:30，下班后 12h 内（次日 03:00）有刷卡 → 消除缺下班卡
    swipe = {"工号": "1", "姓名": "x", "刷卡时间": datetime(2026, 8, 2, 3, 0)}
    result = [_emp("1", [_anomaly("2026-08-01", ["缺卡"], ["下班卡"])])]
    processed, removed = remove_overtime_missing_clock(result, {"1": [swipe]})
    assert removed == 1
    assert processed == [_emp("1", [])]


def test_remove_overtime_missing_clock_out_of_window() -> None:
    # 下班后 12h 外（次日 08:00）才有刷卡 → 不消除
    swipe = {"工号": "1", "姓名": "x", "刷卡时间": datetime(2026, 8, 2, 8, 0)}
    result = [_emp("1", [_anomaly("2026-08-01", ["缺卡"], ["下班卡"])])]
    processed, removed = remove_overtime_missing_clock(result, {"1": [swipe]})
    assert removed == 0
    assert processed == result


def test_remove_false_early_leave() -> None:
    # 早退异常，但应下班后 6h 内有刷卡 → 误报早退消除
    swipe = {"工号": "1", "姓名": "x", "刷卡时间": datetime(2026, 8, 1, 20, 0)}
    result = [_emp("1", [_anomaly("2026-08-01", ["早退"], None, 早退=10)])]
    processed, removed = remove_false_early_leave(result, {"1": [swipe]})
    assert removed == 1
    assert processed == [_emp("1", [])]


def test_remove_false_early_leave_no_swipe_keeps() -> None:
    result = [_emp("1", [_anomaly("2026-08-01", ["早退"], None, 早退=10)])]
    processed, removed = remove_false_early_leave(result, {"1": []})
    assert removed == 0
    assert processed == result
