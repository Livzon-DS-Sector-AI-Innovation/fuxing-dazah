"""Work order image repository."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models.work_order_image import WorkOrderImage


async def create_image(
    db: AsyncSession, data: dict
) -> WorkOrderImage:
    image = WorkOrderImage(**data)
    db.add(image)
    await db.flush()
    return image


async def get_images_by_work_order(
    db: AsyncSession, work_order_id: uuid.UUID
) -> list[WorkOrderImage]:
    result = await db.execute(
        select(WorkOrderImage).where(
            WorkOrderImage.work_order_id == work_order_id,
            WorkOrderImage.is_deleted == False,  # noqa: E712
        ).order_by(WorkOrderImage.uploaded_at.asc())
    )
    return list(result.scalars().all())


async def get_image_by_id(
    db: AsyncSession, image_id: uuid.UUID
) -> WorkOrderImage | None:
    result = await db.execute(
        select(WorkOrderImage).where(
            WorkOrderImage.id == image_id,
            WorkOrderImage.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def delete_image(db: AsyncSession, image: WorkOrderImage) -> None:
    image.is_deleted = True
    await db.flush()
