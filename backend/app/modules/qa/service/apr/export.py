"""PQR 年终汇总导出：把 summary 结果渲染成 xlsx 工作簿（多级表头+表尾统计行）。"""

from __future__ import annotations

from typing import Any

from app.modules.qa.service.apr.common import _display_name


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

    product = summary_data["product"]
    year = summary_data["year"]
    wb = openpyxl.Workbook()
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)
    used_names: set[str] = set()
    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for section in summary_data["sections"]:
        ws = wb.create_sheet(
            title=_excel_sheet_name(section["name"], section["market"], used_names)
        )
        items = section["items"]
        # 列布局：序号 | 批号 | [行标签] | 数据列…
        data_col_offset = 3 if section["multi_row"] else 2
        n_cols = data_col_offset + len(items)

        # r1 标题
        title = (
            f"年度产品审核/ANNUAL PRODUCT REVIEW——{product['name']}"
            f"（{product['code']}）{year} · {section['name']}"
        )
        ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=13)
        ws.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=max(n_cols, 2)
        )
        # r2 分组（相邻同组合并）
        group_row = 2
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
        # r3 列名 / r4 标准
        ws.cell(row=3, column=1, value="序号").font = bold
        ws.cell(row=3, column=2, value="批号").font = bold
        if section["multi_row"]:
            ws.cell(row=3, column=3, value="行标签").font = bold
        for idx, item in enumerate(items):
            name_cell = ws.cell(
                row=3, column=data_col_offset + 1 + idx, value=_item_display_name(item)
            )
            name_cell.font = bold
            name_cell.alignment = center
            ws.cell(
                row=4,
                column=data_col_offset + 1 + idx,
                value=item["spec_text"] or "",
            ).alignment = center
        # 数据行
        for ridx, row in enumerate(section["rows"], start=1):
            excel_row = 4 + ridx
            ws.cell(row=excel_row, column=1, value=ridx)
            ws.cell(row=excel_row, column=2, value=row["batch_no"])
            col_cursor = data_col_offset + 1
            if section["multi_row"]:
                ws.cell(row=excel_row, column=3, value=row["row_label"] or "")
            for item in items:
                cell_data = row["cells"].get(item["id"])
                value = None
                if cell_data is not None:
                    value = (
                        cell_data["num"]
                        if cell_data["num"] is not None
                        else cell_data["text"]
                    )
                ws.cell(row=excel_row, column=col_cursor, value=value)
                col_cursor += 1
        # 表尾统计（仅数值列）
        stats_by_id = section["column_stats"]
        stat_rows = [
            ("平均值", "mean"),
            ("最大值", "max"),
            ("最小值", "min"),
            ("STDEV", "stdev"),
        ]
        base_row = 4 + len(section["rows"]) + 1
        for offset, (label, key) in enumerate(stat_rows):
            row_idx = base_row + offset
            ws.cell(row=row_idx, column=1, value=label).font = bold
            for idx, item in enumerate(items):
                stats = stats_by_id.get(item["id"])
                if stats:
                    ws.cell(
                        row=row_idx,
                        column=data_col_offset + 1 + idx,
                        value=round(stats[key], 6)
                        if stats.get(key) is not None
                        else "",
                    )
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
