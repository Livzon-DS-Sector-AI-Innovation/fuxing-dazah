"""
Excel template filler — openpyxl-based engine that copies a template,
replaces placeholders, fills data rows with style preservation, and
configures page setup for downstream PDF conversion.

Does NOT depend on the rest of the safety module or the database.
Works with plain dicts, so it can be driven by any data source.
"""

from __future__ import annotations

import copy
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from .config import TemplateConfig


class ExcelTemplateFiller:
    """Fill an Excel template with row data, preserving formatting.

    Usage::

        config = TemplateConfig(...)
        filler = ExcelTemplateFiller(config)
        wb = filler.fill(template_path, data_records)
        wb.save(output_path)
    """

    def __init__(self, config: TemplateConfig) -> None:
        self._cfg = config

    # ── Public API ──────────────────────────────────────────────────────

    def fill(
        self,
        template_path: str | Path,
        data: list[dict],
    ) -> openpyxl.Workbook:
        """Load template, fill with data, return the workbook (unsaved)."""
        wb = openpyxl.load_workbook(str(template_path))
        ws = wb.active
        # 统一工作表名称（默认 Sheet1，不沿用模板自定义 sheet 名）
        if self._cfg.sheet_name:
            ws.title = self._cfg.sheet_name

        self._replace_title(ws, data)
        sample_styles = self._capture_sample_styles(ws)
        self._fill_data_rows(ws, data, sample_styles)
        # 表头明细行合并须在删除列字母行之前（表头行号为模板绝对行号）
        self._apply_header_merges(ws)
        self._strip_column_letters_row(ws)
        # 合并单元格须在删除列字母行之后应用（delete_rows 不会随动 merged_cells 范围）
        self._apply_merge_groups(ws, len(data))
        self._apply_data_row_heights(ws, len(data))
        self._apply_column_widths(ws)
        self._apply_page_setup(ws)

        return wb

    def fill_and_save(
        self,
        template_path: str | Path,
        data: list[dict],
        output_path: str | Path,
    ) -> Path:
        """Convenience: fill + save, returning the output path."""
        wb = self.fill(template_path, data)
        wb.save(str(output_path))
        return Path(output_path)

    # ── Private helpers ─────────────────────────────────────────────────

    def _replace_title(self, ws, data: list[dict]) -> None:
        """Replace *** placeholder in the title row."""
        resolver = self._cfg.title_resolver
        if resolver is None:
            return
        replacement = resolver(data)
        if not replacement:
            return

        cell = ws.cell(self._cfg.title_row, 1)
        original = cell.value or ""
        new_title = original.replace(self._cfg.title_placeholder, replacement)
        if new_title != original:
            cell.value = new_title

    def _capture_sample_styles(self, ws) -> dict[str, dict]:
        """Snapshots font/fill/alignment/border from every column of the sample row."""
        styles: dict[str, dict] = {}
        row = self._cfg.sample_row
        for c in range(1, self._cfg.total_columns + 1):
            col_letter = get_column_letter(c).lower()
            src = ws.cell(row, c)
            styles[col_letter] = {
                "font": copy.copy(src.font),
                "fill": copy.copy(src.fill),
                "alignment": copy.copy(src.alignment),
                "border": copy.copy(src.border),
            }
        return styles

    def _fill_data_rows(
        self, ws, data: list[dict], sample_styles: dict[str, dict]
    ) -> None:
        """Write data rows starting at sample_row, cloning styles.

        样式策略：默认克隆模板样本行（向后兼容）；若 config 提供
        ``data_font_size`` / ``data_align_left`` / ``data_align_center``
        等覆盖项，则对数据行应用统一的字体/对齐/自动行高，保证导出「工整」。
        """
        start_row = self._cfg.sample_row
        total_cols = self._cfg.total_columns
        data_height = ws.row_dimensions[start_row].height
        mapping = self._cfg.column_mapping
        numeric_cols = self._cfg.numeric_columns
        risk_col = self._cfg.risk_label_column
        risk_colors = self._cfg.risk_label_colors
        seq_col = self._cfg.sequence_column

        auto_height = self._cfg.data_row_auto_height
        font_name = self._cfg.data_font_name
        font_size = self._cfg.data_font_size
        font_bold = self._cfg.data_font_bold
        left_cols = self._cfg.data_align_left
        center_cols = self._cfg.data_align_center

        # 合并组内的「非主列」：填表时留空（合并单元格只保留首列值）
        merge_non_primary = set()
        for start_letter, end_letter in self._cfg.merge_column_groups:
            for idx in range(
                self._col_index(start_letter) + 1,
                self._col_index(end_letter) + 1,
            ):
                merge_non_primary.add(get_column_letter(idx).lower())

        for row_idx, record in enumerate(data):
            excel_row = start_row + row_idx
            if auto_height:
                # 不写固定行高 → Excel 按内容自动适配（避免长文本被截断）
                ws.row_dimensions[excel_row].height = None
            else:
                ws.row_dimensions[excel_row].height = data_height

            for c in range(1, total_cols + 1):
                col_letter = get_column_letter(c).lower()

                # ── Value ──
                if col_letter in merge_non_primary:
                    formatted = ""  # 合并组的非首列：不填值
                elif c == seq_col:
                    formatted = row_idx + 1
                else:
                    db_field = mapping.get(col_letter, "")
                    raw = record.get(db_field, "") if db_field else ""
                    formatted = self._format_value(raw, col_letter, numeric_cols)

                cell = ws.cell(excel_row, c)
                cell.value = formatted

                # ── Style ──
                style = sample_styles[col_letter]
                cell.fill = style["fill"]
                cell.border = style["border"]

                # 字体：config 指定则统一（字号/字重），否则克隆模板样本行
                if font_size is not None:
                    base_name = font_name or style["font"].name or "等线"
                    cell.font = Font(name=base_name, size=font_size, bold=font_bold)
                else:
                    cell.font = style["font"]

                # 对齐：强制换行 + 垂直居中；水平对齐按 config 覆盖，否则克隆样本行
                if col_letter in center_cols:
                    horiz = "center"
                elif col_letter in left_cols:
                    horiz = "left"
                else:
                    horiz = style["alignment"].horizontal or "center"
                cell.alignment = Alignment(
                    wrap_text=True,
                    vertical="center",
                    horizontal=horiz,
                )

                # ── Risk label coloring ──
                if col_letter == risk_col and formatted:
                    color = self._pick_risk_color(str(formatted), risk_colors)
                    if color:
                        cell.font = Font(
                            bold=True,
                            size=cell.font.size or 10.5,
                            name=cell.font.name or "等线",
                            color=color,
                        )

    def _apply_column_widths(self, ws) -> None:
        """按 config.column_widths 覆盖模板列宽（未配置的列保持模板原宽）。"""
        for letter, width in self._cfg.column_widths.items():
            ws.column_dimensions[letter.upper()].width = width

    def _apply_page_setup(self, ws) -> None:
        """Set print/PDF page properties on the worksheet."""
        ps = self._cfg.page_setup
        ws.page_setup.orientation = ps.orientation
        ws.page_setup.paperSize = ps.paper_size
        ws.page_setup.fitToWidth = ps.fit_to_width
        ws.page_setup.fitToHeight = ps.fit_to_height
        ws.sheet_properties.pageSetUpPr = (
            openpyxl.worksheet.properties.PageSetupProperties(fitToPage=True)
        )

    def _strip_column_letters_row(self, ws) -> None:
        """删除模板中的列字母提示行（如 a, b, c, …），避免出现在导出中。

        config.column_letters_row 指定该行行号（1-based）；None = 不删除。
        仅删除无内容/纯字母占位行，不影响数据行。
        """
        row = self._cfg.column_letters_row
        if not row:
            return
        ws.delete_rows(row, 1)

    def _apply_data_row_heights(self, ws, count: int) -> None:
        """删除列字母行后，数据行号上移，重新显式应用行高。

        openpyxl 的 delete_rows 只移动单元格、不移动 row_dimensions，
        导致数据行可能继承被删行的旧高度（如 17.0），长文本会被截断。
        此处按自动适配模式将数据行高度重置为 None（Excel 打开时自动撑高）。
        """
        if not self._cfg.data_row_auto_height:
            return
        first = self._cfg.sample_row - (1 if self._cfg.column_letters_row else 0)
        for r in range(first, first + count):
            ws.row_dimensions[r].height = None

    def _apply_merge_groups(self, ws, count: int) -> None:
        """将每行配置的列组合并为一个单元格（仅保留首列值，取首列样式）。

        须在 ``_strip_column_letters_row`` 之后调用：openpyxl 的 delete_rows
        不会调整 merged_cells 范围，若先合并再删行会导致合并区域与数据行错位。
        """
        groups = self._cfg.merge_column_groups
        if not groups:
            return
        first = self._cfg.sample_row - (1 if self._cfg.column_letters_row else 0)
        for row_off in range(count):
            excel_row = first + row_off
            for start_letter, end_letter in groups:
                start_col = self._col_index(start_letter)
                end_col = self._col_index(end_letter)
                if start_col >= end_col:
                    continue
                ws.merge_cells(
                    start_row=excel_row, start_column=start_col,
                    end_row=excel_row, end_column=end_col,
                )

    def _apply_header_merges(self, ws) -> None:
        """合并表头明细行的列组（如 Q-U 五个明细列名合成一列并写入新列名）。

        须在 ``_strip_column_letters_row`` 之前调用：表头行号是模板绝对行号，
        删除列字母行不影响其上方行号。合并会清除组内非首列的原值。
        """
        row = self._cfg.header_merge_row
        if not row:
            return
        for start_letter, end_letter, text in self._cfg.header_merge_groups:
            start_col = self._col_index(start_letter)
            end_col = self._col_index(end_letter)
            if start_col >= end_col:
                continue
            ws.merge_cells(
                start_row=row, start_column=start_col,
                end_row=row, end_column=end_col,
            )
            ws.cell(row, start_col).value = text

    @staticmethod
    def _col_index(letter: str) -> int:
        """列字母 → 1-based 列号（a/A 均接受）。"""
        return openpyxl.utils.column_index_from_string(letter)

    # ── Static helpers ──────────────────────────────────────────────────

    @staticmethod
    def _format_value(value, col_letter: str, numeric_cols: frozenset) -> str | float:
        """Coerce value to the expected type for the column."""
        if value is None:
            return ""
        s = str(value).strip()
        if not s:
            return ""
        if col_letter in numeric_cols:
            try:
                return float(s)
            except ValueError:
                return s
        return s

    @staticmethod
    def _pick_risk_color(label: str, color_map: dict[str, str]) -> str | None:
        """Return the first color whose key is found in the label."""
        label_lower = label.lower()
        for keyword, color in color_map.items():
            if keyword.lower() in label_lower:
                return color
        return None
