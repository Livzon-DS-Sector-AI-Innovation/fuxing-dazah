"""PQR 年终汇总导出：把 summary 结果渲染成 xlsx 工作簿（多级表头+表尾统计行）。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.service.apr.analysis import summary
from app.modules.qa.service.apr.common import (
    _display_name,
    _get_section_or_404,
    _item_precision,
)


def _excel_sheet_name(section_name: str, market: str | None, used: set[str]) -> str:
    """Excel sheet 名 ≤31 字符且工作簿内唯一。"""
    base = section_name if not market else f"{section_name}-{market}"
    name = base[:31] or "sheet"
    candidate = name
    suffix = 2
    while candidate in used:
        tail = f"({suffix})"
        candidate = f"{name[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def _item_display_name(item: dict[str, Any]) -> str:
    """summary/export 的 item dict 视图取显示名。"""
    return _display_name(str(item["name_cn"]), item["code"])


# 表尾统计行清单（对齐年度回顾工具 qa_year_review 的 STAT_KEYS_CN 22 项）：
# (标签, 取值来源, 键)。item=列定义自身属性（标准限），stats=查询时统计量；
# 未检出透明行（nd_count）在任一列存在 ND 时追加。
_STAT_ROWS: list[tuple[str, str, str]] = [
    ("标准上限(USL)", "item", "spec_max"),
    ("标准下限(LSL)", "item", "spec_min"),
    ("平均值", "stats", "mean"),
    ("最大值", "stats", "max"),
    ("最小值", "stats", "min"),
    ("STDEVA", "stats", "stdev"),
    ("+3σ", "stats", "plus3s"),
    ("-3σ", "stats", "minus3s"),
    ("+4σ", "stats", "plus4s"),
    ("-4σ", "stats", "minus4s"),
    ("规格公差(T)", "stats", "tolerance"),
    ("规格中心值(U)", "stats", "spec_center"),
    ("制程准确度(ca)", "stats", "ca"),
    ("制程精密度(cp)", "stats", "cp"),
    ("制程能力(CPKu)", "stats", "cpku"),
    ("制程能力(CPKl)", "stats", "cpkl"),
    ("制程能力(CPK)", "stats", "cpk"),
    ("CPK级别", "stats", "cpk_level"),
    ("警告限上限", "stats", "warn_max"),
    ("警告限下限", "stats", "warn_min"),
    ("行动限上限", "stats", "action_max"),
    ("行动限下限", "stats", "action_min"),
]


async def build_section_export(
    db: AsyncSession, section_id: uuid.UUID, *, year: int
) -> tuple[Any, str]:
    """段级汇总导出：该段一个 sheet（模板数据矩阵+全量统计表尾）。

    汇总仍走 summary（查询时统计）；按段过滤 sections 后复用整本渲染器。
    """
    section = await _get_section_or_404(db, section_id)
    data = await summary(db, section.product_id, year=year)
    data["sections"] = [
        s for s in data["sections"] if s["id"] == str(section_id)
    ]
    if not data["sections"]:
        raise AppException(
            status_code=422,
            message=(
                f"模板段「{section.name}」在 {year} 年度还没有可导出的批次数据。"
            ),
        )
    wb = build_export_workbook(data)
    filename = f"{data['product']['name']}{section.name}{year}年度审核汇总.xlsx"
    return wb, filename


def build_export_workbook(
    summary_data: dict[str, Any],
) -> Any:
    """把 summary 结果渲染成 xlsx 工作簿（openpyxl，多级表头+表尾统计行）。

    同步渲染会短暂占用事件循环：当前量级（单产品单年几十批 × 百来列）
    毫秒级可接受；若矩阵显著增长再考虑挪 run_in_executor/后台任务。
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)
    used_names: set[str] = set()
    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    # 数据单元格默认居中：不设 alignment 时数值右对齐/文本左对齐，观感混杂
    cell_center = Alignment(horizontal="center", vertical="center")

    for section in summary_data["sections"]:
        ws = wb.create_sheet(
            title=_excel_sheet_name(section["name"], section["market"], used_names)
        )
        items = section["items"]
        # 列布局：序号 | 批号 | [行标签] | 数据列…
        data_col_offset = 3 if section["multi_row"] else 2
        n_cols = data_col_offset + len(items)

        # r1 分组（相邻同组合并）；无大标题行——产品/年度信息在文件名里
        group_row = 1
        col = data_col_offset + 1
        while col <= n_cols:
            group = items[col - data_col_offset - 1]["group_name"]
            end = col
            while (
                end + 1 <= n_cols
                and items[end - data_col_offset]["group_name"] == group
            ):
                end += 1
            cell = ws.cell(row=group_row, column=col, value=group or "")
            cell.font = bold
            cell.alignment = center
            if end > col:
                ws.merge_cells(
                    start_row=group_row,
                    start_column=col,
                    end_row=group_row,
                    end_column=end,
                )
            col = end + 1
        # r2 列名 / r3 标准
        for col, label in ((1, "序号"), (2, "批号")):
            header = ws.cell(row=2, column=col, value=label)
            header.font = bold
            header.alignment = center
        if section["multi_row"]:
            row_header = ws.cell(row=2, column=3, value="行标签")
            row_header.font = bold
            row_header.alignment = center
        for idx, item in enumerate(items):
            name_cell = ws.cell(
                row=2, column=data_col_offset + 1 + idx, value=_item_display_name(item)
            )
            name_cell.font = bold
            name_cell.alignment = center
            ws.cell(
                row=3,
                column=data_col_offset + 1 + idx,
                value=item["spec_text"] or "",
            ).alignment = center
        # 数据行（默认居中）
        for ridx, row in enumerate(section["rows"], start=1):
            excel_row = 3 + ridx
            ws.cell(row=excel_row, column=1, value=ridx).alignment = cell_center
            ws.cell(
                row=excel_row, column=2, value=row["batch_no"]
            ).alignment = cell_center
            col_cursor = data_col_offset + 1
            if section["multi_row"]:
                ws.cell(
                    row=excel_row, column=3, value=row["row_label"] or ""
                ).alignment = cell_center
            for item in items:
                cell_data = row["cells"].get(item["id"])
                value = None
                if cell_data is not None:
                    value = (
                        cell_data["num"]
                        if cell_data["num"] is not None
                        else cell_data["text"]
                    )
                ws.cell(
                    row=excel_row, column=col_cursor, value=value
                ).alignment = cell_center
                col_cursor += 1
        # 表尾统计：仅数值列；数值按列精度圆整，CPK级别为文字；
        # 不适用的统计显示 N/A（单限缺对侧、文字列无统计）；
        # 任一列存在未检出时追加透明行（口径 zero 已按 0 进统计，无 ND 留空——批数不是统计量）。
        stats_by_id = section["column_stats"]
        base_row = 3 + len(section["rows"]) + 1
        footer_rows: list[tuple[str, str, str]] = list(_STAT_ROWS)
        if any(s.get("nd_count") for s in stats_by_id.values()):
            footer_rows.append(("未检出", "stats", "nd_count"))
        for offset, (label, source, key) in enumerate(footer_rows):
            row_idx = base_row + offset
            ws.cell(row=row_idx, column=1, value=label).font = bold
            for idx, item in enumerate(items):
                stats = stats_by_id.get(item["id"])
                if source == "item":
                    value = item.get(key)
                elif stats is None:
                    value = None
                else:
                    value = stats.get(key)
                # 未检出行空=无 ND；统计行空=不适用，显示 N/A
                empty_display = "" if key == "nd_count" else "N/A"
                cell_value: Any = empty_display
                if value is not None:
                    cell_value = (
                        value
                        if isinstance(value, str)
                        else round(value, _item_precision(item))
                    )
                ws.cell(
                    row=row_idx, column=data_col_offset + 1 + idx, value=cell_value
                ).alignment = cell_center
        # 列宽
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 20
        for idx in range(len(items)):
            ws.column_dimensions[
                get_column_letter(data_col_offset + 1 + idx)
            ].width = 14
    if not wb.sheetnames:
        ws = wb.create_sheet(title="无数据")
        ws.cell(row=1, column=1, value="该年度没有可导出的段数据。")
    return wb
