"""模块级私有文件存储与上传校验的通用基座。

MinIO 开启时走 ``app.core.storage``（每模块独立 bucket：``{PREFIX}-{module}``）；
本地开发没有 MinIO 时回退到 ``UPLOAD_DIR/<module>/`` 目录。文件永远经后端 API
代理访问，浏览器不直连存储。各模块在此之上声明自己的允许类型与大小上限，
例如 qa 偏差附件（PDF/Office/图片，20MB）与 feedback 截图（仅图片，5MB）。
"""

from __future__ import annotations

import io
import logging
import mimetypes
import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from app.core import storage as object_storage
from app.core.config import get_settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


# ───────────────────────── 文件名与响应头 ─────────────────────────


def safe_filename(filename: str | None, default: str = "document") -> str:
    """剥掉路径、替换危险字符，保留中文/空格/括号；空值回落到 default。"""
    value = (filename or default).replace("\\", "/").rsplit("/", 1)[-1]
    value = re.sub(r"[^\w.()\-\u4e00-\u9fff ]", "_", value).strip()
    return value[:255] or default


def content_disposition(disposition: str, filename: str) -> str:
    """生成兼容 latin-1 响应头与 UTF-8 文件名的 Content-Disposition。"""
    safe_name = safe_filename(filename)
    ascii_name = safe_name.encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9.()_ -]", "_", ascii_name).strip()
    if not ascii_name or ascii_name.startswith("."):
        extension = Path(safe_name).suffix.lower()
        ascii_name = f"document{extension}"
    encoded_name = quote(safe_name, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


# 允许内联渲染的类型。text/html、image/svg+xml 一旦 inline 就是 API 域下的
# 存储型 XSS——next.config.ts 把 /api 重写到后端，与 auth_token 同源。图片要
# 放行是因为 Markdown 预览与截图缩略图用 <img src> 直接取文件；SVG 可以带脚本，不放。
_INLINE_MEDIA_TYPES = frozenset(
    {
        "application/pdf",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


def inline_media_type(mime_type: str | None) -> str | None:
    """可以安全内联渲染时返回归一化后的类型，否则返回 None。"""
    normalized = (mime_type or "").split(";", 1)[0].strip().casefold()
    return normalized if normalized in _INLINE_MEDIA_TYPES else None


# ───────────────────────── 内容魔数与上传校验 ─────────────────────────

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _zip_has(data: bytes, member_prefix: str) -> bool:
    if not data.startswith(b"PK"):
        return False
    try:
        with ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except (BadZipFile, OSError):
        return False
    return "[Content_Types].xml" in names and any(
        name.startswith(member_prefix) for name in names
    )


def magic_matches(extension: str, data: bytes) -> bool:
    """按扩展名（带前导点、小写）核对文件头；未知扩展名一律 False。"""
    if extension == ".pdf":
        return data.startswith(b"%PDF-")
    if extension in {".doc", ".xls"}:
        return data.startswith(_OLE_MAGIC)
    if extension == ".docx":
        return _zip_has(data, "word/")
    if extension == ".xlsx":
        return _zip_has(data, "xl/")
    if extension in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if extension == ".webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _size_label(max_size: int) -> str:
    megabytes = max_size / (1024 * 1024)
    return f"{int(megabytes)}MB" if megabytes.is_integer() else f"{megabytes:g}MB"


def validate_upload(
    filename: str | None,
    data: bytes,
    *,
    allowed: Mapping[str, str],
    max_size: int,
    kind_label: str,
    default_name: str = "attachment",
) -> tuple[str, str, str]:
    """校验扩展名、非空、大小与魔数，返回 (安全文件名, 不带点扩展名, MIME)。

    ``allowed`` 为「带点小写扩展名 → 入库 MIME」映射。浏览器送来的 content_type
    不可靠，不作为依据；扩展名与文件头才算数。
    """
    safe_name = safe_filename(filename, default_name)
    extension = Path(safe_name).suffix.lower()
    if extension not in allowed:
        raise AppException(status_code=422, message=f"仅支持 {kind_label} 附件")
    if not data:
        raise AppException(status_code=422, message="附件不能为空")
    if len(data) > max_size:
        raise AppException(
            status_code=422, message=f"附件大小不能超过 {_size_label(max_size)}"
        )
    if not magic_matches(extension, data):
        raise AppException(
            status_code=422, message="附件内容与扩展名不匹配或文件已损坏"
        )
    return safe_name, extension[1:], allowed[extension]


# ───────────────────────── 对象存储（MinIO 或本地目录回退）─────────────────────────


def is_safe_key(key: str) -> bool:
    return bool(key) and not key.startswith(("/", "\\")) and ".." not in Path(key).parts


def local_root(module: str) -> Path:
    """本地回退根目录 ``UPLOAD_DIR/<module>``，仅属主可读写。"""
    root = Path(get_settings().UPLOAD_DIR).expanduser() / module
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass
    return root


def _inside(root: Path, path: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def store_object(
    module: str,
    key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """写入对象并返回 key；不安全的 key 直接拒绝，不触碰任何存储。"""
    if not is_safe_key(key):
        raise ValueError("对象存储键不安全")
    if object_storage.is_enabled():
        return object_storage.upload_object(module, key, data, len(data), content_type)
    path = local_root(module) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def read_object(module: str, key: str) -> tuple[bytes, str] | None:
    """读取对象，返回 (data, content_type)；不存在或 key 不安全返回 None。"""
    if not is_safe_key(key):
        return None
    if object_storage.is_enabled():
        return object_storage.get_object(module, key)
    root = local_root(module)
    path = root / key
    if not path.is_file() or not _inside(root, path):
        return None
    return path.read_bytes(), (
        mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    )


def delete_object(module: str, key: str) -> None:
    if not is_safe_key(key):
        return
    if object_storage.is_enabled():
        object_storage.delete_object(module, key)
        return
    root = local_root(module)
    path = root / key
    if path.exists() and _inside(root, path):
        path.unlink(missing_ok=True)


def cleanup_object(module: str, key: str) -> None:
    """尽力删除、失败只记日志：用于写入半途失败或落库失败后的孤儿对象清理。"""
    try:
        delete_object(module, key)
    except Exception:
        logger.exception("Unable to clean up stored object %s/%s", module, key)
