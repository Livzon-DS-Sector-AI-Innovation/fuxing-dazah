"""MinIO / S3-compatible object storage service — 模块级 bucket 隔离。

每个模块拥有独立 bucket：{MINIO_BUCKET_PREFIX}-{module}，例如：
    dazah-equipment、dazah-production、dazah-quality。

所有文件访问通过后端代理，浏览器不需要直连 MinIO——只需一个端点。

Usage:
    from app.core.storage import upload_object, get_object, delete_object, is_enabled

    if is_enabled():
        upload_object("equipment", "inspection/abc.jpg", data, len(data), "image/jpeg")
        data, ct = get_object("equipment", "inspection/abc.jpg")
        delete_object("equipment", "inspection/abc.jpg")
"""

from __future__ import annotations

import logging
from io import BytesIO

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_client: "Minio | None" = None  # type: ignore[name-defined]
_enabled: bool | None = None
_known_buckets: set[str] = set()


def _init() -> None:
    global _client, _enabled
    if _enabled is not None:
        return
    settings = get_settings()
    _enabled = settings.MINIO_ENABLED
    if _enabled:
        from minio import Minio
        _client = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )


def _get_client() -> "Minio | None":  # type: ignore[name-defined]
    _init()
    return _client if _enabled else None


def _module_bucket(module: str) -> str:
    return f"{get_settings().MINIO_BUCKET_PREFIX}-{module}"


def _ensure_bucket(module: str) -> None:
    client = _get_client()
    if client is None:
        return
    bucket = _module_bucket(module)
    if bucket in _known_buckets:
        return
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            logger.info("Created MinIO bucket: %s", bucket)
        _known_buckets.add(bucket)
    except Exception:
        logger.exception("Failed to ensure MinIO bucket: %s", bucket)


def upload_object(
    module: str,
    object_key: str,
    data: bytes,
    length: int,
    content_type: str = "application/octet-stream",
) -> str:
    """上传对象，返回 object_key。"""
    client = _get_client()
    if client is None:
        raise RuntimeError("MinIO is not enabled")
    _ensure_bucket(module)
    client.put_object(
        bucket_name=_module_bucket(module),
        object_name=object_key,
        data=BytesIO(data),
        length=length,
        content_type=content_type,
    )
    return object_key


def get_object(module: str, object_key: str) -> "tuple[bytes, str] | None":  # type: ignore[name-defined]
    """读取对象，返回 (data, content_type)；不存在返回 None。"""
    client = _get_client()
    if client is None:
        return None
    from minio.error import S3Error
    try:
        resp = client.get_object(
            bucket_name=_module_bucket(module),
            object_name=object_key,
        )
        data = resp.read()
        ct = resp.getheader("Content-Type") or "application/octet-stream"
        resp.close()
        resp.release_conn()
        return data, ct
    except S3Error:
        return None


def delete_object(module: str, object_key: str) -> None:
    """删除对象。"""
    client = _get_client()
    if client is None:
        raise RuntimeError("MinIO is not enabled")
    client.remove_object(
        bucket_name=_module_bucket(module),
        object_name=object_key,
    )


def is_enabled() -> bool:
    _init()
    return _enabled or False
