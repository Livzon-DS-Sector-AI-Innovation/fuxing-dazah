"""外部审计表 — 统一读取层

支持两种数据源:
  - Bitable: 通过 SafetyBitableClient 读取
  - Sheets (Excel): 通过 Feishu Sheets API 读取
"""

import logging
from typing import Any

import httpx

from app.modules.safety.feishu.bitable_client import SafetyBitableClient
from app.modules.safety.feishu.client import get_safety_tenant_token

logger = logging.getLogger(__name__)


async def read_table(config: dict) -> list[dict[str, Any]]:
    """按配置读取源表全部记录。

    返回统一格式: 每条记录 = {中文字段名: 原始值}

    Bitable 记录包含额外字段:
      - _record_id: Bitable record_id（用作 feishu_record_id）
    Sheets 记录包含额外字段:
      - _row_index: 行号（用作 feishu_record_id）
    """
    source = config["source"]
    source_type = source["type"]

    if source_type == "bitable":
        return await _read_bitable(config)
    elif source_type == "sheets":
        return await _read_sheets(config)
    else:
        raise ValueError(f"不支持的数据源类型: {source_type}")


# ============================================================
# Bitable 读取
# ============================================================


async def _read_bitable(config: dict) -> list[dict[str, Any]]:
    """通过 SafetyBitableClient 读取 Bitable 表全部记录。"""
    source = config["source"]
    client = SafetyBitableClient(
        app_token=source["app_token"],
        table_id=source["table_id"],
    )
    records = await client.list_all_records()
    result = []
    for rec in records:
        fields = {}
        raw_fields = rec.get("fields", {})
        for key, value in raw_fields.items():
            fields[key] = value
        fields["_record_id"] = rec.get("record_id", "")
        result.append(fields)
    logger.info(
        "Bitable 读取完成: %s → %d 条记录", config.get("label"), len(result)
    )
    return result


# ============================================================
# Sheets 读取
# ============================================================


async def _read_sheets(config: dict) -> list[dict[str, Any]]:
    """通过 Feishu Sheets API 读取表格数据。

    API 响应格式:
      {
        "data": {
          "valueRange": {
            "values": [
              ["表头1", "表头2", ...],   # 第1行=表头
              ["数据1", "数据2", ...],   # 第2行起=数据
              ...
            ]
          }
        }
      }
    """
    source = config["source"]
    columns = source.get("columns", [])
    spreadsheet_token = source["spreadsheet_token"]
    sheet_range = source["range"]
    sheet_id = source.get("sheet_id", "")
    header_row_index = source.get("header_row_index", 0)

    # Sheets API 需要 {sheet_id}!{range} 格式
    full_range = f"{sheet_id}!{sheet_range}" if sheet_id else sheet_range

    token = await get_safety_tenant_token()
    url = (
        f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets"
        f"/{spreadsheet_token}/values/{full_range}"
    )
    async with httpx.AsyncClient(timeout=30) as http_client:
        resp = await http_client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    if body.get("code") != 0:
        raise RuntimeError(
            f"Sheets API 错误: code={body.get('code')} msg={body.get('msg')}"
        )

    rows = body["data"]["valueRange"]["values"]

    # 解析表头
    if columns:
        headers = columns
    else:
        headers = rows[header_row_index] if rows else []
        rows = rows[header_row_index + 1 :]

    # 每行转 dict
    result = []
    for row_idx, row in enumerate(rows):
        fields = {}
        for col_idx, header in enumerate(headers):
            if col_idx < len(row):
                value = row[col_idx]
            else:
                value = None
            if header:
                fields[header] = value
        # 行号=range起始行 + 表头偏移 + 当前行
        start_row = _parse_range_start_row(sheet_range)
        actual_row = start_row + header_row_index + row_idx + 1  # 1-indexed
        fields["_row_index"] = actual_row
        result.append(fields)

    logger.info(
        "Sheets 读取完成: %s → %d 条记录", config.get("label"), len(result)
    )
    return result


def _parse_range_start_row(sheet_range: str) -> int:
    """从 Sheets range 字符串解析起始行号。

    例: "A3:G14" → 3, "数据表!A2:G20" → 2
    """
    # 去掉 sheet 名前缀（如 "数据表!"）
    range_part = sheet_range.split("!")[-1]
    # 提取起始单元格 → 解析行号
    start_cell = range_part.split(":")[0]
    # 去掉字母前缀
    row_str = "".join(c for c in start_cell if c.isdigit())
    return int(row_str) if row_str else 0
