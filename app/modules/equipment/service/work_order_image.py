"""Work order image service."""

import os
import uuid

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.models.work_order_image import WorkOrderImage

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


async def upload_images(
    db: AsyncSession,
    work_order_id: uuid.UUID,
    files: list[UploadFile],
) -> list[WorkOrderImage]:
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
        file_path = os.path.join(upload_dir, stored_name)

        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)

        image = await repo.create_image(db, {
            "work_order_id": work_order_id,
            "file_name": file.filename or stored_name,
            "file_path": file_path,
            "file_size": file_size,
        })
        images.append(image)

    return images


async def get_images(
    db: AsyncSession, work_order_id: uuid.UUID
) -> list[WorkOrderImage]:
    return await repo.get_images_by_work_order(db, work_order_id)


async def delete_image(db: AsyncSession, image_id: uuid.UUID) -> None:
    image = await repo.get_image_by_id(db, image_id)
    if not image:
        raise NotFoundException("图片", str(image_id))

    if os.path.exists(image.file_path):
        os.remove(image.file_path)

    await repo.delete_image(db, image)
