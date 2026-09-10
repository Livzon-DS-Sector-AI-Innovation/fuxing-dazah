"""办公只读工具（搜索/读文档/读表/读 Bitable/读云空间文件）。"""

from __future__ import annotations

import base64
from typing import Any

from pydantic_ai import RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.business_agent.tools.office_tools._common import (
    _result_to_dict,
)
from app.modules.safety.feishu.office_client import get_office_client


async def office_search_files(
    ctx: RunContext[SafetyDeps],
    query: str,
    space_id: str | None = None,
    page_size: int = 20,
) -> dict:
    """搜索飞书云空间 / 知识库文件。

    根据关键词查找当前应用可访问的飞书文档、表格、多维表格等云空间对象，
    返回名称、类型、token 和链接。后续可用 office_read_docx / office_read_sheet /
    office_read_base 读取具体内容。

    Args:
        query: 搜索关键词（文件名片段 / 文档主题，最多 30 个字符）
        space_id: 可选，限定某个知识库空间（wiki space_id）；不传则搜索全部可访问范围
        page_size: 返回条数上限（默认 20，最多 100）

    Returns:
        dict: {"kind": "data", "content": [{"name", "type", "token", "url"}],
               "total", "has_more"}
    """
    client = get_office_client(ctx)
    result = await client.search_files(
        query, space_id=space_id, page_size=page_size,
    )
    return _result_to_dict(result, "搜索云空间/知识库文件")


async def office_read_docx(
    ctx: RunContext[SafetyDeps],
    document_id: str,
    max_chars: int = 20000,
) -> dict:
    """读取飞书云文档正文（纯文本）。

    从飞书云文档链接（https://xxx.feishu.cn/docx/{document_id}）中提取
    document_id 后调用，返回文档纯文本内容。长文档会按 max_chars 截断，
    并通过 truncated=true 标记。

    Args:
        document_id: 云文档 token（docx 链接路径最后一段，如 doxcnXXXX）
        max_chars: 最大返回字符数（默认 20000）

    Returns:
        dict: {"kind": "data", "content": "正文", "truncated": false,
               "total_chars", "returned_chars"}
    """
    client = get_office_client(ctx)
    result = await client.read_docx_raw(document_id, max_chars=max_chars)
    return _result_to_dict(result, "读取云文档")


async def office_read_sheet(
    ctx: RunContext[SafetyDeps],
    spreadsheet_token: str,
    sheet_range: str,
    max_rows: int = 500,
    max_cols: int = 50,
) -> dict:
    """读取飞书电子表格指定区域的值。

    sheet_range 使用飞书 range 语法（如 "Sheet1!A1:Z100" 或 "0b12ab!A1:C5"）。
    返回二维数组 values，超出的行/列会被截断并标记 truncated=true。

    Args:
        spreadsheet_token: 电子表格 token（sheets 链接路径中的 token）
        sheet_range: 读取区域，如 "Sheet1!A1:D100"
        max_rows: 最大返回行数（默认 500）
        max_cols: 最大返回列数（默认 50）

    Returns:
        dict: {"kind": "data", "content": [["单元格", ...], ...],
               "truncated", "total_rows", "total_cols"}
    """
    client = get_office_client(ctx)
    result = await client.read_sheet(
        spreadsheet_token,
        sheet_range,
        max_rows=max_rows,
        max_cols=max_cols,
    )
    return _result_to_dict(result, "读取电子表格")


async def office_read_base(
    ctx: RunContext[SafetyDeps],
    app_token: str,
    table_id: str,
    page_size: int = 100,
    max_records: int = 500,
    view_id: str | None = None,
) -> dict:
    """读取飞书多维表格（Bitable）记录。

    从多维表格链接中提取 app_token 与 table_id 后调用，返回记录列表
    （每条含 record_id 与 fields）。超过 max_records 条时自动截断并标记
    truncated=true。

    Args:
        app_token: 多维表格应用 token（base 链接中的 app_token）
        table_id: 数据表 ID（tbl 开头）
        page_size: 每页记录数（默认 100，最多 100）
        max_records: 最大返回记录数（默认 500）
        view_id: 可选，指定视图 ID（不传读取默认视图）

    Returns:
        dict: {"kind": "data", "content": [{"record_id", "fields"}, ...],
               "truncated", "total", "returned_records"}
    """
    client = get_office_client(ctx)
    result = await client.read_base_records(
        app_token,
        table_id,
        page_size=page_size,
        max_records=max_records,
        view_id=view_id,
    )
    return _result_to_dict(result, "读取多维表格")


async def office_read_drive_file(
    ctx: RunContext[SafetyDeps],
    file_token: str,
    include_content: bool = False,
) -> dict:
    """读取飞书云空间普通文件；默认仅返回元数据。

    适用于云空间里的普通文件（file token），不适用于 docx/sheet/bitable 等
    在线文档（那些请用对应读取工具）。默认只返回文件元数据（type / size /
    file_name / meta），不下载文件内容；只有显式传入 include_content=True
    时才下载并以 content_base64 返回，避免大文件占满上下文。

    Args:
        file_token: 云空间文件 token（file 链接路径中的 token）
        include_content: 是否下载文件内容（默认 False，仅元数据）

    Returns:
        dict: {"kind": "data", "file_token", "type", "size",
               "file_name", "meta"}；include_content=True 时额外返回
               "content_base64"
    """
    client = get_office_client(ctx)
    meta_result = await client.file_metadata(file_token)
    if meta_result.kind == "error":
        return _result_to_dict(meta_result, "读取文件元数据")

    meta = meta_result.content if isinstance(meta_result.content, dict) else {}
    out: dict[str, Any] = {
        "kind": "data",
        "file_token": meta.get("file_token") or file_token,
        "type": meta.get("type") or meta.get("doc_type"),
        "size": meta.get("size"),
        "file_name": meta.get("name") or meta.get("file_name"),
        "url": meta.get("url"),
        "meta": meta,
    }

    if include_content:
        dl_result = await client.download_drive_file(file_token)
        if dl_result.kind == "error":
            out["error"] = f"下载文件内容失败：{dl_result.error}"
        elif dl_result.bytes is not None:
            out["content_base64"] = base64.b64encode(dl_result.bytes).decode()
            out["size"] = dl_result.size if dl_result.size is not None else out["size"]
            out["file_name"] = dl_result.file_name or out["file_name"]

    return out
