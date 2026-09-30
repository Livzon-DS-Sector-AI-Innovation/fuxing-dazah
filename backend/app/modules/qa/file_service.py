"""QA 文件校验、私有存储和正文提取辅助。

文件永远通过 QA API 代理访问。生产环境使用独立 ``dazah-qa`` bucket；
本地开发没有 MinIO，回退到 ``UPLOAD_DIR/qa`` 下的本地目录。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from app.core import storage as object_storage
from app.core.config import get_settings

if TYPE_CHECKING:
    from app.modules.qa.document_processing import ExtractionDocument

logger = logging.getLogger(__name__)

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
    value = (filename or "document").replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"[^\w.()\-\u4e00-\u9fff ]", "_", value).strip()
    return value[:255] or "document"


def content_disposition(disposition: str, filename: str) -> str:
    """生成兼容 latin-1 响应头与 UTF-8 文件名的 Content-Disposition。"""
    safe_name = _safe_filename(filename)
    ascii_name = safe_name.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9.()_ -]", "_", ascii_name).strip()
    if not ascii_name or ascii_name.startswith("."):
        extension = Path(safe_name).suffix.lower()
        ascii_name = f"document{extension}"
    encoded_name = quote(safe_name, safe="")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{encoded_name}"
    )


# 允许内联渲染的类型。提取产物的 MIME 是从远端 ZIP 成员名推出来的
# （mineru._unzip_artifacts 里的 mimetypes.guess_type），成员名叫什么就
# 是什么；text/html、image/svg+xml 一旦 inline 就是 API 域下的存储型 XSS
# ——next.config.ts 把 /api 重写到后端，与 auth_token 同源。图片要放行是
# 因为 Markdown 预览用 <img src> 直接取产物；SVG 可以带脚本，不放。
_INLINE_MEDIA_TYPES = frozenset({
    "application/pdf",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
})


def inline_media_type(mime_type: str | None) -> str | None:
    """可以安全内联渲染时返回该类型，否则返回 None。"""

    normalized = (mime_type or "").split(";", 1)[0].strip().casefold()
    return normalized if normalized in _INLINE_MEDIA_TYPES else None


def _detect_magic(extension: str, data: bytes) -> bool:
    if extension == ".pdf":
        return data.startswith(b"%PDF-")
    if extension == ".docx":
        if not data.startswith(b"PK"):
            return False
        try:
            with ZipFile(__import__("io").BytesIO(data)) as archive:
                names = set(archive.namelist())
                return "[Content_Types].xml" in names and any(
                    name.startswith("word/") for name in names
                )
        except (BadZipFile, OSError):
            return False
    if extension == ".doc":
        return data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    return False


def validate_file(filename: str | None, content_type: str | None, data: bytes) -> tuple[str, str, str]:
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


def _local_root() -> Path:
    settings = get_settings()
    # 与 safety 等模块同口径：本地回退文件统一落在 UPLOAD_DIR 下的 qa/ 子目录。
    root = Path(settings.UPLOAD_DIR).expanduser() / "qa"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def store_file(filename: str | None, content_type: str | None, data: bytes) -> StoredFile:
    safe_name, extension, mime = validate_file(filename, content_type, data)
    digest = hashlib.sha256(data).hexdigest()
    key = f"documents/{uuid.uuid4().hex}.{extension}"
    try:
        if object_storage.is_enabled():
            object_storage.upload_object("qa", key, data, len(data), mime)
        else:
            path = _local_root() / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    except Exception:
        # 对象存储/本地写入可能在写入一半时失败；尽力清掉已产生的对象，
        # 避免没有数据库行可追踪的孤儿文件。
        cleanup_stored_file(key)
        raise
    return StoredFile(key, safe_name, extension, mime, len(data), digest)


def read_file(key: str) -> tuple[bytes, str] | None:
    if not _is_safe_key(key):
        return None
    if object_storage.is_enabled():
        return object_storage.get_object("qa", key)
    path = _local_root() / key
    if not path.is_file() or not path.resolve().is_relative_to(_local_root().resolve()):
        return None
    return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def store_object(
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """保存 QA 受保护对象，供原文件之外的解析产物复用同一存储策略。

    MinIO 开启时统一调用 ``app.core.storage``；本地开发沿用 QA 私有目录，
    这样切换提取后端不会引入第二套对象存储配置。
    """
    if not _is_safe_key(key):
        raise FileValidationError("对象存储键不安全")
    if object_storage.is_enabled():
        return object_storage.upload_object("qa", key, data, len(data), content_type)
    path = _local_root() / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def read_object(key: str) -> tuple[bytes, str] | None:
    """读取解析产物等任意 QA 私有对象。"""
    return read_file(key)


def delete_file(key: str) -> None:
    if not _is_safe_key(key):
        return
    if object_storage.is_enabled():
        object_storage.delete_object("qa", key)
        return
    path = _local_root() / key
    if path.exists() and path.resolve().is_relative_to(_local_root().resolve()):
        path.unlink(missing_ok=True)


def _is_safe_key(key: str) -> bool:
    return bool(key) and not key.startswith(("/", "\\")) and ".." not in Path(key).parts


def extract_text(extension: str, data: bytes) -> tuple[str, list[TextSegment]]:
    """提取可定位正文。

    扫描 PDF 返回 ``text_not_available`` 由 service 判断；旧 DOC 不解析。
    这里不做 OCR、不转换 Word。
    """
    from app.modules.qa.document_processing import parse_document

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
    from app.modules.qa.document_processing import parse_document

    return parse_document(extension, data, mode=mode)


def cleanup_stored_file(stored: StoredFile | str) -> None:
    key = stored.key if isinstance(stored, StoredFile) else stored
    try:
        delete_file(key)
    except Exception:
        logger.exception("Unable to clean up QA stored file %s", key)
