"""打卡核对工具：刷卡核对 → 消除误报 → 写入多维表 三步流程。

流程迁移自 attendance-checking 项目的三个脚本：
scripts/check_all_month.py → scripts/remove_duty_missing_clock.py → scripts/write_to_bitable.py。
前两步核对/消除逻辑与原脚本一致；写入步骤前先清空多维表旧结果。
每步执行结果返回原脚本 print 输出（text）与结构化数据。
"""

import asyncio
import calendar
import contextlib
import io
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.modules.toolbox import storage
from app.modules.toolbox.registry import (
    ConfigField,
    StepContext,
    ToolError,
    ToolInput,
    ToolStep,
    tool,
)

from ._bitable import (
    delete_all_records,
    flatten_check_result,
    write_records_to_bitable,
)
from ._core import (
    check_attendance_for_day,
    format_date_range,
    get_shift_for_day,
    months_in_range,
)
from ._dedupe import (
    remove_actual_clock_anomalies,
    remove_duty_anomalies,
    remove_false_early_leave,
    remove_overtime_missing_clock,
)
from ._feishu import (
    create_feishu_client,
    fetch_actual_clock_records,
    fetch_duty_records,
    load_check_context,
)
from ._files import (
    group_attendance_by_employee,
    load_attendance_records,
)


def _capture(func: Callable[..., Any], *args: Any) -> tuple[Any, str]:
    """执行同步函数并捕获其 print 输出，返回 (结果, 输出文本)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = func(*args)
    return result, buf.getvalue()


def _run_check_sync(
    config: dict[str, Any],
    attendance_file: str,
    leave_file: str,
    overtime_file: str,
    month: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    if month:
        dt = datetime.strptime(month, "%Y-%m")
        start = dt.replace(day=1).date()
        last_day = calendar.monthrange(dt.year, dt.month)[1]
        end = dt.replace(day=last_day).date()
    else:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()

    ctx = load_check_context(config, attendance_file, leave_file,
                             start_date=start.isoformat(), end_date=end.isoformat(),
                             overtime_file=overtime_file)

    result = []
    for employee in ctx["employees"]:
        if employee["工号"] in ctx["whitelist"]:
            continue
        emp_swipes = ctx["swipe_by_emp"].get(employee["工号"], [])
        emp_leaves = ctx["leave_by_emp"].get(employee["工号"], [])
        emp_overtimes = ctx["overtime_by_emp"].get(employee["工号"], [])

        anomaly_list = []
        current = start
        while current <= end:
            shift = get_shift_for_day(employee, current.day)
            if shift:
                day_result = check_attendance_for_day(shift, emp_swipes, emp_leaves, current, ctx["offset"],
                                                      emp_overtimes, ctx["overtime_gap_minutes"])
                if day_result:
                    anomaly_list.append({
                        "日期": current.isoformat(),
                        "异常类型": day_result["异常类型"],
                        "缺卡": day_result["缺卡"],
                        "迟到": day_result["迟到"],
                        "早退": day_result["早退"],
                        "应上班时间": day_result["应上班时间"],
                        "应下班时间": day_result["应下班时间"],
                    })
            current += timedelta(days=1)

        if anomaly_list:
            result.append({
                "员工姓名": employee["姓名"],
                "工号": employee["工号"],
                "异常": anomaly_list,
            })

    date_range = format_date_range(start, end)
    print(f"{date_range} 共有 {len(result)} 人存在异常记录")
    return {
        "result": result,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "date_range": date_range,
        "anomaly_count": len(result),
    }


def _run_dedupe_sync(
    config: dict[str, Any],
    result_data: list[dict[str, Any]],
    attendance_file: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    client = create_feishu_client(config)
    duty_app_token = config["bitable"]["duty_app_token"]
    duty_table_id = config["bitable"]["duty_table_id"]
    actual_table_id = config["bitable"]["actual_clock_table_id"]

    # 日期范围涉及的每个月份分别获取值班/实际打卡记录（原脚本为单月参数）
    months = months_in_range(
        datetime.strptime(start_date, "%Y-%m-%d").date(),
        datetime.strptime(end_date, "%Y-%m-%d").date(),
    )
    duty_records = []
    for m in months:
        print(f"正在获取 {m} 的值班记录...")
        recs = fetch_duty_records(client, duty_app_token, duty_table_id, m)
        print(f"获取到 {len(recs)} 条值班记录")
        duty_records.extend(recs)
    actual_records = []
    for m in months:
        print(f"正在获取 {m} 的实际打卡记录...")
        recs = fetch_actual_clock_records(client, duty_app_token, actual_table_id, m)
        print(f"获取到 {len(recs)} 条实际打卡记录")
        actual_records.extend(recs)

    print(f"读取到 {len(result_data)} 条员工记录")

    # 加载刷卡记录（用于加班缺下班卡判断）
    print(f"正在加载刷卡记录: {attendance_file}")
    attendance_records = load_attendance_records(attendance_file)
    swipe_by_emp = group_attendance_by_employee(attendance_records)
    print(f"刷卡记录: {len(attendance_records)} 条, {len(swipe_by_emp)} 人")

    # 消除加班缺下班卡异常（应下班+12h内有打卡）
    processed_data, overtime_removed = remove_overtime_missing_clock(result_data, swipe_by_emp)
    print(f"消除了 {overtime_removed} 条加班缺下班卡异常")

    # 消除误报早退异常（应下班+6h内有打卡）
    processed_data, early_removed = remove_false_early_leave(processed_data, swipe_by_emp)
    print(f"消除了 {early_removed} 条误报早退异常")

    # 消除值班缺下班卡异常
    processed_data, duty_removed = remove_duty_anomalies(processed_data, duty_records)
    print(f"消除了 {duty_removed} 条值班缺下班卡异常")

    # 消除实际有打卡异常
    processed_data, actual_removed = remove_actual_clock_anomalies(processed_data, actual_records)
    print(f"消除了 {actual_removed} 条实际打卡异常")

    # 过滤掉异常为空的记录
    processed_data = [emp for emp in processed_data if emp.get("异常")]
    print(f"处理后剩余 {len(processed_data)} 人有异常记录")

    return processed_data


def _run_write_sync(config: dict[str, Any], check_result: list[dict[str, Any]]) -> dict[str, Any]:
    client = create_feishu_client(config)
    app_token = config["bitable"]["app_token"]
    table_id = config["bitable"]["attendance_result_table_id"]

    # 先清空多维表旧结果，再写入本次核对结果
    deleted = delete_all_records(client, app_token, table_id)
    print(f"已删除 {deleted} 条旧记录")

    if not check_result:
        print("核对结果为空，无需写入")
        return {"written": 0, "deleted": deleted}

    # 扁平化
    field_records = flatten_check_result(check_result)
    print(f"共 {len(field_records)} 条异常记录待写入")

    written = write_records_to_bitable(client, app_token, table_id, field_records)
    print(f"写入完成，共 {written} 条记录")
    return {"written": written, "deleted": deleted}


def _save_result_json(execution_id: str, result: list[dict[str, Any]], filename: str) -> dict[str, Any]:
    file_id, _ = storage.save_upload(
        execution_id, filename,
        json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"),
    )
    return {"file_id": file_id, "filename": filename}


@tool(
    id="attendance-check",
    name="打卡核对",
    description="上传刷卡/请假/加班记录，核对指定日期范围的打卡异常，消除误报后写入飞书多维表",
    image=None,
    config_schema=[
        ConfigField(key="feishu.app_id", label="飞书应用 ID", type="text", section="飞书应用", required=True),
        ConfigField(key="feishu.app_secret", label="飞书应用密钥", type="password", section="飞书应用", required=True),
        ConfigField(key="bitable.app_token", label="排班多维表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.shift_table_id", label="班次表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.schedule_table_id", label="排班表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.whitelist_table_id", label="白名单表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.attendance_result_table_id", label="核对结果表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.duty_app_token", label="值班记录多维表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.duty_table_id", label="值班记录表 ID", type="text", section="多维表", required=True),
        ConfigField(key="bitable.actual_clock_table_id", label="实际打卡记录表 ID", type="text", section="多维表", required=True),
        ConfigField(key="offset_minutes", label="打卡容错分钟数", type="number", section="核对参数", required=True),
        ConfigField(key="overtime_gap_minutes", label="加班间隔分钟数", type="number", section="核对参数", required=True),
    ],
    steps=[
        ToolStep(
            id="check",
            name="刷卡核对",
            description="上传 3 个记录文件并指定核对日期，执行刷卡异常核对",
            inputs=[
                ToolInput(key="attendance_file", label="刷卡记录文件", type="file", accept=".csv,.xlsx", required=True),
                ToolInput(key="leave_file", label="请假记录文件", type="file", accept=".xlsx", required=True),
                ToolInput(key="overtime_file", label="加班登记文件", type="file", accept=".xlsx", required=True),
                ToolInput(key="mode", label="核对方式", type="select", options=["按月核对", "按日期范围核对"], default="按月核对", required=True),
                ToolInput(key="month", label="月份", type="month", placeholder="选择月份", show_when=("mode", "按月核对")),
                ToolInput(key="start_date", label="开始日期", type="date", placeholder="选择开始日期", show_when=("mode", "按日期范围核对")),
                ToolInput(key="end_date", label="结束日期", type="date", placeholder="选择结束日期", show_when=("mode", "按日期范围核对")),
            ],
        ),
        ToolStep(
            id="dedupe",
            name="消除误报",
            description="消除值班/实际打卡/加班导致的误报异常",
            inputs=[
                ToolInput(
                    key="attendance_file", label="刷卡记录文件", type="file",
                    from_step="check", from_key="attendance_file", required=True,
                ),
            ],
        ),
        ToolStep(
            id="write",
            name="写入多维表",
            description="清空多维表旧结果并写入本次核对结果",
            inputs=[],
        ),
    ],
)
async def attendance_check(step_id: str, params: dict[str, Any], context: StepContext) -> dict[str, Any]:
    if not context.config:
        raise ToolError("工具尚未配置，请联系管理员在工具箱配置页填写打卡核对配置")
    config = context.config

    if step_id == "check":
        mode = params.get("mode")
        month = str(params.get("month") or "").strip()
        start_date = str(params.get("start_date") or "").strip()
        end_date = str(params.get("end_date") or "").strip()
        if mode == "按月核对":
            if not month:
                raise ToolError("请填写月份（YYYY-MM）")
            try:
                datetime.strptime(month, "%Y-%m")
            except ValueError:
                raise ToolError("月份格式应为 YYYY-MM，如 2026-08") from None
        elif mode == "按日期范围核对":
            if not start_date or not end_date:
                raise ToolError("请填写开始日期和结束日期")
            for d in (start_date, end_date):
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    raise ToolError(f"日期格式应为 YYYY-MM-DD: {d}") from None
        else:
            raise ToolError("请选择核对方式")

        paths = context.file_paths
        if not paths.get("attendance_file") or not paths.get("leave_file") or not paths.get("overtime_file"):
            raise ToolError("请上传刷卡记录、请假记录、加班登记 3 个文件")

        attendance_file = paths["attendance_file"][0]
        leave_file = paths["leave_file"][0]
        overtime_file = paths["overtime_file"][0]

        data, text = await asyncio.to_thread(
            _capture, _run_check_sync,
            config, attendance_file, leave_file, overtime_file, month, start_date, end_date,
        )
        result_file = await asyncio.to_thread(
            _save_result_json, context.execution_id, data["result"], "check_result.json"
        )
        return {
            "text": text,
            "date_range": data["date_range"],
            "anomaly_count": data["anomaly_count"],
            "result_file": result_file,
            "result": data["result"],
            "start_date": data["start_date"],
            "end_date": data["end_date"],
        }

    if step_id == "dedupe":
        prev = context.prev_outputs.get("check") or {}
        result_data = prev.get("result")
        if result_data is None:
            raise ToolError("请先完成「刷卡核对」步骤")
        attendance_paths = context.file_paths.get("attendance_file", [])
        if not attendance_paths:
            raise ToolError("缺少刷卡记录文件，请重新执行「刷卡核对」步骤")

        processed, text = await asyncio.to_thread(
            _capture, _run_dedupe_sync,
            config, result_data, attendance_paths[0], prev["start_date"], prev["end_date"],
        )
        result_file = await asyncio.to_thread(
            _save_result_json, context.execution_id, processed, "check_result_after_dedupe.json"
        )
        return {
            "text": text,
            "remaining": len(processed),
            "result_file": result_file,
            "result": processed,
        }

    if step_id == "write":
        prev = context.prev_outputs.get("dedupe") or {}
        processed = prev.get("result")
        if processed is None:
            raise ToolError("请先完成「消除误报」步骤")

        data, text = await asyncio.to_thread(_capture, _run_write_sync, config, processed)
        return {"text": text, "written": data["written"], "deleted": data["deleted"]}

    raise ToolError(f"未知步骤: {step_id}")
