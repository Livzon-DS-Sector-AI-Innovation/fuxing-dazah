"""HR 模块 Excel 导入/导出公共工具。

api.py 与 headcount_routes.py 两个路由模块共用（api.py 挂载 headcount
router，直接互相 import 会循环，故抽独立小模块）。
"""

import logging
from io import BytesIO
from typing import Any
from urllib.parse import quote

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def read_first_sheet_rows(file_bytes: bytes) -> list[tuple[Any, ...]]:
    """上传的 Excel → 首个工作表的行值（只要值，不做业务解析），供各导入入口共用。

    .xlsx/.xlsm 走 openpyxl；旧版 .xls（Excel 97-2003，OLE 容器）openpyxl 打不开，
    回退 xlrd，两者读出的值口径一致（见 _read_xls_rows）。都读不了时抛 ValueError
    ——导入入口已把 ValueError 转成 400 提示，不会变成 500「服务内部错误」。
    """
    from openpyxl import load_workbook

    if not file_bytes:
        return []
    try:
        wb = load_workbook(BytesIO(file_bytes), data_only=True)
    except Exception:
        try:
            return _read_xls_rows(file_bytes)
        except Exception as e:
            logger.warning("Excel 导入文件无法读取: %s: %s", type(e).__name__, e)
            raise ValueError(
                "无法读取该文件：文件可能已加密、已损坏或不是 Excel 文件，"
                "请用 Excel 打开确认后另存为 .xlsx 重新上传"
            ) from e
    ws = wb.active
    if ws is None:
        return []
    return list(ws.iter_rows(values_only=True))


def _read_xls_rows(file_bytes: bytes) -> list[tuple[Any, ...]]:
    """旧版 .xls：xlrd 读首个工作表，值口径对齐 openpyxl。

    xlrd 原样读出来是：空格 ''、日期是序列号浮点数、错误值是 0-7 的整数、布尔是 0/1，
    直接交给各导入逻辑会误判（整行 '' 不会被当成空行跳过）。此处统一成
    空格 None、日期 datetime、整数值的数字去小数、布尔 bool。
    """
    import xlrd  # type: ignore[import-untyped]
    from xlrd.xldate import xldate_as_datetime  # type: ignore[import-untyped]

    def cell_value(ctype: int, value: Any, datemode: int) -> Any:
        if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_ERROR):
            return None
        if ctype == xlrd.XL_CELL_DATE:
            return xldate_as_datetime(value, datemode)
        if ctype == xlrd.XL_CELL_NUMBER:
            return int(value) if value.is_integer() else value
        if ctype == xlrd.XL_CELL_BOOLEAN:
            return bool(value)
        return value

    book = xlrd.open_workbook(file_contents=file_bytes)
    sheet = book.sheet_by_index(0)
    rows: list[tuple[Any, ...]] = []
    for rowx in range(sheet.nrows):
        types, values = sheet.row_types(rowx), sheet.row_values(rowx)
        rows.append(tuple(
            cell_value(ctype, value, book.datemode) for ctype, value in zip(types, values)
        ))
    return rows


def xlsx_response(wb, filename: str) -> StreamingResponse:
    """openpyxl 工作簿 → xlsx 下载响应（统一保存/媒体类型/文件名头）。

    文件名支持中文：HTTP 头只能 latin-1，按 RFC 5987 双写——
    filename= ASCII 兜底 + filename*=utf-8'' 百分号编码（前端
    fetchHrDownload 解析 filename* 还原中文名，浏览器直下也认）。
    """
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    ascii_fallback = filename.encode("ascii", "ignore").decode() or "export.xlsx"
    return StreamingResponse(
        buf,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": (
            f'attachment; filename="{ascii_fallback}"; filename*=utf-8\'\'{quote(filename)}'
        )},
    )


def write_sheet(ws, headers: list[str], rows: list[list[Any]]) -> None:
    """写表头（加粗居中）与数据行；None → ""，其余 str() 落格。"""
    from openpyxl.styles import Alignment, Font

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")
    for row_idx, row in enumerate(rows, 2):
        for col_idx, val in enumerate(row, 1):
            ws.cell(row=row_idx, column=col_idx, value="" if val is None else str(val))
