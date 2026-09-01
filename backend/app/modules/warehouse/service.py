"""Warehouse business workflows: 库存、出入库与盘点的状态流转与事务编排。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.warehouse import repository
from app.modules.warehouse.models import (
    WarehouseLocation,
    WarehouseMaterial,
    WarehouseMovement,
    WarehouseStock,
    WarehouseStocktake,
    WarehouseStocktakeItem,
)
from app.modules.warehouse.schemas import (
    LocationCreate,
    LocationUpdate,
    MaterialCreate,
    MaterialUpdate,
    MovementCreate,
    StocktakeCreate,
    StocktakeUpdate,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

_MOVEMENT_NO_PREFIX = {"inbound": "IN", "outbound": "OUT", "adjust": "ADJ"}
_QUANTITY_QUANTUM = Decimal("0.0001")


def _to_decimal(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_QUANTITY_QUANTUM)


def _generate_no(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:6].upper()}"


# ── 物料主数据 ──


async def create_material(
    db: AsyncSession, payload: MaterialCreate, user: User
) -> WarehouseMaterial:
    if await repository.get_material_by_code(db, payload.code):
        raise AppException(status_code=409, message=f"物料编码 {payload.code} 已存在")
    material = WarehouseMaterial(
        code=payload.code.strip(),
        name=payload.name.strip(),
        category=payload.category,
        spec=payload.spec,
        unit=payload.unit.strip(),
        safety_stock=_to_decimal(payload.safety_stock),
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(material)
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.material.create",
        user=user,
        resource_type="warehouse_material",
        resource_id=material.id,
        new_value={"code": material.code, "name": material.name},
    )
    return material


async def update_material(
    db: AsyncSession, material_id: UUID, payload: MaterialUpdate, user: User
) -> WarehouseMaterial:
    material = await repository.get_material(db, material_id)
    if not material:
        raise NotFoundException("物料", str(material_id))
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "safety_stock":
            material.safety_stock = _to_decimal(value)
        else:
            setattr(material, field, value)
    material.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.material.update",
        user=user,
        resource_type="warehouse_material",
        resource_id=material.id,
        new_value=data,
    )
    # UPDATE 后 re-fetch，保证 updated_at 等回填字段可安全序列化
    refreshed = await repository.get_material(db, material.id)
    assert refreshed is not None
    return refreshed


async def delete_material(db: AsyncSession, material_id: UUID, user: User) -> None:
    material = await repository.get_material(db, material_id)
    if not material:
        raise NotFoundException("物料", str(material_id))
    if await repository.exists_stock_for_material(db, material.id):
        raise AppException(status_code=400, message="物料仍有库存，不能删除")
    material.is_deleted = True
    material.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.material.delete",
        user=user,
        resource_type="warehouse_material",
        resource_id=material.id,
        old_value={"code": material.code, "name": material.name},
    )


# ── 库位 ──


async def create_location(
    db: AsyncSession, payload: LocationCreate, user: User
) -> WarehouseLocation:
    if await repository.get_location_by_code(db, payload.code):
        raise AppException(status_code=409, message=f"库位编码 {payload.code} 已存在")
    location = WarehouseLocation(
        code=payload.code.strip(),
        name=payload.name.strip(),
        location_type=payload.location_type,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(location)
    await db.flush()
    return location


async def update_location(
    db: AsyncSession, location_id: UUID, payload: LocationUpdate, user: User
) -> WarehouseLocation:
    location = await repository.get_location(db, location_id)
    if not location:
        raise NotFoundException("库位", str(location_id))
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field, value)
    location.updated_by = user.id if user else None
    await db.flush()
    return await repository.get_location(db, location.id)  # type: ignore[return-value]


async def delete_location(db: AsyncSession, location_id: UUID, user: User) -> None:
    location = await repository.get_location(db, location_id)
    if not location:
        raise NotFoundException("库位", str(location_id))
    if await repository.exists_stock_in_location(db, location.id):
        raise AppException(status_code=400, message="库位下仍有库存，不能删除")
    location.is_deleted = True
    location.updated_by = user.id if user else None
    await db.flush()


# ── 库存维护（内部工具） ──


async def _add_stock_delta(
    db: AsyncSession,
    *,
    material: WarehouseMaterial,
    location: WarehouseLocation,
    batch_no: str,
    delta: Decimal,
) -> None:
    """按物料+批次+库位增减库存，行不存在则新建；不允许出现负库存。"""
    stock = await repository.get_stock_row(
        db, material_id=material.id, batch_no=batch_no, location_id=location.id
    )
    if stock is None:
        if delta < 0:
            raise AppException(status_code=400, message="库存不足，无法出库")
        stock = WarehouseStock(
            material_id=material.id,
            material_code=material.code,
            material_name=material.name,
            batch_no=batch_no,
            location_id=location.id,
            location_code=location.code,
            location_name=location.name,
            quantity=Decimal("0"),
        )
        db.add(stock)
    new_quantity = (stock.quantity + delta).quantize(_QUANTITY_QUANTUM)
    if new_quantity < 0:
        raise AppException(
            status_code=400,
            message=f"库存不足：当前库存 {stock.quantity}，本次需出库 {-delta}",
        )
    stock.quantity = new_quantity
    await db.flush()


async def _set_stock_quantity(
    db: AsyncSession,
    item: WarehouseStocktakeItem,
    counted: Decimal,
) -> None:
    """盘点确认：把库存设置为实盘数量。"""
    stock = await repository.get_stock_row(
        db, material_id=item.material_id, batch_no=item.batch_no, location_id=item.location_id
    )
    if stock is None:
        if counted == 0:
            return
        stock = WarehouseStock(
            material_id=item.material_id,
            material_code=item.material_code,
            material_name=item.material_name,
            batch_no=item.batch_no,
            location_id=item.location_id,
            location_code=item.location_code,
            location_name=item.location_name,
            quantity=Decimal("0"),
        )
        db.add(stock)
    stock.quantity = counted
    await db.flush()


# ── 出入库 ──


async def create_movement(
    db: AsyncSession, payload: MovementCreate, user: User
) -> WarehouseMovement:
    material = await repository.get_material(db, UUID(payload.material_id))
    if not material:
        raise NotFoundException("物料", payload.material_id)
    location = await repository.get_location(db, UUID(payload.location_id))
    if not location:
        raise NotFoundException("库位", payload.location_id)

    quantity = _to_decimal(payload.quantity)
    occurred_at = payload.occurred_at or datetime.now(UTC)
    movement = WarehouseMovement(
        movement_no=_generate_no(_MOVEMENT_NO_PREFIX[payload.direction]),
        direction=payload.direction,
        source_type=payload.source_type,
        material_id=material.id,
        material_code=material.code,
        material_name=material.name,
        batch_no=payload.batch_no.strip(),
        quantity=quantity,
        unit=material.unit,
        location_id=location.id,
        location_code=location.code,
        location_name=location.name,
        occurred_at=occurred_at,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(movement)
    delta = quantity if payload.direction == "inbound" else -quantity
    await _add_stock_delta(
        db, material=material, location=location, batch_no=movement.batch_no, delta=delta
    )
    await db.flush()
    await record_audit_log(
        db,
        action=f"warehouse.movement.{payload.direction}",
        user=user,
        resource_type="warehouse_movement",
        resource_id=movement.id,
        new_value={
            "movement_no": movement.movement_no,
            "material": material.code,
            "quantity": float(quantity),
            "location": location.code,
        },
    )
    return movement


async def delete_movement(db: AsyncSession, movement_id: UUID, user: User) -> None:
    movement = await repository.get_movement(db, movement_id)
    if not movement:
        raise NotFoundException("出入库记录", str(movement_id))
    if movement.direction == "adjust":
        raise AppException(status_code=400, message="盘点调整记录不可删除，请通过盘点流程修正")
    material = await repository.get_material(db, movement.material_id)
    location = await repository.get_location(db, movement.location_id)
    if material is None or location is None:
        raise AppException(status_code=400, message="物料或库位已不存在，无法撤销该记录")
    # 反向冲销：入库删除则减库存，出库删除则加回
    delta = -movement.quantity if movement.direction == "inbound" else movement.quantity
    await _add_stock_delta(
        db, material=material, location=location, batch_no=movement.batch_no, delta=delta
    )
    movement.is_deleted = True
    movement.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.movement.delete",
        user=user,
        resource_type="warehouse_movement",
        resource_id=movement.id,
        old_value={"movement_no": movement.movement_no, "direction": movement.direction},
    )


# ── 盘点 ──


async def create_stocktake(
    db: AsyncSession, payload: StocktakeCreate, user: User
) -> WarehouseStocktake:
    scope_location = None
    if payload.scope_location_id:
        scope_location = await repository.get_location(db, UUID(payload.scope_location_id))
        if not scope_location:
            raise NotFoundException("库位", payload.scope_location_id)

    stocks = await repository.list_stocks_for_snapshot(
        db, location_id=scope_location.id if scope_location else None
    )
    if not stocks:
        raise AppException(status_code=400, message="盘点范围内没有库存记录，无法创建盘点")

    stocktake = WarehouseStocktake(
        stocktake_no=_generate_no("ST"),
        status="draft",
        scope_location_id=scope_location.id if scope_location else None,
        scope_location_code=scope_location.code if scope_location else None,
        scope_location_name=scope_location.name if scope_location else None,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(stocktake)
    await db.flush()
    for stock in stocks:
        db.add(
            WarehouseStocktakeItem(
                stocktake_id=stocktake.id,
                material_id=stock.material_id,
                material_code=stock.material_code,
                material_name=stock.material_name,
                batch_no=stock.batch_no,
                location_id=stock.location_id,
                location_code=stock.location_code,
                location_name=stock.location_name,
                book_quantity=stock.quantity,
                counted_quantity=None,
            )
        )
    await db.flush()
    return stocktake


async def _load_stocktake_with_items(
    db: AsyncSession, stocktake_id: UUID
) -> tuple[WarehouseStocktake, list[WarehouseStocktakeItem]]:
    stocktake = await repository.get_stocktake(db, stocktake_id)
    if not stocktake:
        raise NotFoundException("盘点单", str(stocktake_id))
    items = await repository.list_stocktake_items(db, stocktake.id)
    return stocktake, items


async def update_stocktake(
    db: AsyncSession, stocktake_id: UUID, payload: StocktakeUpdate, user: User
) -> WarehouseStocktake:
    stocktake, items = await _load_stocktake_with_items(db, stocktake_id)
    if stocktake.status != "draft":
        raise AppException(status_code=400, message="盘点单已确认，不能修改")
    items_by_id = {item.id: item for item in items}
    updated = 0
    for row in payload.items:
        item = items_by_id.get(UUID(row.item_id))
        if not item:
            raise NotFoundException("盘点明细", row.item_id)
        if row.counted_quantity is not None:
            item.counted_quantity = _to_decimal(row.counted_quantity)
        else:
            item.counted_quantity = None
        item.remark = row.remark
        updated += 1
    stocktake.updated_by = user.id if user else None
    await db.flush()
    fresh = await repository.get_stocktake(db, stocktake.id)
    assert fresh is not None
    return fresh


async def confirm_stocktake(
    db: AsyncSession, stocktake_id: UUID, user: User
) -> WarehouseStocktake:
    stocktake, items = await _load_stocktake_with_items(db, stocktake_id)
    if stocktake.status != "draft":
        raise AppException(status_code=400, message="盘点单已确认，不能重复确认")
    uncounted = [item for item in items if item.counted_quantity is None]
    if uncounted:
        raise AppException(
            status_code=400,
            message=f"还有 {len(uncounted)} 条明细未填写实盘数量，不能确认",
        )
    # 批量取物料单位，供调整流水冗余展示
    material_units: dict[uuid.UUID, str] = {}
    for material_id in {item.material_id for item in items}:
        material = await repository.get_material(db, material_id)
        if material:
            material_units[material_id] = material.unit

    adjusted = 0
    for item in items:
        counted = item.counted_quantity
        assert counted is not None
        diff = (counted - item.book_quantity).quantize(_QUANTITY_QUANTUM)
        if diff == 0:
            continue
        adjusted += 1
        movement = WarehouseMovement(
            movement_no=_generate_no("ADJ"),
            direction="adjust",
            source_type="stocktake",
            material_id=item.material_id,
            material_code=item.material_code,
            material_name=item.material_name,
            batch_no=item.batch_no,
            quantity=abs(diff),
            unit=material_units.get(item.material_id, ""),
            location_id=item.location_id,
            location_code=item.location_code,
            location_name=item.location_name,
            occurred_at=datetime.now(UTC),
            remark=(
                f"盘点单 {stocktake.stocktake_no}：账面 {item.book_quantity} → 实盘 {counted}"
            ),
            created_by=user.id if user else None,
        )
        db.add(movement)
        await _set_stock_quantity(db, item, counted)

    stocktake.status = "confirmed"
    stocktake.confirmed_at = datetime.now(UTC)
    stocktake.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.stocktake.confirm",
        user=user,
        resource_type="warehouse_stocktake",
        resource_id=stocktake.id,
        new_value={"stocktake_no": stocktake.stocktake_no, "adjusted_lines": adjusted},
    )
    fresh = await repository.get_stocktake(db, stocktake.id)
    assert fresh is not None
    return fresh


async def delete_stocktake(db: AsyncSession, stocktake_id: UUID, user: User) -> None:
    stocktake, items = await _load_stocktake_with_items(db, stocktake_id)
    if stocktake.status != "draft":
        raise AppException(status_code=400, message="已确认的盘点单不能删除")
    stocktake.is_deleted = True
    stocktake.updated_by = user.id if user else None
    for item in items:
        item.is_deleted = True
    await db.flush()
    await record_audit_log(
        db,
        action="warehouse.stocktake.delete",
        user=user,
        resource_type="warehouse_stocktake",
        resource_id=stocktake.id,
        old_value={"stocktake_no": stocktake.stocktake_no},
    )


# ── 列表查询（api 层统一经 service 进入） ──


async def list_materials(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    category: str | None,
    keyword: str | None,
) -> tuple[list[WarehouseMaterial], int]:
    return await repository.list_materials(
        db, page=page, page_size=page_size, category=category, keyword=keyword
    )


async def list_locations(db: AsyncSession) -> list[WarehouseLocation]:
    return await repository.list_locations(db)


async def list_stocks(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    category: str | None,
    keyword: str | None,
    location_id: UUID | None,
) -> tuple[list[WarehouseStock], int]:
    return await repository.list_stocks(
        db,
        page=page,
        page_size=page_size,
        category=category,
        keyword=keyword,
        location_id=location_id,
    )


async def list_movements(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    direction: str | None,
    source_type: str | None,
    keyword: str | None,
    location_id: UUID | None,
    occurred_from: datetime | None,
    occurred_to: datetime | None,
) -> tuple[list[WarehouseMovement], int]:
    return await repository.list_movements(
        db,
        page=page,
        page_size=page_size,
        direction=direction,
        source_type=source_type,
        keyword=keyword,
        location_id=location_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
    )


async def list_stocktakes(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    status: str | None,
) -> tuple[list[WarehouseStocktake], int]:
    return await repository.list_stocktakes(
        db, page=page, page_size=page_size, status=status
    )


async def build_stocktake_response(db: AsyncSession, stocktake_id: UUID) -> dict[str, Any]:
    """组装含明细的盘点单响应字典。"""
    from app.modules.warehouse.schemas import StocktakeItemResponse, StocktakeResponse

    stocktake, items = await _load_stocktake_with_items(db, stocktake_id)
    response = StocktakeResponse.model_validate(stocktake)
    response.items = [StocktakeItemResponse.model_validate(item) for item in items]
    return response.model_dump(mode="json")


# ── 概览 ──


async def get_overview(db: AsyncSession) -> dict[str, Any]:
    now_local = datetime.now(UTC).astimezone()
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    low_stock = await repository.list_low_stock_materials(db)
    today_in = await repository.sum_movements_quantity(
        db, direction="inbound", occurred_from=day_start, occurred_to=day_end
    )
    today_out = await repository.sum_movements_quantity(
        db, direction="outbound", occurred_from=day_start, occurred_to=day_end
    )
    return {
        "material_count": await repository.count_materials(db),
        "location_count": await repository.count_locations(db),
        "stock_sku_count": await repository.count_stock_skus(db),
        "low_stock_materials": [
            f"{name}（库存 {quantity}，低于安全库存 {safety}）"
            for name, quantity, safety in low_stock
        ],
        "today_inbound_quantity": float(today_in),
        "today_outbound_quantity": float(today_out),
    }
