"""office_client 基础类型与通用辅助函数。

仅放无资源依赖的公共契约（OfficeResult）与跨资源复用的纯函数。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

OPEN_API_BASE = "https://open.feishu.cn/open-apis"

# 飞书 Search v2 的 query 上限：按 Unicode 码点数计算，超过会被服务端拒绝。
SEARCH_QUERY_MAX_CHARS = 30

_HIGHLIGHT_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")


def _strip_highlight(text: str | None) -> str:
    """剥掉搜索结果中的 <h> / <hb> 高亮标签。"""
    if not text:
        return ""
    return _HIGHLIGHT_TAG_RE.sub("", text)


def _filename_from_disposition(disposition: str | None, fallback: str) -> str:
    """从 Content-Disposition 中解析文件名，失败则回退。"""
    if not disposition:
        return fallback
    # 优先解析 RFC 5987: filename*=UTF-8''...
    for part in disposition.split(";"):
        part = part.strip()
        if part.startswith("filename*=UTF-8''"):
            return quote(part.split("''", 1)[1], safe="")
        if part.startswith("filename="):
            return part.split("=", 1)[1].strip().strip('"')
    return fallback


def _column_letter(index: int) -> str:
    """把 1-based 列号转成 Excel 列字母（1→A，27→AA）。"""
    letters = ""
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _range_for_rows(rows: list[list[Any]]) -> str:
    """根据二维行数据生成写入默认工作表 Sheet1 的 range。"""
    if not rows:
        return "Sheet1!A1"
    row_count = len(rows)
    col_count = max((len(row) for row in rows), default=0) or 1
    return f"Sheet1!A1:{_column_letter(col_count)}{row_count}"


def _normalize_perm(perm: str) -> str:
    """把工具层的权限描述归一化为飞书 Drive 成员权限枚举。

    飞书成员权限枚举为 view / edit / full_access；工具层常用 manage 表示管理权限。
    """
    value = (perm or "").strip().lower()
    if value in {"manage", "admin", "full_access", "fullaccess"}:
        return "full_access"
    if value in {"edit", "write"}:
        return "edit"
    return "view"


@dataclass
class OfficeResult:
    """办公工具统一返回结构。

    Attributes:
        kind: 产物形态（link / file / data / error 等；本层不强制枚举值）。
        url: 飞书可编辑链接（kind=link 时使用）。
        file_token: 飞书文件 token。
        bytes: 文件二进制内容（kind=file 时使用）。
        content: 读取类工具的正文 / 表格数据 / 记录列表（kind=data 时使用）。
        truncated: 是否因超出长度/行数上限被截断。
        error: 失败时的错误描述。
        message: 面向用户的提示信息。
        file_name: 文件名（下载/上传时可选）。
        size: 文件大小（字节，可选）。
        meta: 其它弹性元数据（如 mime_type / total 等）。
    """

    kind: str | None = None
    url: str | None = None
    file_token: str | None = None
    bytes: bytes | None = None
    content: Any = None
    truncated: bool = False
    error: str | None = None
    message: str | None = None
    file_name: str | None = None
    size: int | None = None
    meta: dict[str, Any] | None = None

    @classmethod
    def link(
        cls,
        url: str,
        *,
        file_token: str | None = None,
        message: str | None = None,
    ) -> OfficeResult:
        """构造 link 型结果（飞书可编辑链接）。"""
        return cls(kind="link", url=url, file_token=file_token, message=message)

    @classmethod
    def file(
        cls,
        *,
        file_token: str | None = None,
        bytes: bytes | None = None,
        file_name: str | None = None,
        size: int | None = None,
    ) -> OfficeResult:
        """构造 file 型结果（下载 token / 二进制内容）。"""
        return cls(
            kind="file",
            file_token=file_token,
            bytes=bytes,
            file_name=file_name,
            size=size,
        )

    @classmethod
    def data(
        cls,
        content: Any,
        *,
        truncated: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> OfficeResult:
        """构造 data 型结果（正文 / 表格 / 记录等结构化数据）。"""
        return cls(kind="data", content=content, truncated=truncated, meta=meta)

    @classmethod
    def failure(cls, error: str) -> OfficeResult:
        """构造 error 型结果。"""
        return cls(kind="error", error=error)
