"""打卡核对工具：飞书数据获取与核对上下文加载。

迁移自 attendance-checking 项目 scripts/utils.py 的飞书数据获取段与
scripts/remove_duty_missing_clock.py 的值班/实际打卡记录获取，
获取与解析逻辑不可做任何变更。工具配置从 attendance_config.json 读取。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import lark_oapi as lark
from lark_oapi.api.bitable.v1 import ListAppTableRecordRequest

from ._files import (
    _extract_link_record_ids,
    _extract_lookup_text,
    _first,
    group_attendance_by_employee,
    group_leave_by_employee,
    group_overtime_by_employee,
    load_attendance_records,
    load_leave_records,
    load_overtime_records,
)

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_attendance_config() -> dict[str, Any]:
    """加载打卡核对工具配置（feishu 凭据、多维表 ID、核对参数）"""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config: dict[str, Any] = json.load(f)
        return config


# ── 飞书数据获取 ──────────────────────────────────────────────

def create_feishu_client(config: dict[str, Any]) -> lark.Client:
    return (
        lark.Client.builder()
        .app_id(config["feishu"]["app_id"])
        .app_secret(config["feishu"]["app_secret"])
        .domain("https://open.feishu.cn")
        .build()
    )


def list_bitable_records(client: lark.Client, app_token: str, table_id: str, filter_str: str = "") -> list[dict[str, Any]]:
    """分页获取多维表全部记录，返回 [{record_id, fields}, ...]"""
    all_items = []
    page_token = ""
    while True:
        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(500)
        )
        if page_token:
            builder = builder.page_token(page_token)
        if filter_str:
            builder = builder.filter(filter_str)
        resp = client.bitable.v1.app_table_record.list(builder.build())
        if not resp.success():
            raise RuntimeError(f"获取多维表记录失败: code={resp.code}, msg={resp.msg}")
        for item in resp.data.items:
            all_items.append({"record_id": item.record_id, "fields": item.fields})
        if not resp.data.has_more:
            break
        page_token = resp.data.page_token
    return all_items


def _fetch_shift_map(client: lark.Client, app_token: str, shift_table_id: str) -> dict[str, Any]:
    """获取班次信息表，返回 record_id → 班次详情 的映射"""
    shift_records = list_bitable_records(client, app_token, shift_table_id)
    shift_map = {}
    for rec in shift_records:
        fields = rec["fields"]
        shift_map[rec["record_id"]] = {
            "班次类型": _first(fields.get("班次类型")),
            "考勤对应标识": _first(fields.get("考勤对应标识")),
            "班次编码": _first(fields.get("班次编码")),
            "应上班时间": _first(fields.get("应上班时间")),
            "应下班时间": _first(fields.get("应下班时间")),
            "休息时间": _first(fields.get("休息时间（不计入出勤时间）")),
            "工作日工作时段": fields.get("工作日工作时段", []),
            "备注": _first(fields.get("备注")),
            "班次类型-考勤标识": _first(fields.get("班次类型-考勤标识")),
        }
    return shift_map


def _parse_schedule_records(schedule_records: list[dict[str, Any]], shift_map: dict[str, Any]) -> list[dict[str, Any]]:
    """解析排班记录为员工列表，每人包含每日班次映射"""
    employees = []
    for rec in schedule_records:
        fields = rec["fields"]
        name = _first(fields.get("姓名"), "")
        employee_id = _extract_lookup_text(fields.get("工号"), "")
        rec_month = fields.get("月", 0)
        try:
            rec_month = int(rec_month)
        except (ValueError, TypeError):
            rec_month = 0

        daily_shifts = {}
        for day in range(1, 32):
            day_field = f"{day}日"
            link_val = fields.get(day_field)
            record_ids = _extract_link_record_ids(link_val)
            for rid in record_ids:
                if rid in shift_map:
                    daily_shifts[str(day)] = shift_map[rid]
                    break

        employees.append({
            "姓名": name,
            "工号": str(employee_id),
            "月": rec_month,
            "每日班次": daily_shifts,
        })
    return employees


def _fetch_schedule_for_month(client: lark.Client, app_token: str, schedule_table_id: str, shift_map: dict[str, Any], month: int) -> list[dict[str, Any]]:
    """获取指定月份的排班数据并解析为员工列表"""
    filter_str = f'CurrentValue.[月]={month}' if month > 0 else ""
    schedule_records = list_bitable_records(client, app_token, schedule_table_id, filter_str)
    return _parse_schedule_records(schedule_records, shift_map)


def fetch_whitelist(config: dict[str, Any]) -> set[str]:
    """从飞书获取免核对打卡白名单，返回工号集合"""
    client = create_feishu_client(config)
    app_token = config["bitable"]["app_token"]
    table_id = config["bitable"]["whitelist_table_id"]
    records = list_bitable_records(client, app_token, table_id)
    ids = set()
    for rec in records:
        fields = rec["fields"]
        emp_id = fields.get("工号")
        if emp_id is not None:
            emp_id = str(int(emp_id)) if isinstance(emp_id, (int, float)) else str(emp_id)
            ids.add(emp_id)
    return ids


# ── 值班/实际打卡记录 ─────────────────────────────────────────

def _fetch_records(client: lark.Client, app_token: str, table_id: str) -> list[dict[str, Any]]:
    """分页获取多维表全部记录"""
    all_items = []
    page_token = ""
    while True:
        builder = (
            ListAppTableRecordRequest.builder()
            .app_token(app_token)
            .table_id(table_id)
            .page_size(500)
        )
        if page_token:
            builder = builder.page_token(page_token)

        resp = client.bitable.v1.app_table_record.list(builder.build())
        if not resp.success():
            raise RuntimeError(f"获取多维表记录失败: code={resp.code}, msg={resp.msg}")

        if resp.data is None or resp.data.items is None:
            break

        for item in resp.data.items:
            all_items.append(item.fields)

        if not resp.data.has_more:
            break
        page_token = resp.data.page_token

    return all_items


def _parse_date(ts: Any) -> tuple[datetime, str] | None:
    """解析时间戳为 (datetime对象, 日期字符串)"""
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts / 1000)
    else:
        dt = datetime.strptime(str(ts)[:10], "%Y-%m-%d")
    return dt, dt.strftime("%Y-%m-%d")


def fetch_duty_records(client: lark.Client, app_token: str, table_id: str, month: str) -> list[dict[str, Any]]:
    """获取指定月份的值班记录

    同时读取"调休日期（异常日期）"和"值班日期"两个字段。
    值班当天或调休当天如果出现缺下班卡异常都应被消除。

    Returns:
        值班记录列表，每条记录包含工号和调休日期
    """
    year, mon = map(int, month.split("-"))

    all_fields = _fetch_records(client, app_token, table_id)
    result = []
    seen = set()

    for fields in all_fields:
        emp_id = fields.get("工号")
        if not emp_id:
            continue
        emp_id_str = str(emp_id)

        for field_name in ("调休日期（异常日期）", "值班日期"):
            ts = fields.get(field_name)
            if not ts:
                continue
            parsed = _parse_date(ts)
            if not parsed or parsed[0].year != year or parsed[0].month != mon:
                continue
            key = (emp_id_str, parsed[1])
            if key not in seen:
                seen.add(key)
                result.append({"工号": emp_id_str, "调休日期": parsed[1]})

    return result


def fetch_actual_clock_records(client: lark.Client, app_token: str, table_id: str, month: str) -> list[dict[str, Any]]:
    """获取实际有打卡但超出有效时间的记录

    Returns:
        记录列表，每条包含工号、异常日期、备注类型
    """
    year, mon = map(int, month.split("-"))

    all_fields = _fetch_records(client, app_token, table_id)
    result = []

    for fields in all_fields:
        emp_id = fields.get("工号")
        anomaly_date_ts = fields.get("异常日期")
        remark = fields.get("备注")

        if not emp_id or not anomaly_date_ts or not remark:
            continue

        # 备注是数组格式，取第一个
        if isinstance(remark, list):
            remark = remark[0] if remark else None

        if not remark:
            continue

        parsed = _parse_date(anomaly_date_ts)
        if parsed and parsed[0].year == year and parsed[0].month == mon:
            result.append({
                "工号": str(emp_id),
                "异常日期": parsed[1],
                "备注": remark
            })

    return result


# ── 公共流程 ──────────────────────────────────────────────

def load_check_context(config: dict[str, Any], attendance_file: str, leave_file: str,
                       start_date: str = "", end_date: str = "",
                       overtime_file: str = "") -> dict[str, Any]:
    """加载核对所需的全部数据：排班、刷卡记录、请假记录、加班记录"""
    # 支持日期范围：获取涉及的所有月份的排班数据
    if start_date and end_date:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        # 直接计算涉及的月份集合，跳到每月1号
        months = set()
        d = start
        while d <= end:
            months.add(d.month)
            if d.month < 12:
                d = datetime(d.year, d.month + 1, 1)
            else:
                d = datetime(d.year + 1, 1, 1)
        # 班次信息表只需获取一次，排班表按月筛选
        client = create_feishu_client(config)
        app_token = config["bitable"]["app_token"]
        shift_map = _fetch_shift_map(client, app_token, config["bitable"]["shift_table_id"])
        all_employees = []
        for m in months:
            schedule_data = _fetch_schedule_for_month(client, app_token, config["bitable"]["schedule_table_id"], shift_map, m)
            all_employees.extend(schedule_data)
        employees = all_employees
    else:
        employees = []

    whitelist = fetch_whitelist(config)
    print(f"白名单人数: {len(whitelist)}，核对人数: {len(employees)}")
    attendance_records = load_attendance_records(attendance_file)
    leave_records = load_leave_records(leave_file)
    swipe_by_emp = group_attendance_by_employee(attendance_records)
    leave_by_emp = group_leave_by_employee(leave_records)
    offset = config.get("offset_minutes", 30)
    overtime_gap = config.get("overtime_gap_minutes", 0)
    overtime_by_emp = {}
    if overtime_file:
        overtime_records = load_overtime_records(overtime_file)
        overtime_by_emp = group_overtime_by_employee(overtime_records)
        print(f"加班记录数: {len(overtime_records)}，涉及员工: {len(overtime_by_emp)}")
    return {
        "config": config,
        "employees": employees,
        "whitelist": whitelist,
        "swipe_by_emp": swipe_by_emp,
        "leave_by_emp": leave_by_emp,
        "offset": offset,
        "overtime_by_emp": overtime_by_emp,
        "overtime_gap_minutes": overtime_gap,
    }
