"""PQR Excel 批量导入：模板生成 + 文件解析校验 + 原子写入（merge/replace）。

校验口径与行内保存共用 common 的白名单助手；全部正确才写库，任一错误
零落库；文件中的新批号自动登记为该段批次。
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import io
import math
import uuid
from typing import Any
from unicodedata import normalize as _nfkc

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import AprBatch, AprItem, AprValueType
from app.modules.qa.repository import apr as repo
from app.modules.qa.service.apr.common import (
    _actor_id,
    _display_name,
    _ensure_year_open,
    _get_product_or_404,
    _get_section_or_404,
    _normalize_quick_values,
    _quick_values_hint,
    _record_value_changes,
)
from app.platform.identity.models import User

# 表头别名/空白占位/规模上限：模板与导入端共用一套口径。
_IMPORT_BATCH_HEADERS = {"批号", "批次号", "batch_no"}

_IMPORT_BATCH_HEADERS = {"批号", "批次号", "batch_no"}
_IMPORT_LABEL_HEADERS = {"行标签", "标签", "row_label"}

_IMPORT_LABEL_HEADERS = {"行标签", "标签", "row_label"}
_IMPORT_BLANK_MARKERS = {"", "-", "/", "—", "–"}

_IMPORT_BLANK_MARKERS = {"", "-", "/", "—", "–"}
_IMPORT_HEADER_SCAN_ROWS = 8

_IMPORT_HEADER_SCAN_ROWS = 8
_IMPORT_MAX_ROWS = 2000

# 防御 used range 虚高的文件：空白行也计入读取上限，避免整表读进内存。
_IMPORT_MAX_READ_ROWS = 20_000

_IMPORT_MAX_READ_ROWS = 20_000
_IMPORT_MAX_ERRORS = 100


def _normalize_header_cell(value: Any) -> str:
    if value is None:
        return ""
    return _nfkc("NFKC", str(value)).strip()


def _cell_is_blank(value: Any) -> bool:
    """空格 / - / / / — 视为未填；数值 0 是有效测量值不算空。"""
    if value is None:
        return True
    if isinstance(value, str):
        return _nfkc("NFKC", value).strip() in _IMPORT_BLANK_MARKERS
    return False


def _parse_import_cell(
    item: AprItem, value: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """导入单元格 → 值字典；返回 (值行, 错误消息) 二者互斥，空白格两 None。

    与 save_batch_values 同口径：数值列收数字（含数字串）或 quick_values
    白名单文字（NFKC 归一）；文字列收任意文字；日期/布尔格一律拒收。
    """
    if _cell_is_blank(value):
        return None, None
    if isinstance(value, (bool, _dt.datetime, _dt.date, _dt.time)):
        return None, "类型不符：该格是日期/布尔值，请改为数字或文字。"
    if item.value_type == AprValueType.NUMBER.value:
        if isinstance(value, (int, float)):
            num = float(value)
            if not math.isfinite(num):
                return None, "数值无效（inf/nan 不被接受）。"
            return {"value_num": num, "value_text": None}, None
        text = _nfkc("NFKC", str(value)).strip()
        parsed_num: float | None
        try:
            parsed_num = float(text)
        except ValueError:
            parsed_num = None
        if parsed_num is not None:
            if not math.isfinite(parsed_num):
                return None, "数值无效（inf/nan 不被接受）。"
            return {"value_num": parsed_num, "value_text": None}, None
        if text in _normalize_quick_values(item.quick_values):
            return {"value_num": None, "value_text": text}, None
        return (
            None,
            f"数值列只接受数字或文字结果：{_quick_values_hint(item.quick_values)}",
        )
    text = _nfkc("NFKC", str(value)).strip()
    if len(text) > 300:
        return None, "文字超过 300 字上限。"
    return {"value_num": None, "value_text": text}, None


async def build_import_template(
    db: AsyncSession, section_id: uuid.UUID, year: int
) -> tuple[Any, str]:
    """生成录入导入模板工作簿 + 建议文件名（不含扩展名）。

    sheet「数据录入」：r1 分组行（批号/行标签列留空）、r2 表头（批注附
    单位/标准/文字结果白名单）、r3 起空白数据区；sheet「已登记批号」列出
    该段该年度全部批号供参考——导入时文件中未登记的批号会自动登记。
    """
    import openpyxl
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    section = await _get_section_or_404(db, section_id)
    items = await repo.list_items(db, section_id, active_only=True)
    batches = await repo.list_batches_of_section(db, section_id, year=year)

    wb = openpyxl.Workbook()
    ws = wb.active
    if ws is None:  # 新工作簿必有 active；类型收窄。
        raise RuntimeError("openpyxl Workbook() 未提供活动工作表")
    ws.title = "数据录入"
    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    data_col_offset = 2 if section.multi_row else 1

    # r1 分组（相邻同组合并）
    col = data_col_offset + 1
    while col <= data_col_offset + len(items):
        group = items[col - data_col_offset - 1].group_name
        end = col
        while (
            end + 1 <= data_col_offset + len(items)
            and items[end - data_col_offset].group_name == group
        ):
            end += 1
        if group:
            cell = ws.cell(row=1, column=col, value=group)
            cell.font = bold
            cell.alignment = center
            if end > col:
                ws.merge_cells(start_row=1, start_column=col, end_row=1, end_column=end)
        col = end + 1
    # r2 表头 + 批注（单位/标准/文字结果）
    ws.cell(row=2, column=1, value="批号").font = bold
    if section.multi_row:
        ws.cell(row=2, column=2, value="行标签").font = bold
    for idx, item in enumerate(items):
        cell = ws.cell(
            row=2,
            column=data_col_offset + 1 + idx,
            value=_display_name(item.name_cn, item.code),
        )
        cell.font = bold
        cell.alignment = center
        hints: list[str] = []
        if item.unit:
            hints.append(f"单位：{item.unit}")
        if item.spec_text:
            hints.append(f"标准：{item.spec_text}")
        if item.value_type == AprValueType.NUMBER.value and item.quick_values:
            hints.append(f"文字结果可用：{'、'.join(item.quick_values)}")
        if hints:
            cell.comment = Comment("\n".join(hints), "PQR")
    ws.column_dimensions["A"].width = 20
    if section.multi_row:
        ws.column_dimensions["B"].width = 12
    for idx in range(len(items)):
        ws.column_dimensions[get_column_letter(data_col_offset + 1 + idx)].width = 14

    # sheet 已登记批号（参考；导入会自动登记文件中未登记的批号）
    ref = wb.create_sheet(title="已登记批号")
    ref.cell(row=1, column=1, value="批号").font = bold
    ref.cell(row=1, column=2, value="排序号").font = bold
    for r, b in enumerate(batches, start=2):
        ref.cell(row=r, column=1, value=b.batch_no)
        ref.cell(row=r, column=2, value=b.seq)
    ref.column_dimensions["A"].width = 22
    ref.column_dimensions["B"].width = 10

    return wb, f"{section.name}-{year}录入导入模板"


async def import_section_values(
    db: AsyncSession,
    section_id: uuid.UUID,
    *,
    year: int,
    mode: str,
    file_bytes: bytes,
    user: User | None,
) -> dict[str, Any]:
    """Excel 批量导入录入值：全部校验通过才写库，任一错误零落库。

    - merge：非空格写入、空白格保留系统已有值（repo.merge_batch_values）
    - replace：整批替换（同 save_batch_values 全量替换语义 + 必填校验）
    - 校验规则与行内保存同口径：quick_values 白名单、类型匹配、锁定拦截
    - 文件中的新批号自动登记为该段批次（唯一守卫同登记批次），
      结果 registered 字段透明报告新登记数
    """
    section = await _get_section_or_404(db, section_id)
    # 锁定拦截最优先（同其他写路径）。
    await _ensure_year_open(db, section.product_id, year)

    def _fail(errors: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "ok": False,
            "mode": mode,
            "batches": 0,
            "cells": 0,
            "errors": errors[:_IMPORT_MAX_ERRORS],
            "total_errors": len(errors),
        }

    def _open_workbook() -> Any:
        import openpyxl

        return openpyxl.load_workbook(
            io.BytesIO(file_bytes), read_only=True, data_only=True
        )

    try:
        wb = await asyncio.to_thread(_open_workbook)
    except Exception as exc:
        return _fail(
            [
                {
                    "row": 0,
                    "column": None,
                    "message": (
                        f"无法打开文件：{exc}。若为加密文件请另存为解密副本后重试。"
                    ),
                }
            ]
        )
    if not wb.sheetnames:
        return _fail([{"row": 0, "column": None, "message": "文件里没有任何工作表。"}])
    ws = wb["数据录入"] if "数据录入" in wb.sheetnames else wb[wb.sheetnames[0]]

    def _read_rows() -> list[tuple[Any, ...]]:
        rows: list[tuple[Any, ...]] = []
        for row in ws.iter_rows(values_only=True):
            rows.append(row)
            if len(rows) >= _IMPORT_MAX_READ_ROWS:
                break
        return rows

    try:
        all_rows = await asyncio.to_thread(_read_rows)
    except Exception as exc:  # read_only 流式解析中途坏档
        return _fail(
            [{"row": 0, "column": None, "message": f"无法读取表格内容：{exc}。"}]
        )

    # 表头探测：前 N 行里找含「批号」的行（模板 r1 是分组行，表头在 r2）。
    header_idx: int | None = None
    header: list[str] = []
    for idx in range(min(_IMPORT_HEADER_SCAN_ROWS, len(all_rows))):
        cells = [_normalize_header_cell(c) for c in all_rows[idx]]
        if any(c in _IMPORT_BATCH_HEADERS for c in cells):
            header_idx = idx
            header = cells
            break
    if header_idx is None:
        return _fail(
            [
                {
                    "row": 0,
                    "column": None,
                    "message": (
                        f"未找到表头行：前 {_IMPORT_HEADER_SCAN_ROWS} 行里"
                        "没有「批号」列，请使用下载的模板填写。"
                    ),
                }
            ]
        )

    errors: list[dict[str, Any]] = []

    # 列映射：先按列编码（段内唯一稳定标识），再按显示名；重名拒绝按名匹配。
    # 字典 key 与表头同样过 NFKC 归一：库内列名常含全角字符（培养温度（最低）），
    # 只归一表头一侧会把模板自产的表头也认不出来。
    items = await repo.list_items(db, section_id, active_only=True)
    by_code = {_normalize_header_cell(i.code): i for i in items}
    by_name: dict[str, list[AprItem]] = {}
    for i in items:
        key = _normalize_header_cell(_display_name(i.name_cn, i.code))
        by_name.setdefault(key, []).append(i)

    batch_col: int | None = None
    label_col: int | None = None
    col_items: dict[int, AprItem] = {}
    seen_item_cols: set[uuid.UUID] = set()
    for col, name in enumerate(header):
        if not name:
            continue
        if name in _IMPORT_BATCH_HEADERS:
            if batch_col is None:
                batch_col = col
            else:
                errors.append(
                    {
                        "row": header_idx + 1,
                        "column": name,
                        "message": "「批号」列出现多次。",
                    }
                )
            continue
        if name in _IMPORT_LABEL_HEADERS:
            label_col = col if label_col is None else label_col
            continue
        item = by_code.get(name)
        if item is None:
            candidates = by_name.get(name, [])
            if not candidates:
                errors.append(
                    {
                        "row": header_idx + 1,
                        "column": name,
                        "message": (
                            f"列「{name}」无法匹配到该段的列定义，"
                            "请在「模板配置」核对列名，或在表头改用列编码。"
                        ),
                    }
                )
                continue
            if len(candidates) > 1:
                errors.append(
                    {
                        "row": header_idx + 1,
                        "column": name,
                        "message": (
                            f"列名「{name}」在该段内重复，"
                            f"请在表头改用列编码（如 {candidates[0].code}）。"
                        ),
                    }
                )
                continue
            item = candidates[0]
        if item.id in seen_item_cols:
            errors.append(
                {
                    "row": header_idx + 1,
                    "column": name,
                    "message": f"列「{name}」在表头里重复出现。",
                }
            )
            continue
        seen_item_cols.add(item.id)
        col_items[col] = item
    if batch_col is None:
        errors.append(
            {"row": header_idx + 1, "column": None, "message": "未找到「批号」列。"}
        )
    if errors:
        return _fail(errors)
    assert batch_col is not None  # 上面已把缺失的批号列转成错误返回

    # 数据行 → 解析单元格（批号/标签/值），收集全部错误再决定是否落库。
    data_rows = all_rows[header_idx + 1 :]
    filled_rows = sum(1 for row in data_rows if any(not _cell_is_blank(c) for c in row))
    if filled_rows > _IMPORT_MAX_ROWS:
        return _fail(
            [
                {
                    "row": 0,
                    "column": None,
                    "message": f"数据行超过 {_IMPORT_MAX_ROWS} 行上限，请分批导入。",
                }
            ]
        )
    if len(all_rows) >= _IMPORT_MAX_READ_ROWS:
        return _fail(
            [
                {
                    "row": 0,
                    "column": None,
                    "message": (
                        f"表格空白区域超过 {_IMPORT_MAX_READ_ROWS} 行，"
                        "请清理空白行/格式后重试。"
                    ),
                }
            ]
        )
    parsed_rows: list[dict[str, Any]] = []
    for offset, raw in enumerate(data_rows):
        excel_row = header_idx + 2 + offset

        def _cell(col: int) -> Any:
            return raw[col] if col < len(raw) else None

        watched = (
            [_cell(batch_col)]
            + [_cell(col) for col in col_items]
            + ([_cell(label_col)] if label_col is not None else [])
        )
        if all(_cell_is_blank(v) for v in watched):
            continue  # 整行未填，静默跳过

        raw_batch = _cell(batch_col)
        if isinstance(raw_batch, (bool, _dt.datetime, _dt.date, _dt.time)):
            errors.append(
                {
                    "row": excel_row,
                    "column": "批号",
                    "message": "批号格类型不符，请填写文字批号。",
                }
            )
            continue
        if _cell_is_blank(raw_batch):
            errors.append({"row": excel_row, "column": "批号", "message": "批号为空。"})
            continue
        if isinstance(raw_batch, float) and raw_batch.is_integer():
            batch_no = str(int(raw_batch))
        else:
            batch_no = _nfkc("NFKC", str(raw_batch)).strip()
        if not batch_no or len(batch_no) > 64:
            errors.append(
                {
                    "row": excel_row,
                    "column": "批号",
                    "message": "批号不能为空且不超过 64 字。",
                }
            )
            continue

        label: str | None = None
        if section.multi_row and label_col is not None:
            raw_label = _cell(label_col)
            if not _cell_is_blank(raw_label):
                if isinstance(raw_label, (bool, _dt.datetime, _dt.date, _dt.time)):
                    errors.append(
                        {
                            "row": excel_row,
                            "column": "行标签",
                            "message": "行标签格类型不符，请填写文字。",
                        }
                    )
                else:
                    label = _nfkc("NFKC", str(raw_label)).strip()
                    if len(label) > 32:
                        errors.append(
                            {
                                "row": excel_row,
                                "column": "行标签",
                                "message": "行标签超过 32 字上限。",
                            }
                        )
                        label = None

        cell_values: dict[int, dict[str, Any]] = {}
        for col, item in col_items.items():
            parsed, err = _parse_import_cell(item, _cell(col))
            if err is not None:
                errors.append({"row": excel_row, "column": header[col], "message": err})
            elif parsed is not None:
                cell_values[col] = parsed
        parsed_rows.append(
            {
                "excel_row": excel_row,
                "batch_no": batch_no,
                "label": label,
                "cells": cell_values,
            }
        )

    # 批次分组：保序；单行段批号重复、多行段同批行不连续均拒绝。
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    index: dict[str, list[dict[str, Any]]] = {}
    prev_batch: str | None = None
    for pr in parsed_rows:
        bn: str = pr["batch_no"]
        if bn not in index:
            index[bn] = []
            groups.append((bn, index[bn]))
        elif not section.multi_row:
            errors.append(
                {
                    "row": pr["excel_row"],
                    "column": "批号",
                    "message": f"批号 {bn} 重复出现：该段为单行段，一批一行。",
                }
            )
            continue
        elif prev_batch != bn:
            errors.append(
                {
                    "row": pr["excel_row"],
                    "column": "批号",
                    "message": f"批号 {bn} 的行必须连续排列，中间不能夹其他批号。",
                }
            )
            continue
        index[bn].append(pr)
        prev_batch = bn

    # 批号查找 key 同样 NFKC 归一（与解析侧对称）；文件中的新批号自动登记为
    # 该段批次（复用登记批次的唯一守卫），结果里透明报告新登记数。
    registered = {
        _normalize_header_cell(b.batch_no): b
        for b in await repo.list_batches_of_section(db, section_id, year=year)
    }
    write_ops: list[tuple[AprBatch | None, str, list[dict[str, Any]]]] = []
    required_items = [i for i in items if i.required]
    for bn, rows_ in groups:
        values: list[dict[str, Any]] = []
        for seq, pr in enumerate(rows_, start=1):
            row_seq = seq if section.multi_row else 1
            for col, parsed in pr["cells"].items():
                item = col_items[col]
                values.append(
                    {
                        "item_id": item.id,
                        "row_seq": row_seq,
                        # 行标签随所在行任一数据格写入生效（仅多行段）。
                        "row_label": pr["label"] if section.multi_row else None,
                        "value_num": parsed["value_num"],
                        "value_text": parsed["value_text"],
                        "remark": None,
                    }
                )
        if mode == "replace" and required_items:
            # 整批替换语义的必填校验（同 save_batch_values）：漏填会被静默清掉。
            filled = {(v["item_id"], v["row_seq"]) for v in values}
            row_scope = sorted({v["row_seq"] for v in values}) or [1]
            missing: list[str] = []
            for row_seq in row_scope:
                for item in required_items:
                    if (item.id, row_seq) in filled:
                        continue
                    missing.append(
                        f"第 {row_seq} 行「{item.name_cn}」"
                        if section.multi_row
                        else f"「{item.name_cn}」"
                    )
            if missing:
                errors.append(
                    {
                        "row": rows_[0]["excel_row"],
                        "column": "批号",
                        "message": (
                            f"批号 {bn}：整批替换下以下必填项为空会被清掉，"
                            f"请补齐：{'、'.join(missing)}。"
                        ),
                    }
                )
                continue
        write_ops.append((registered.get(bn), bn, values))

    # 原子性：任一错误零落库（validate-before-write）。
    if errors:
        return _fail(errors)

    registered_new = 0
    batches_written = 0
    cells_written = 0
    product = await _get_product_or_404(db, section.product_id)
    items_all = {i.id: i for i in items}
    for batch, bn, values in write_ops:
        if batch is None:
            batch = AprBatch(
                section_id=section.id,
                product_id=section.product_id,
                year=year,
                batch_no=bn,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
            try:
                # 预检后并发仍可能撞 uq_qa_apr_batches_section_year_no，转 409。
                async with db.begin_nested():
                    db.add(batch)
                    await db.flush()
            except IntegrityError:
                raise AppException(
                    status_code=409,
                    message=f"批号 {bn} 在该段 {year} 年度已登记",
                ) from None
            registered_new += 1
        if mode == "merge" and not values:
            continue  # 全空白批次：merge 无事可做
        # 操作日志：写入前取旧值逐格 diff（merge 只看本次写入的格）。
        old_values = await repo.list_values_of_batch(db, batch.id)
        if mode == "replace":
            count = await repo.replace_batch_values(
                db, batch.id, values, actor_id=_actor_id(user)
            )
            diff_rows = values
        else:
            count = await repo.merge_batch_values(
                db, batch.id, values, actor_id=_actor_id(user)
            )
            # merge 会保留文件未提供的备注/行标签：以写完后的库内值为准，
            # 否则原值重导会被 diff 成「备注被清空」。
            written = {(v["item_id"], v["row_seq"]) for v in values}
            diff_rows = [
                value
                for value in await repo.list_values_of_batch(db, batch.id)
                if (value.item_id, value.row_seq) in written
            ]
        recorded = await _record_value_changes(
            db,
            user=user,
            batch=batch,
            section=section,
            product=product,
            items_by_id=items_all,
            old_values=old_values,
            new_rows=diff_rows,
            touched_only=mode == "merge",
            source="import",
            mode=mode,
        )
        if not recorded and count == 0:
            continue  # 内容与现状完全一致的 merge：既没写值也没变更，不算事件
        batches_written += 1
        cells_written += count
    return {
        "ok": True,
        "mode": mode,
        "batches": batches_written,
        "cells": cells_written,
        "registered": registered_new,
        "errors": [],
        "total_errors": 0,
    }
