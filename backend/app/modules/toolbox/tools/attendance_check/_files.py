"""打卡核对工具：刷卡/请假/加班文件读取。

原样迁移自 attendance-checking 项目 scripts/utils.py 的文件读取段，
解析行为不可做任何变更。
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl


def _parse_dt(val: Any) -> datetime | None:
    """解析日期时间字符串，兼容多种常见格式（- 或 / 分隔，月日可补零或不补零）"""
    if isinstance(val, datetime):
        return val
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _first(val: Any, default: Any = None) -> Any:
    """取列表第一个元素或直接返回标量"""
    if val is None:
        return default
    if isinstance(val, list):
        return val[0] if val else default
    return val


def _extract_lookup_text(val: Any, default: str = "") -> Any:
    """提取 lookup 字段的文本值，格式为 [{'text': 'xxx', 'type': 'text'}]"""
    if val is None:
        return default
    if isinstance(val, list) and val:
        item = val[0]
        if isinstance(item, dict):
            return item.get("text", default)
        return item
    return val


def _extract_link_record_ids(val: Any) -> list[str]:
    """提取 link 字段的关联 record_id 列表，格式为 [{'record_ids': ['recXXX'], ...}]"""
    if not val or not isinstance(val, list):
        return []
    ids = []
    for item in val:
        if isinstance(item, dict) and "record_ids" in item:
            ids.extend(item["record_ids"])
    return ids


# ── 文件读取工具 ──────────────────────────────────────────────

def _read_rows(file_path: str) -> tuple[list[str], list[list[Any]]]:
    """根据文件扩展名读取 xlsx 或 csv，返回 (header列名列表, 数据行列表)"""
    p = Path(file_path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        # 优先尝试 UTF-8-BOM，失败则回退到 GBK（中文 Windows 导出 CSV 的常见编码）
        for encoding in ("utf-8-sig", "gbk", "gb18030"):
            try:
                with open(file_path, encoding=encoding) as f:
                    reader = csv.reader(f)
                    header = next(reader)
                    rows = [row for row in reader]
                return header, rows
            except UnicodeDecodeError:
                continue
        raise ValueError(f"无法以 UTF-8/GBK/GB18030 编码读取文件: {file_path}")
    else:
        wb = openpyxl.load_workbook(file_path)
        ws = wb.active
        if ws is None:
            wb.close()
            return [], []
        all_rows = list(ws.iter_rows(min_row=1, values_only=True))
        wb.close()
        header = [str(h) if h is not None else "" for h in all_rows[0]]
        rows = [list(r) for r in all_rows[1:]]  # type: ignore[arg-type]
        return header, rows


# ── 刷卡记录解析 ──────────────────────────────────────────────

def load_attendance_records(file_path: str) -> list[dict[str, Any]]:
    """加载刷卡记录 xlsx/csv，返回 [{工号, 姓名, 刷卡时间}, ...]"""
    header, rows = _read_rows(file_path)
    if not header:
        return []
    col_idx = {name: i for i, name in enumerate(header)}

    records = []
    for row in rows:
        emp_id = row[col_idx.get("员工工号", 1)]
        name = row[col_idx.get("姓名", 3)]
        swipe_time = row[col_idx.get("刷卡时间", 5)]
        if emp_id is None or swipe_time is None:
            continue
        emp_id = str(int(emp_id)) if isinstance(emp_id, (int, float)) else str(emp_id)
        dt = _parse_dt(swipe_time)
        if dt is not None:
            records.append({"工号": emp_id, "姓名": name, "刷卡时间": dt})
    return records


def group_attendance_by_employee(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按工号分组刷卡记录"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        eid = r["工号"]
        grouped.setdefault(eid, []).append(r)
    return grouped


# ── 请假记录解析 ──────────────────────────────────────────────

def load_leave_records(file_path: str) -> list[dict[str, Any]]:
    """加载请假记录 xlsx/csv，返回 [{工号, 开始时间, 结束时间, 请假类型}, ...]"""
    header, rows = _read_rows(file_path)
    if not header:
        return []
    col_idx = {name: i for i, name in enumerate(header)}

    records = []
    for row in rows:
        emp_id = row[col_idx.get("工号", 4)]
        start = row[col_idx.get("开始时间", 6)]
        end = row[col_idx.get("结束时间", 8)]
        leave_type = row[col_idx.get("请假类型", 7)]
        if emp_id is None or start is None or end is None:
            continue
        emp_id = str(int(emp_id)) if isinstance(emp_id, (int, float)) else str(emp_id)
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end)
        if start_dt is None or end_dt is None:
            continue
        records.append({
            "工号": emp_id,
            "开始时间": start_dt,
            "结束时间": end_dt,
            "请假类型": leave_type,
        })
    return records


def group_leave_by_employee(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按工号分组请假记录"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        grouped.setdefault(r["工号"], []).append(r)
    return grouped


# ── 加班记录解析 ──────────────────────────────────────────────

def load_overtime_records(file_path: str) -> list[dict[str, Any]]:
    """加载加班登记 xlsx/csv，返回 [{工号, 姓名, 开始时间, 结束时间}, ...]"""
    header, rows = _read_rows(file_path)
    if not header:
        return []
    col_idx = {name: i for i, name in enumerate(header)}

    records = []
    for row in rows:
        emp_id = row[col_idx.get("工号", 1)]
        name = row[col_idx.get("姓名", 2)]
        start = row[col_idx.get("开始时间", 6)]
        end = row[col_idx.get("结束时间", 7)]
        if emp_id is None or start is None or end is None:
            continue
        if str(start).strip() == "" or str(end).strip() == "":
            continue
        emp_id = str(int(emp_id)) if isinstance(emp_id, (int, float)) else str(emp_id)
        start_dt = _parse_dt(start)
        end_dt = _parse_dt(end)
        if start_dt is None or end_dt is None:
            continue
        records.append({
            "工号": emp_id,
            "姓名": name,
            "开始时间": start_dt,
            "结束时间": end_dt,
        })
    return records


def group_overtime_by_employee(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """按工号分组加班记录，并合并相邻的跨天拆分记录"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        grouped.setdefault(r["工号"], []).append(r)
    # 合并相邻记录（上一条结束时间 == 下一条开始时间）
    for eid in grouped:
        recs = sorted(grouped[eid], key=lambda x: x["开始时间"])
        merged: list[dict[str, Any]] = []
        for cur in recs:
            if merged and cur["开始时间"] == merged[-1]["结束时间"]:
                merged[-1]["结束时间"] = cur["结束时间"]
            else:
                merged.append(cur)
        grouped[eid] = merged
    return grouped
