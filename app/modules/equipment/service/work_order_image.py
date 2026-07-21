"""Work order image service."""

import base64
import logging
import os
import uuid

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models.work_order_image import WorkOrderImage

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

VALID_MAGICS: dict[bytes, str] = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG": "png",
    b"RIFF": "webp",
    b"BM": "bmp",
}


async def upload_images(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    files: list[UploadFile],
) -> list[WorkOrderImage]:
    from app.core.storage import is_enabled as minio_enabled
    from app.core.storage import upload_object

    settings = get_settings()
    wo = await repo.get_work_order_by_id(db, work_order_id)
    if not wo:
        raise NotFoundException("工单", str(work_order_id))

    existing = await repo.get_images_by_work_order(db, work_order_id)
    if len(existing) + len(files) > 9:
        raise AppException(message="每个工单最多上传9张图片")

    upload_dir = os.path.join(settings.UPLOAD_DIR, "work-orders", str(work_order_id))
    os.makedirs(upload_dir, exist_ok=True)

    images = []
    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise AppException(message=f"不支持的文件类型: {ext}")

        file_size = file.size
        if file_size is None:
            raise AppException(message="无法获取文件大小")
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if file_size > max_bytes:
            raise AppException(
                message=f"文件大小超过限制（{settings.MAX_UPLOAD_SIZE_MB}MB）"
            )

        stored_name = f"{uuid.uuid4()}{ext}"
        content = await file.read()

        if minio_enabled():
            object_key = f"work-orders/{work_order_id}/{stored_name}"
            upload_object(
                module="equipment",
                object_key=object_key,
                data=content,
                length=len(content),
                content_type=file.content_type or "image/jpeg",
            )
            stored_path = object_key
        else:
            file_path = os.path.join(upload_dir, stored_name)
            with open(file_path, "wb") as f:
                f.write(content)
            stored_path = file_path

        image = await repo.create_image(db, {
            "work_order_id": work_order_id,
            "file_name": file.filename or stored_name,
            "file_path": stored_path,
            "file_size": file_size,
        })
        images.append(image)

    return images


async def get_images(
    db: AsyncSession, work_order_id: uuid.UUID
) -> list[WorkOrderImage]:
    return await repo.get_images_by_work_order(db, work_order_id)


async def delete_image(db: AsyncSession, image_id: uuid.UUID) -> None:
    from app.core.storage import delete_object
    from app.core.storage import is_enabled as minio_enabled

    image = await repo.get_image_by_id(db, image_id)
    if not image:
        raise NotFoundException("图片", str(image_id))

    if minio_enabled():
        try:
            delete_object("equipment", image.file_path)
        except Exception:
            # 删除 MinIO 文件失败不阻塞数据库操作，记录日志方便排查
            logger.exception("删除 MinIO 文件失败: %s", image.file_path)
    elif os.path.exists(image.file_path):
        os.remove(image.file_path)

    await repo.delete_image(db, image)


async def delete_images_by_work_order(
    db: AsyncSession, work_order_id: uuid.UUID
) -> int:
    """删除工单的所有图片（软删除 + 物理文件清理）。返回实际成功删除数量。"""
    images = await repo.get_images_by_work_order(db, work_order_id)
    deleted = 0
    for image in images:
        try:
            await delete_image(db, image.id)
            deleted += 1
        except Exception:
            logger.exception("删除工单图片失败: image_id=%s", image.id)
    return deleted


async def save_photo_from_base64(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    image_b64: str,
    filename: str = "",
) -> WorkOrderImage:
    """从 base64 编码保存工单照片到 MinIO（或本地）和数据库。

    对标巡检模块的 save_photo_from_base64，用于 MCP 工具上传工单现场照片。
    """
    from app.core.storage import is_enabled as minio_enabled
    from app.core.storage import upload_object

    max_size = 10 * 1024 * 1024  # 10 MB

    try:
        content = base64.b64decode(image_b64, validate=True)
    except Exception as e:
        raise AppException(message=f"图片 base64 解码失败：{e}")

    if len(content) > max_size:
        size_mb = len(content) / 1024 / 1024
        raise AppException(message=f"图片大小 {size_mb:.1f}MB 超过上限 10MB")

    if len(content) < 64:
        raise AppException(message="图片数据过小，可能不是有效图片")

    # 检查工单存在且图片数量未超限
    wo = await repo.get_work_order_by_id(db, work_order_id)
    if not wo:
        raise NotFoundException("工单", str(work_order_id))

    existing = await repo.get_images_by_work_order(db, work_order_id)
    if len(existing) >= 9:
        raise AppException(message="每个工单最多上传9张图片")

    # 识别图片格式
    magic = content[:4]
    ext = "jpg"
    for magic_bytes, fmt in VALID_MAGICS.items():
        if magic.startswith(magic_bytes):
            ext = fmt
            break

    fname = filename or f"{uuid.uuid4()}.{ext}"

    if minio_enabled():
        object_key = f"work-orders/{work_order_id}/{fname}"
        upload_object(
            module="equipment",
            object_key=object_key,
            data=content,
            length=len(content),
            content_type="image/jpeg",
        )
        stored_path = object_key
    else:
        upload_dir = os.path.join(
            get_settings().UPLOAD_DIR, "work-orders", str(work_order_id)
        )
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, fname)
        with open(file_path, "wb") as f:
            f.write(content)
        stored_path = file_path

    image = await repo.create_image(db, {
        "work_order_id": work_order_id,
        "file_name": fname,
        "file_path": stored_path,
        "file_size": len(content),
    })
    return image
