"""打卡核对工具：刷卡/请假/加班文件读取测试（行为与原 attendance-checking 脚本一致）。"""

from datetime import datetime
from typing import Any

import openpyxl

from app.modules.toolbox.tools.attendance_check._files import (
    group_attendance_by_employee,
    group_leave_by_employee,
    group_overtime_by_employee,
    load_attendance_records,
    load_leave_records,
    load_overtime_records,
)


def _write_csv(path: str, text: str, encoding: str) -> None:
    with open(path, "w", encoding=encoding, newline="") as f:
        f.write(text)


def _write_xlsx(path: str, rows: list[list[Any]]) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    if ws is None:
        return
    for row in rows:
        ws.append(row)
    wb.save(path)
    wb.close()


def test_load_attendance_records_csv_utf8_bom() -> None:
    csv_path = "/tmp/att_swipe_bom.csv"
    _write_csv(
        csv_path,
        "员工工号,姓名,刷卡时间\n111001830,张三,2026-08-01 08:25:00\n111001831,李四,2026-08-01 17:35:00\n",
        "utf-8-sig",
    )
    records = load_attendance_records(csv_path)
    assert records == [
        {"工号": "111001830", "姓名": "张三", "刷卡时间": datetime(2026, 8, 1, 8, 25)},
        {"工号": "111001831", "姓名": "李四", "刷卡时间": datetime(2026, 8, 1, 17, 35)},
    ]


def test_load_attendance_records_csv_gbk_fallback() -> None:
    csv_path = "/tmp/att_swipe_gbk.csv"
    _write_csv(
        csv_path,
        "员工工号,姓名,刷卡时间\n111001830,张三,2026-08-01 08:25:00\n",
        "gbk",
    )
    records = load_attendance_records(csv_path)
    assert records == [
        {"工号": "111001830", "姓名": "张三", "刷卡时间": datetime(2026, 8, 1, 8, 25)},
    ]


def test_load_attendance_records_skips_invalid_rows_and_converts_id() -> None:
    # 工号为数字（float）时转整数字符串；无工号或无刷卡时间的行跳过；无法解析的刷卡时间跳过
    xlsx_path = "/tmp/att_swipe.xlsx"
    _write_xlsx(
        xlsx_path,
        [
            ["员工工号", "姓名", "刷卡时间"],
            [111001830, "张三", "2026-08-01 08:25:00"],
            [None, "无工号", "2026-08-01 08:25:00"],
            [111001831, "无时间", None],
            [111001832, "坏时间", "not-a-time"],
        ],
    )
    records = load_attendance_records(xlsx_path)
    assert records == [
        {"工号": "111001830", "姓名": "张三", "刷卡时间": datetime(2026, 8, 1, 8, 25)},
    ]


def test_group_attendance_by_employee() -> None:
    r1 = {"工号": "1", "姓名": "张三", "刷卡时间": datetime(2026, 8, 1, 8, 25)}
    r2 = {"工号": "1", "姓名": "张三", "刷卡时间": datetime(2026, 8, 1, 17, 35)}
    r3 = {"工号": "2", "姓名": "李四", "刷卡时间": datetime(2026, 8, 1, 8, 30)}
    grouped = group_attendance_by_employee([r1, r2, r3])
    assert grouped == {"1": [r1, r2], "2": [r3]}


def test_load_leave_records() -> None:
    xlsx_path = "/tmp/att_leave.xlsx"
    _write_xlsx(
        xlsx_path,
        [
            ["工号", "请假类型", "开始时间", "结束时间"],
            [111001830, "事假", "2026-08-01 08:30:00", "2026-08-01 12:00:00"],
            [111001830, "调休", "2026-08-01 13:30:00", "2026-08-01 18:00:00"],
            [111001831, "事假", None, "2026-08-01 12:00:00"],
        ],
    )
    records = load_leave_records(xlsx_path)
    assert records == [
        {"工号": "111001830", "开始时间": datetime(2026, 8, 1, 8, 30), "结束时间": datetime(2026, 8, 1, 12, 0), "请假类型": "事假"},
        {"工号": "111001830", "开始时间": datetime(2026, 8, 1, 13, 30), "结束时间": datetime(2026, 8, 1, 18, 0), "请假类型": "调休"},
    ]


def test_group_leave_by_employee() -> None:
    l1 = {"工号": "1", "开始时间": datetime(2026, 8, 1, 8, 0), "结束时间": datetime(2026, 8, 1, 12, 0), "请假类型": "事假"}
    l2 = {"工号": "2", "开始时间": datetime(2026, 8, 1, 8, 0), "结束时间": datetime(2026, 8, 1, 12, 0), "请假类型": "事假"}
    assert group_leave_by_employee([l1, l2]) == {"1": [l1], "2": [l2]}


def test_load_overtime_records_skips_empty_and_parses() -> None:
    xlsx_path = "/tmp/att_overtime.xlsx"
    _write_xlsx(
        xlsx_path,
        [
            ["工号", "姓名", "开始时间", "结束时间"],
            [111001830, "张三", "2026-08-01 18:00:00", "2026-08-01 23:00:00"],
            [111001831, "李四", "", ""],
            [111001832, "王五", "2026-08-02 07:00:00", "2026-08-02 09:00:00"],
        ],
    )
    records = load_overtime_records(xlsx_path)
    assert records == [
        {"工号": "111001830", "姓名": "张三", "开始时间": datetime(2026, 8, 1, 18, 0), "结束时间": datetime(2026, 8, 1, 23, 0)},
        {"工号": "111001832", "姓名": "王五", "开始时间": datetime(2026, 8, 2, 7, 0), "结束时间": datetime(2026, 8, 2, 9, 0)},
    ]


def test_group_overtime_by_employee_merges_adjacent() -> None:
    # 相邻记录（上一条结束 == 下一条开始）合并为一段（跨天拆分）
    o1 = {"工号": "1", "姓名": "张三", "开始时间": datetime(2026, 8, 1, 18, 0), "结束时间": datetime(2026, 8, 2, 0, 0)}
    o2 = {"工号": "1", "姓名": "张三", "开始时间": datetime(2026, 8, 2, 0, 0), "结束时间": datetime(2026, 8, 2, 9, 0)}
    o3 = {"工号": "1", "姓名": "张三", "开始时间": datetime(2026, 8, 3, 18, 0), "结束时间": datetime(2026, 8, 3, 21, 0)}
    grouped = group_overtime_by_employee([o2, o3, o1])
    assert grouped == {
        "1": [
            {"工号": "1", "姓名": "张三", "开始时间": datetime(2026, 8, 1, 18, 0), "结束时间": datetime(2026, 8, 2, 9, 0)},
            o3,
        ]
    }
