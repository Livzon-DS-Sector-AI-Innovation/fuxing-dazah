"""QA 文件校验、私有存储和正文提取辅助。

文件永远通过 QA API 代理访问。存储/响应头/魔数等通用能力委托给
``app.core.file_storage``（MinIO 开启用独立 ``dazah-qa`` bucket，本地开发回退到
``UPLOAD_DIR/qa``）；这里只保留 QA 文档归档专用的校验规则与正文提取。

本模块对外函数名保持稳定：qa 内部以模块属性方式调用，测试也以此为 patch 点。
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.core import file_storage

if TYPE_CHECKING:
    from app.modules.qa.processing.document import ExtractionDocument

_MODULE = "qa"

MAX_FILE_SIZE = 50 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}
ALLOWED_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
    ".doc": {"application/msword", "application/octet-stream"},
}


class FileValidationError(ValueError):
    """文件不符合 QA 归档限制。"""


@dataclass(frozen=True)
class StoredFile:
    key: str
    original_filename: str
    # 不带前导点，和 qa.document_files.extension 的数据库约束保持一致。
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class TextSegment:
    content: str
    locator: str
    page_number: int | None = None
    paragraph_index: int | None = None
    table_index: int | None = None
    cell_index: int | None = None


def _safe_filename(filename: str | None) -> str:
    return file_storage.safe_filename(filename, "document")


content_disposition = file_storage.content_disposition
inline_media_type = file_storage.inline_media_type


def _detect_magic(extension: str, data: bytes) -> bool:
    return file_storage.magic_matches(extension, data)


def validate_file(
    filename: str | None, content_type: str | None, data: bytes
) -> tuple[str, str, str]:
    """校验扩展名、MIME、大小和魔数，返回安全文件名/扩展名/MIME。"""
    safe_name = _safe_filename(filename)
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise FileValidationError("仅支持 PDF、DOCX 或 DOC 文件")
    if not data:
        raise FileValidationError("文件不能为空")
    if len(data) > MAX_FILE_SIZE:
        raise FileValidationError("文件大小不能超过 50MB")
    supplied = (content_type or "").split(";", 1)[0].strip().lower()
    allowed = ALLOWED_MIME_TYPES[extension]
    # 浏览器可能发送 application/octet-stream；扩展名和魔数仍是最终依据。
    if supplied and supplied not in allowed:
        if supplied != "application/octet-stream":
            raise FileValidationError("文件 MIME 类型与扩展名不匹配")
    if not _detect_magic(extension, data):
        raise FileValidationError("文件内容与扩展名不匹配或文件已损坏")
    mime = mimetypes.guess_type(safe_name)[0] or supplied or "application/octet-stream"
    if extension == ".docx":
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif extension == ".doc":
        mime = "application/msword"
    elif extension == ".pdf":
        mime = "application/pdf"
    # 数据库存储统一使用 pdf/docx/doc，而不是 .pdf/.docx/.doc。
    return safe_name, extension[1:], mime


def store_file(
    filename: str | None, content_type: str | None, data: bytes
) -> StoredFile:
    safe_name, extension, mime = validate_file(filename, content_type, data)
    digest = hashlib.sha256(data).hexdigest()
    key = f"documents/{uuid.uuid4().hex}.{extension}"
    try:
        file_storage.store_object(_MODULE, key, data, mime)
    except Exception:
        # 对象存储/本地写入可能在写入一半时失败；尽力清掉已产生的对象，
        # 避免没有数据库行可追踪的孤儿文件。
        cleanup_stored_file(key)
        raise
    return StoredFile(key, safe_name, extension, mime, len(data), digest)


def read_file(key: str) -> tuple[bytes, str] | None:
    return file_storage.read_object(_MODULE, key)


def store_object(
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """保存 QA 受保护对象，供原文件之外的解析产物复用同一存储策略。"""
    if not _is_safe_key(key):
        raise FileValidationError("对象存储键不安全")
    return file_storage.store_object(_MODULE, key, data, content_type)


def read_object(key: str) -> tuple[bytes, str] | None:
    """读取解析产物等任意 QA 私有对象。"""
    return read_file(key)


def delete_file(key: str) -> None:
    file_storage.delete_object(_MODULE, key)


def _is_safe_key(key: str) -> bool:
    return file_storage.is_safe_key(key)


def extract_text(extension: str, data: bytes) -> tuple[str, list[TextSegment]]:
    """提取可定位正文。

    扫描 PDF 返回 ``text_not_available`` 由 service 判断；旧 DOC 不解析。
    这里不做 OCR、不转换 Word。
    """
    from app.modules.qa.processing.document import parse_document

    extension = extension.lower().lstrip(".")
    parsed = parse_document(extension, data)
    if parsed.status != "ready":
        return parsed.status, []

    # 这是旧 endpoint 的兼容视图：PDF 仍按页聚合，DOCX 表格仍按 cell
    # 返回；新版 raw block/chunk API 则使用 extract_document 的完整结构。
    if extension == "pdf":
        grouped: dict[int, list[str]] = {}
        for block in parsed.blocks:
            if block.page_number is not None:
                grouped.setdefault(block.page_number, []).append(block.content)
        return "ready", [
            TextSegment(
                "\n".join(parts),
                f"第 {page_number} 页",
                page_number=page_number,
            )
            for page_number, parts in sorted(grouped.items())
        ]

    segments: list[TextSegment] = []
    table_cell_counters: dict[int, int] = {}
    for block in parsed.blocks:
        if block.table_index is None:
            segments.append(
                TextSegment(
                    block.content,
                    f"段落 {block.paragraph_index}"
                    if block.paragraph_index is not None
                    else block.locator,
                    paragraph_index=block.paragraph_index,
                )
            )
            continue
        cells = block.source_metadata.get("cells", [])
        if not isinstance(cells, list) or not cells:
            cells = [{"text": block.content}]
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            text = str(cell.get("text") or "").strip()
            if not text:
                continue
            index = table_cell_counters.get(block.table_index, 0) + 1
            table_cell_counters[block.table_index] = index
            segments.append(
                TextSegment(
                    text,
                    f"表格 {block.table_index} / 单元格 {index}",
                    table_index=block.table_index,
                    cell_index=index,
                )
            )
    return "ready", segments


def extract_document(
    extension: str, data: bytes, *, mode: str = "native_text"
) -> ExtractionDocument:
    """返回包含 raw block/chunk 的新版解析结果。"""
    from app.modules.qa.processing.document import parse_document

    return parse_document(extension, data, mode=mode)


def cleanup_stored_file(stored: StoredFile | str) -> None:
    """尽力删除已写入的对象；失败只记日志（与 core 的通用清理同口径）。"""
    key = stored.key if isinstance(stored, StoredFile) else stored
    file_storage.cleanup_object(_MODULE, key)
