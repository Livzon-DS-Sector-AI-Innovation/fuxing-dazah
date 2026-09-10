"""附件统一存储 helper（MinIO 优先 / 本地磁盘兜底）。

供 safety 模块全部下载/回读点复用，屏蔽两种存储方式的差异：
- MinIO 启用：对象存 bucket ``dazah-safety``，返回 object key；
- 未启用：落本地 ``uploads/safety/``，返回相对路径（与
  ``vision.utils.save_upload_to_storage`` 本地分支一致）。

``read_bytes`` / ``materialize`` / ``exists`` 接受的 ``path_or_key`` 支持三种路径语义：
  1. MinIO object key（新）：``hazard/file.jpg`` → MinIO bucket ``dazah-safety``；
  2. 干净相对路径（新，本地模式）：``safety/hazard/file.jpg``
     → ``{cwd}/uploads/safety/hazard/file.jpg``；
  3. 旧带 uploads/ 前缀路径（兼容存量数据）：``uploads/safety/hazard/file.jpg``
     → 剥离前缀后映射到 ``{cwd}/uploads/safety/hazard/file.jpg``。

本地路径解析复用 ``vision.utils.resolve_local_path``（三种约定统一处理），
MinIO 读写复用 ``app.core.storage``（bucket 隔离见该模块文档）。
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from app.core.storage import get_object, upload_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.vision.utils import resolve_local_path

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z._-]")


def safe_filename(filename: str) -> str:
    """清洗文件名：非法字符替换为 ``_``；拒绝空名与 ``.`` / ``..``。

    路径分隔符（``/``、``\\``）不在保留字符集内，会被替换为 ``_``，
    因此路径穿越片段无法原样穿透；``..`` 作为完整文件名时单独拒绝。
    """
    safe = _SAFE_NAME_RE.sub("_", filename)
    if not safe or safe in (".", ".."):
        raise ValueError(f"非法文件名: {filename!r}")
    return safe


def _check_subdir(subdir: str) -> str:
    """校验并规范化 subdir：拒绝空值、``.`` / ``..`` 段与首尾斜杠。"""
    normalized = subdir.replace("\\", "/").strip("/")
    if not normalized or any(seg in (".", "..") for seg in normalized.split("/")):
        raise ValueError(f"非法 subdir: {subdir!r}")
    return normalized


def store_bytes(
    subdir: str,
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """保存字节到 MinIO 或本地磁盘，返回存储标识。

    MinIO 模式：``upload_object("safety", "{subdir}/{safe_filename}", ...)``，
    返回 object key（如 ``hazard/file.jpg``）。
    本地模式：写 ``uploads/safety/{subdir}/{safe_filename}``，
    返回相对路径 ``safety/{subdir}/{safe_filename}``（不带 uploads/ 前缀，
    与 ``vision.utils.save_upload_to_storage`` / ``resolve_local_path`` 约定一致）。
    """
    subdir = _check_subdir(subdir)
    safe_name = safe_filename(filename)

    if minio_enabled():
        object_key = f"{subdir}/{safe_name}"
        upload_object("safety", object_key, data, len(data), content_type)
        return object_key

    upload_dir = os.path.join("uploads", "safety", subdir)
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, safe_name)
    with open(file_path, "wb") as f:
        f.write(data)
    return os.path.join("safety", subdir, safe_name)


def read_bytes(path_or_key: str) -> bytes | None:
    """读取存储中的字节；不存在返回 None。

    优先本地（``resolve_local_path`` 三种约定命中即读文件），
    否则 MinIO ``get_object("safety", path_or_key)``。
    """
    local = resolve_local_path(path_or_key)
    if local is not None:
        try:
            with open(local, "rb") as f:
                return f.read()
        except OSError:
            return None

    if minio_enabled():
        result = get_object("safety", path_or_key)
        if result is not None:
            return result[0]
    return None


def materialize(path_or_key: str, suffix: str = "") -> Path | None:
    """把存储内容物化到本地文件，返回路径；不存在返回 None。

    本地路径：原样返回（``resolve_local_path`` 三种约定命中即复用）；
    MinIO key：``get_object`` 下载到 ``tempfile.NamedTemporaryFile(delete=False, suffix=suffix)``，
    调用方负责用 :func:`cleanup_temp` 删除临时文件。
    """
    local = resolve_local_path(path_or_key)
    if local is not None:
        return Path(local)

    if minio_enabled():
        result = get_object("safety", path_or_key)
        if result is not None:
            data = result[0]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(data)
                return Path(tmp.name)
    return None


def cleanup_temp(path: str | Path) -> None:
    """删除 :func:`materialize` 产生的临时文件；不存在或删除失败时静默。"""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def exists(path_or_key: str) -> bool:
    """判断存储中是否存在（本地文件命中或 MinIO object 存在）。"""
    if resolve_local_path(path_or_key) is not None:
        return True
    if minio_enabled():
        return get_object("safety", path_or_key) is not None
    return False
