"""物料容器数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    QualityContainerMovement,
    QualityMaterialContainer,
)

# ─── 容器台账 ───


async def create_material_containers(
    db: AsyncSession, rows: list[dict[str, Any]]
) -> list[QualityMaterialContainer]:
    """批量赋码。INSERT 后 flush 返回（RETURNING 回填 id）。"""
    objs = [QualityMaterialContainer(**row) for row in rows]
    db.add_all(objs)
    await db.flush()
    return objs


async def get_material_container_by_no(
    db: AsyncSession, container_no: str
) -> QualityMaterialContainer | None:
    stmt = (
        select(QualityMaterialContainer)
        .where(
            QualityMaterialContainer.container_no == container_no,
            QualityMaterialContainer.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_material_container(db: AsyncSession, cid: uuid.UUID) -> QualityMaterialContainer | None:
    stmt = select(QualityMaterialContainer).where(
        QualityMaterialContainer.id == cid,
        QualityMaterialContainer.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def max_container_seq(db: AsyncSession, prefix: str) -> int:
    """该前缀（MC-物料代码-日期-）下已有最大流水号，防并发时唯一索引兜底。"""
    val = await db.scalar(
        select(func.max(QualityMaterialContainer.seq)).where(
            QualityMaterialContainer.container_no.like(f"{prefix}%"),
            QualityMaterialContainer.is_deleted == False,  # noqa: E712
        )
    )
    return int(val or 0)


async def list_material_containers(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    batch_no: str | None = None,
    material_code: str | None = None,
) -> tuple[list[QualityMaterialContainer], int]:
    conds = [QualityMaterialContainer.is_deleted == False]  # noqa: E712
    if status:
        conds.append(QualityMaterialContainer.status == status)
    if batch_no:
        conds.append(QualityMaterialContainer.inbound_batch_no.like(f"%{batch_no}%"))
    if material_code:
        conds.append(QualityMaterialContainer.material_code.like(f"%{material_code}%"))
    total = await db.scalar(
        select(func.count()).select_from(QualityMaterialContainer).where(*conds)
    )
    stmt = (
        select(QualityMaterialContainer)
        .where(*conds)
        .order_by(QualityMaterialContainer.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def list_containers_by_nos(
    db: AsyncSession, container_nos: list[str]
) -> list[QualityMaterialContainer]:
    stmt = select(QualityMaterialContainer).where(
        QualityMaterialContainer.container_no.in_(container_nos),
        QualityMaterialContainer.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_container_status(
    db: AsyncSession, cid: uuid.UUID, status: str
) -> QualityMaterialContainer | None:
    container = await get_material_container(db, cid)
    if container is None:
        return None
    container.status = status
    await db.flush()
    stmt = select(QualityMaterialContainer).where(QualityMaterialContainer.id == cid)
    return (await db.execute(stmt)).scalar_one_or_none()


# ─── 进出库流水 ───


async def create_container_movement(
    db: AsyncSession,
    container_id: uuid.UUID,
    container_no: str,
    op_type: str,
    from_status: str,
    to_status: str,
    operator: uuid.UUID | None = None,
    related_doc: str | None = None,
    remark: str | None = None,
) -> QualityContainerMovement:
    movement = QualityContainerMovement(
        container_id=container_id,
        container_no=container_no,
        op_type=op_type,
        from_status=from_status,
        to_status=to_status,
        operator=operator,
        related_doc=related_doc,
        remark=remark,
    )
    db.add(movement)
    await db.flush()
    return movement


async def list_container_movements(
    db: AsyncSession, container_id: uuid.UUID
) -> list[QualityContainerMovement]:
    stmt = (
        select(QualityContainerMovement)
        .where(QualityContainerMovement.container_id == container_id)
        .order_by(QualityContainerMovement.op_at.desc())
        .limit(50)
    )
    return list((await db.execute(stmt)).scalars().all())
