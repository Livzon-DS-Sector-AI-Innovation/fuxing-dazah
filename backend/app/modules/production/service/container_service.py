"""混装容器：CRUD 与库存计算。

容器是某中间体类型的混装池：产出入库（container_id）与消耗取用（container_id）
都只记账到容器，不做批次级溯源。
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models import MixingContainer
from app.modules.production.schemas import (
    MixingContainerCreate,
    MixingContainerOut,
    MixingContainerUpdate,
)
from app.platform.identity.models import User


async def get_container_stock(db: AsyncSession, container_id: uuid.UUID) -> float:
    """容器余量 = Σ落入产出 − Σ容器消耗（未删除口径，中止执行不计消耗）。"""
    return (await get_container_stocks(db, [container_id])).get(container_id, 0.0)


async def get_container_stocks(
    db: AsyncSession, container_ids: list[uuid.UUID],
) -> dict[uuid.UUID, float]:
    """批量容器余量（未删除口径，中止执行不计消耗，与消耗校验口径一致）。"""
    if not container_ids:
        return {}
    totals = {cid: 0.0 for cid in container_ids}
    for o in await repo.get_outputs_by_container_ids(db, container_ids):
        assert o.container_id is not None  # 查询按 container_id IN 过滤
        totals[o.container_id] += o.quantity
    for c in await repo.get_consumptions_by_container_ids(
        db, container_ids, exclude_aborted=True,
    ):
        assert c.container_id is not None  # 查询按 container_id IN 过滤
        totals[c.container_id] -= c.quantity
    return totals


async def create_container(
    db: AsyncSession, payload: MixingContainerCreate, user: User | None,
) -> MixingContainerOut:
    if await repo.get_intermediate_type(db, payload.intermediate_type_id) is None:
        raise NotFoundException("中间体类型", str(payload.intermediate_type_id))
    line = await repo.get_line(db, payload.line_id)
    if not line:
        raise NotFoundException("产线", str(payload.line_id))
    # 类型内名称唯一（软删除范围）由 DB 唯一索引兜底
    return await _insert_container(db, payload, user)


async def _insert_container(
    db: AsyncSession, payload: MixingContainerCreate, user: User | None,
) -> MixingContainerOut:
    from sqlalchemy.exc import IntegrityError

    row = MixingContainer(
        name=payload.name,
        intermediate_type_id=payload.intermediate_type_id,
        line_id=payload.line_id,
        remark=payload.remark,
        created_by=user.id if user else None,
        updated_by=user.id if user else None,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise AppException(
            status_code=400, message=f"容器名称 {payload.name} 在该中间体类型下已存在",
        ) from None
    return await _build_out(db, row)


async def update_container(
    db: AsyncSession, container_id: uuid.UUID,
    payload: MixingContainerUpdate, user: User | None,
) -> MixingContainerOut:
    row = await repo.get_mixing_container(db, container_id)
    if not row:
        raise NotFoundException("混装容器", str(container_id))
    if payload.line_id is not None and payload.line_id != row.line_id:
        # 已有出入库记录的容器不允许更换产线（历史流水归属不可变）
        if await repo.get_outputs_by_container(db, container_id) or \
                await repo.get_consumptions_by_container(db, container_id):
            raise AppException(
                status_code=400, message="该容器已有出入库记录，不能更换产线",
            )
        line = await repo.get_line(db, payload.line_id)
        if not line:
            raise NotFoundException("产线", str(payload.line_id))
        row.line_id = payload.line_id
    if payload.name is not None:
        row.name = payload.name
    if payload.remark is not None:
        row.remark = payload.remark
    row.updated_by = user.id if user else None
    # 名称唯一性由 DB 索引兜底，flush 失败转 400
    from sqlalchemy.exc import IntegrityError

    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise AppException(
            status_code=400, message=f"容器名称 {row.name} 在该中间体类型下已存在",
        ) from None
    refreshed = await repo.get_mixing_container(db, container_id)
    assert refreshed is not None
    return await _build_out(db, refreshed)


async def delete_container(
    db: AsyncSession, container_id: uuid.UUID, user: User | None,
) -> None:
    row = await repo.get_mixing_container(db, container_id)
    if not row:
        raise NotFoundException("混装容器", str(container_id))
    # 有流水记录不允许删除（数据完整性），仅空容器可删
    if await repo.get_outputs_by_container(db, container_id) or \
            await repo.get_consumptions_by_container(db, container_id):
        raise AppException(
            status_code=400, message="该容器已有出入库记录，不能删除",
        )
    row.is_deleted = True
    row.updated_by = user.id if user else None
    await db.flush()


async def list_containers(
    db: AsyncSession, intermediate_type_id: uuid.UUID | None = None,
) -> list[MixingContainerOut]:
    rows = await repo.list_mixing_containers(db, intermediate_type_id)
    return await _build_outs(db, rows)


async def _build_out(db: AsyncSession, row: MixingContainer) -> MixingContainerOut:
    return (await _build_outs(db, [row]))[0]


async def _build_outs(
    db: AsyncSession, rows: list[MixingContainer],
) -> list[MixingContainerOut]:
    """批量组装容器输出（类型名/产线名/余量各批量查一次，避免 N+1）。"""
    if not rows:
        return []
    type_ids = list({r.intermediate_type_id for r in rows})
    line_ids = list({r.line_id for r in rows})
    types = await repo.get_intermediate_types_by_ids(db, type_ids, include_deleted=True)
    type_names = {t.id: t.name for t in types}
    lines = await repo.get_lines_by_ids(db, line_ids)
    line_names = {ln.id: ln.name for ln in lines}
    stocks = await get_container_stocks(db, [r.id for r in rows])
    return [
        MixingContainerOut(
            id=r.id,
            name=r.name,
            intermediate_type_id=r.intermediate_type_id,
            intermediate_type_name=type_names.get(r.intermediate_type_id),
            line_id=r.line_id,
            line_name=line_names.get(r.line_id),
            remark=r.remark,
            available_quantity=stocks.get(r.id, 0.0),
        )
        for r in rows
    ]
