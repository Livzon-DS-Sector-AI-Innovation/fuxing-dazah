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
    """上传的 Excel(.xlsx/.xlsm) → 首个工作表的行值（只要值，不做业务解析），供各导入入口共用。

    只走 openpyxl——旧版 .xls 在上传入口就被扩展名校验拒绝（提示另存为 .xlsx），
    这里读到读不开的只可能是加密/损坏/伪扩展名文件，抛 ValueError
    ——导入入口已把 ValueError 转成 400 提示，不会变成 500「服务内部错误」。
    """
    from openpyxl import load_workbook

    if not file_bytes:
        return []
    try:
        wb = load_workbook(BytesIO(file_bytes), data_only=True)
    except Exception as e:
        logger.warning("Excel 导入文件无法读取: %s: %s", type(e).__name__, e)
        raise ValueError(
            "无法读取该文件：文件可能已加密、已损坏，或是旧版 .xls（请用 Excel 打开后"
            "另存为 .xlsx 重新上传）"
        ) from e
    ws = wb.active
    if ws is None:
        return []
    return list(ws.iter_rows(values_only=True))


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
