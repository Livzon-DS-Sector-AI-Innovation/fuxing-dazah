"""物料容器数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.quality.models import (
    QualityContainerMovement,
    QualityInspectionPlan,
    QualityLabItem,
    QualityMaterial,
    QualityMaterialContainer,
    QualityMaterialRequest,
    QualityMaterialStandard,
    QualityMaterialStandardItem,
    QualityStocktakeItem,
    QualityStocktakeSheet,
    QualitySupplier,
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


# ─── 物料字典 ───


async def create_material(db: AsyncSession, data: dict[str, Any]) -> QualityMaterial:
    material = QualityMaterial(**data)
    db.add(material)
    await db.flush()
    return material


async def get_material_by_code(db: AsyncSession, code: str) -> QualityMaterial | None:
    stmt = (
        select(QualityMaterial)
        .where(QualityMaterial.code == code, QualityMaterial.is_deleted == False)  # noqa: E712
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_material(db: AsyncSession, mid: uuid.UUID) -> QualityMaterial | None:
    stmt = select(QualityMaterial).where(
        QualityMaterial.id == mid, QualityMaterial.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_materials(
    db: AsyncSession, q: str | None = None, page: int = 1, page_size: int = 50
) -> tuple[list[QualityMaterial], int]:
    conds = [QualityMaterial.is_deleted == False]  # noqa: E712
    if q:
        like = f"%{q}%"
        conds.append(
            (QualityMaterial.code.ilike(like)) | (QualityMaterial.name.ilike(like))
        )
    total = await db.scalar(select(func.count()).select_from(QualityMaterial).where(*conds))
    stmt = (
        select(QualityMaterial)
        .where(*conds)
        .order_by(QualityMaterial.code)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, int(total or 0)


async def update_material(
    db: AsyncSession, mid: uuid.UUID, data: dict[str, Any]
) -> QualityMaterial | None:
    material = await get_material(db, mid)
    if material is None:
        return None
    for key, value in data.items():
        setattr(material, key, value)
    await db.flush()
    stmt = select(QualityMaterial).where(QualityMaterial.id == mid)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_material(db: AsyncSession, mid: uuid.UUID) -> bool:
    material = await get_material(db, mid)
    if material is None:
        return False
    material.is_deleted = True
    await db.flush()
    return True


# ─── 台账流水（联容器取物料信息） ───


async def list_material_movements(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 50,
    material_q: str | None = None,
    op_type: str | None = None,
) -> tuple[list[Any], int]:
    conds = [
        QualityContainerMovement.is_deleted == False,  # noqa: E712
    ]
    if material_q:
        like = f"%{material_q}%"
        conds.append(
            (QualityMaterialContainer.material_code.ilike(like))
            | (QualityMaterialContainer.material_name.ilike(like))
        )
    if op_type:
        conds.append(QualityContainerMovement.op_type == op_type)
    base = (
        select(QualityContainerMovement, QualityMaterialContainer.material_code, QualityMaterialContainer.material_name)
        .join(
            QualityMaterialContainer,
            QualityMaterialContainer.id == QualityContainerMovement.container_id,
        )
        .where(*conds)
    )
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = list(
        (await db.execute(base.order_by(QualityContainerMovement.op_at.desc())
            .offset((page - 1) * page_size).limit(page_size)))
        .all()
    )
    return rows, int(total or 0)


async def material_stock_summary(db: AsyncSession) -> list[dict[str, Any]]:
    """按物料聚合容器状态与临效期/过期统计。"""
    from app.core.time import today as _today

    today_str = _today().isoformat()
    rows = await db.execute(
        select(
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
            func.count().label("total"),
            func.count().filter(QualityMaterialContainer.status == "labeled").label("labeled"),
            func.count().filter(QualityMaterialContainer.status == "in_warehouse").label("in_warehouse"),
            func.count().filter(QualityMaterialContainer.status == "qualified").label("qualified"),
            func.count().filter(QualityMaterialContainer.status == "issued").label("issued"),
            func.count().filter(QualityMaterialContainer.status == "returned").label("returned"),
            func.count().filter(
                QualityMaterialContainer.expiry_date < today_str
            ).label("expired"),
            func.count().filter(
                QualityMaterialContainer.expiry_date >= today_str,
                QualityMaterialContainer.expiry_date
                <= func.to_char(
                    func.now() + text("interval '90 days'"), "YYYY-MM-DD"
                ),
            ).label("near_expiry"),
        )
        .where(QualityMaterialContainer.is_deleted == False)  # noqa: E712
        .group_by(
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
        )
        .order_by(QualityMaterialContainer.material_name)
    )
    result = []
    for r in rows:
        available = int(r.in_warehouse or 0) + int(r.qualified or 0)
        result.append({
            "material_code": r.material_code,
            "material_name": r.material_name,
            "labeled": int(r.labeled or 0),
            "in_warehouse": int(r.in_warehouse or 0),
            "qualified": int(r.qualified or 0),
            "issued": int(r.issued or 0),
            "returned": int(r.returned or 0),
            "total": int(r.total or 0),
            "available": available,
            "near_expiry": int(r.near_expiry or 0),
            "expired": int(r.expired or 0),
        })
    # 附带字典阈值
    dicts = await list_materials(db, page_size=500)
    by_code = {d.code: d for d in dicts[0]}
    for item in result:
        material = by_code.get(item["material_code"])
        min_stock = material.min_stock if material else None
        item["min_stock"] = min_stock
        item["below_stock"] = min_stock is not None and item["available"] < min_stock
    return result


# ─── 效期预警与采购建议 ───


async def material_expiry_alerts(db: AsyncSession) -> list[dict[str, Any]]:
    """临效期(≤90天)与已过期容器按物料聚合（在库相关状态才提醒，已领出不计）。

    返回 [{material_code, material_name, near, expired, earliest}]。
    """
    from app.core.time import today as _today

    today_str = _today().isoformat()
    deadline = func.to_char(func.now() + text("interval '90 days'"), "YYYY-MM-DD")
    rows = await db.execute(
        select(
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
            func.count().filter(QualityMaterialContainer.expiry_date < today_str).label("expired"),
            func.count().filter(
                QualityMaterialContainer.expiry_date >= today_str,
                QualityMaterialContainer.expiry_date <= deadline,
            ).label("near"),
            func.min(QualityMaterialContainer.expiry_date).label("earliest"),
        )
        .where(
            QualityMaterialContainer.is_deleted == False,  # noqa: E712
            QualityMaterialContainer.status.in_(["labeled", "in_warehouse", "qualified"]),
            QualityMaterialContainer.expiry_date.is_not(None),
            QualityMaterialContainer.expiry_date <= deadline,
        )
        .group_by(
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
        )
        .order_by(QualityMaterialContainer.material_name)
    )
    return [
        {
            "material_code": r.material_code,
            "material_name": r.material_name,
            "near": int(r.near or 0),
            "expired": int(r.expired or 0),
            "earliest": r.earliest,
        }
        for r in rows
    ]


async def material_today_stats(db: AsyncSession) -> dict[str, int]:
    """今日出入库笔数（北京时间口径，含 status 流转之外的 in/out 操作）。"""
    from app.core.time import today as _today

    today_str = _today().isoformat()
    rows = await db.execute(
        select(
            QualityContainerMovement.op_type,
            func.count(),
        )
        .where(
            QualityContainerMovement.is_deleted == False,  # noqa: E712
            QualityContainerMovement.op_type.in_(["in", "out"]),
            func.to_char(
                func.timezone("Asia/Shanghai", QualityContainerMovement.op_at),
                "YYYY-MM-DD",
            ) == today_str,
        )
        .group_by(QualityContainerMovement.op_type)
    )
    stats = {"today_in": 0, "today_out": 0}
    for op_type, count in rows:
        if op_type == "in":
            stats["today_in"] = int(count)
        elif op_type == "out":
            stats["today_out"] = int(count)
    return stats


async def material_consumption_trend(
    db: AsyncSession, material_code: str, months: int = 6
) -> list[dict[str, Any]]:
    """物料近 N 个月出入库笔数（北京时区按月聚合），供领用趋势与阈值建议。"""
    rows = await db.execute(
        select(
            func.to_char(func.timezone("Asia/Shanghai", QualityContainerMovement.op_at), "YYYY-MM").label("month"),
            func.count().filter(QualityContainerMovement.op_type == "in").label("in_count"),
            func.count().filter(QualityContainerMovement.op_type == "out").label("out_count"),
        )
        .join(
            QualityMaterialContainer,
            QualityMaterialContainer.id == QualityContainerMovement.container_id,
        )
        .where(
            QualityContainerMovement.is_deleted == False,  # noqa: E712
            QualityContainerMovement.op_type.in_(["in", "out"]),
            QualityMaterialContainer.material_code == material_code,
        )
        .group_by("month")
        .order_by("month")
    )
    counts = {r.month: {"in": int(r.in_count or 0), "out": int(r.out_count or 0)} for r in rows}
    # 补齐近 N 个月（含空月），纯算术避免额外依赖
    from app.core.time import today as _today

    now = _today().replace(day=1)
    result = []
    for i in range(months - 1, -1, -1):
        total = now.year * 12 + (now.month - 1) - i
        year, month_idx = divmod(total, 12)
        month = f"{year}-{month_idx + 1:02d}"
        entry = counts.get(month, {"in": 0, "out": 0})
        result.append({"month": month, "in": entry["in"], "out": entry["out"]})
    return result


# ─── 供应商主数据 ───


async def create_supplier(db: AsyncSession, data: dict[str, Any]) -> QualitySupplier:
    supplier = QualitySupplier(**data)
    db.add(supplier)
    await db.flush()
    return supplier


async def get_supplier_by_code(db: AsyncSession, code: str) -> QualitySupplier | None:
    stmt = (
        select(QualitySupplier)
        .where(QualitySupplier.code == code, QualitySupplier.is_deleted == False)  # noqa: E712
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_supplier(db: AsyncSession, sid: uuid.UUID) -> QualitySupplier | None:
    stmt = select(QualitySupplier).where(
        QualitySupplier.id == sid, QualitySupplier.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_suppliers(
    db: AsyncSession, q: str | None = None
) -> list[QualitySupplier]:
    conds = [QualitySupplier.is_deleted == False]  # noqa: E712
    if q:
        like = f"%{q}%"
        conds.append((QualitySupplier.code.ilike(like)) | (QualitySupplier.name.ilike(like)))
    stmt = select(QualitySupplier).where(*conds).order_by(QualitySupplier.code)
    return list((await db.execute(stmt)).scalars().all())


async def update_supplier(
    db: AsyncSession, sid: uuid.UUID, data: dict[str, Any]
) -> QualitySupplier | None:
    supplier = await get_supplier(db, sid)
    if supplier is None:
        return None
    for key, value in data.items():
        setattr(supplier, key, value)
    await db.flush()
    stmt = select(QualitySupplier).where(QualitySupplier.id == sid)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_supplier(db: AsyncSession, sid: uuid.UUID) -> bool:
    supplier = await get_supplier(db, sid)
    if supplier is None:
        return False
    supplier.is_deleted = True
    await db.flush()
    return True


async def supplier_qual_alerts(db: AsyncSession) -> list[dict[str, Any]]:
    """供应商资质临期（≤90天）/已过期提醒。"""
    from app.core.time import today as _today

    today_str = _today().isoformat()
    deadline = func.to_char(func.now() + text("interval '90 days'"), "YYYY-MM-DD")
    rows = await db.execute(
        select(
            QualitySupplier.code,
            QualitySupplier.name,
            QualitySupplier.qual_expiry_date,
        )
        .where(
            QualitySupplier.is_deleted == False,  # noqa: E712
            QualitySupplier.qual_expiry_date.is_not(None),
            QualitySupplier.qual_expiry_date <= deadline,
        )
        .order_by(QualitySupplier.qual_expiry_date)
    )
    return [
        {
            "code": r.code,
            "name": r.name,
            "qual_expiry_date": r.qual_expiry_date,
            "expired": bool(r.qual_expiry_date and r.qual_expiry_date < today_str),
        }
        for r in rows
    ]


# ─── 盘点与月度报表 ───


async def create_stocktake_sheet(db: AsyncSession, data: dict[str, Any]) -> QualityStocktakeSheet:
    sheet = QualityStocktakeSheet(**data)
    db.add(sheet)
    await db.flush()
    return sheet


async def get_stocktake_sheet(db: AsyncSession, sid: uuid.UUID) -> QualityStocktakeSheet | None:
    stmt = select(QualityStocktakeSheet).where(
        QualityStocktakeSheet.id == sid, QualityStocktakeSheet.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_stocktake_sheets(
    db: AsyncSession, status: str | None = None
) -> list[QualityStocktakeSheet]:
    conds = [QualityStocktakeSheet.is_deleted == False]  # noqa: E712
    if status:
        conds.append(QualityStocktakeSheet.status == status)
    stmt = select(QualityStocktakeSheet).where(*conds).order_by(QualityStocktakeSheet.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


async def max_stocktake_seq(db: AsyncSession, prefix: str) -> int:
    val = await db.scalar(
        select(func.max(QualityStocktakeSheet.sheet_no)).where(
            QualityStocktakeSheet.sheet_no.like(f"{prefix}%"),
            QualityStocktakeSheet.is_deleted == False,  # noqa: E712
        )
    )
    text_val = str(val or "")
    try:
        return int(text_val.rsplit("-", 1)[-1])
    except ValueError:
        return 0


async def create_stocktake_item(db: AsyncSession, data: dict[str, Any]) -> QualityStocktakeItem:
    item = QualityStocktakeItem(**data)
    db.add(item)
    await db.flush()
    return item


async def get_stocktake_item(db: AsyncSession, sheet_id: uuid.UUID, container_no: str) -> QualityStocktakeItem | None:
    stmt = (
        select(QualityStocktakeItem)
        .where(
            QualityStocktakeItem.sheet_id == sheet_id,
            QualityStocktakeItem.container_no == container_no,
            QualityStocktakeItem.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_stocktake_items(db: AsyncSession, sheet_id: uuid.UUID) -> list[QualityStocktakeItem]:
    stmt = (
        select(QualityStocktakeItem)
        .where(QualityStocktakeItem.sheet_id == sheet_id, QualityStocktakeItem.is_deleted == False)  # noqa: E712
        .order_by(QualityStocktakeItem.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def list_in_stock_containers(
    db: AsyncSession, material_code: str | None = None
) -> list[QualityMaterialContainer]:
    """盘点口径的在库容器：in_warehouse + qualified。"""
    conds = [
        QualityMaterialContainer.is_deleted == False,  # noqa: E712
        QualityMaterialContainer.status.in_(["in_warehouse", "qualified"]),
    ]
    if material_code:
        conds.append(QualityMaterialContainer.material_code == material_code)
    stmt = select(QualityMaterialContainer).where(*conds).order_by(QualityMaterialContainer.container_no)
    return list((await db.execute(stmt)).scalars().all())


async def material_monthly_report(db: AsyncSession, month: str) -> list[dict[str, Any]]:
    """指定月（YYYY-MM）按物料的出入库/退库/状态流转笔数 + 当前可用。"""
    rows = await db.execute(
        select(
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
            func.count().filter(QualityContainerMovement.op_type == "in").label("in_count"),
            func.count().filter(QualityContainerMovement.op_type == "out").label("out_count"),
            func.count().filter(QualityContainerMovement.op_type == "return").label("return_count"),
            func.count().filter(QualityContainerMovement.op_type == "status").label("status_count"),
        )
        .join(
            QualityContainerMovement,
            QualityContainerMovement.container_id == QualityMaterialContainer.id,
        )
        .where(
            QualityContainerMovement.is_deleted == False,  # noqa: E712
            func.to_char(func.timezone("Asia/Shanghai", QualityContainerMovement.op_at), "YYYY-MM") == month,
        )
        .group_by(
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
        )
        .order_by(QualityMaterialContainer.material_name)
    )
    # 当前可用（在库+合格）
    stock = await material_stock_summary(db)
    available_map = {s["material_code"]: s["available"] for s in stock}
    return [
        {
            "material_code": r.material_code,
            "material_name": r.material_name,
            "in_count": int(r.in_count or 0),
            "out_count": int(r.out_count or 0),
            "return_count": int(r.return_count or 0),
            "status_count": int(r.status_count or 0),
            "available": available_map.get(r.material_code, 0),
        }
        for r in rows
    ]


async def update_container_location(
    db: AsyncSession, container_id: uuid.UUID, location: str
) -> QualityMaterialContainer | None:
    container = await get_material_container(db, container_id)
    if container is None:
        return None
    container.location = location
    await db.flush()
    stmt = select(QualityMaterialContainer).where(QualityMaterialContainer.id == container_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_slow_moving_containers(
    db: AsyncSession, min_age_days: int = 30
) -> list[dict[str, Any]]:
    """呆滞库存：在库（待验/合格）且入库已超过 N 天的容器（账龄=今天-入库日期）。"""
    from datetime import timedelta as _td

    from app.core.time import today as _today

    today = _today()
    cutoff = (today - _td(days=min_age_days)).isoformat()
    rows = await db.execute(
        select(
            QualityMaterialContainer.container_no,
            QualityMaterialContainer.material_code,
            QualityMaterialContainer.material_name,
            QualityMaterialContainer.inbound_batch_no,
            QualityMaterialContainer.inbound_date,
            QualityMaterialContainer.created_at,
            QualityMaterialContainer.location,
        )
        .where(
            QualityMaterialContainer.is_deleted == False,  # noqa: E712
            QualityMaterialContainer.status.in_(["in_warehouse", "qualified"]),
            QualityMaterialContainer.inbound_date.is_not(None),
            QualityMaterialContainer.inbound_date <= cutoff,
        )
        .order_by(QualityMaterialContainer.inbound_date)
    )
    result = []
    for r in rows:
        age = (today - date.fromisoformat(r.inbound_date)).days
        result.append({
            "container_no": r.container_no,
            "material_code": r.material_code,
            "material_name": r.material_name,
            "inbound_batch_no": r.inbound_batch_no,
            "inbound_date": r.inbound_date,
            "location": r.location,
            "age_days": age,
        })
    return result


# ─── 物料请验 / 物料标准 ───


async def create_material_request(db: AsyncSession, data: dict[str, Any]) -> QualityMaterialRequest:
    req = QualityMaterialRequest(**data)
    db.add(req)
    await db.flush()
    return req


async def get_material_request(db: AsyncSession, rid: uuid.UUID) -> QualityMaterialRequest | None:
    stmt = select(QualityMaterialRequest).where(
        QualityMaterialRequest.id == rid, QualityMaterialRequest.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_material_requests(
    db: AsyncSession, status: str | None = None, batch_no: str | None = None
) -> list[QualityMaterialRequest]:
    conds = [QualityMaterialRequest.is_deleted == False]  # noqa: E712
    if status:
        conds.append(QualityMaterialRequest.status == status)
    if batch_no:
        conds.append(QualityMaterialRequest.inbound_batch_no.like(f"%{batch_no}%"))
    stmt = select(QualityMaterialRequest).where(*conds).order_by(QualityMaterialRequest.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


async def max_material_request_seq(db: AsyncSession, prefix: str) -> int:
    val = await db.scalar(
        select(func.max(QualityMaterialRequest.request_no)).where(
            QualityMaterialRequest.request_no.like(f"{prefix}%"),
            QualityMaterialRequest.is_deleted == False,  # noqa: E712
        )
    )
    try:
        return int(str(val or "").rsplit("-", 1)[-1])
    except ValueError:
        return 0


async def create_material_standard(db: AsyncSession, data: dict[str, Any]) -> QualityMaterialStandard:
    std = QualityMaterialStandard(**data)
    db.add(std)
    await db.flush()
    return std


async def get_material_standard(db: AsyncSession, sid: uuid.UUID) -> QualityMaterialStandard | None:
    stmt = select(QualityMaterialStandard).where(
        QualityMaterialStandard.id == sid, QualityMaterialStandard.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_material_standard_by_key(
    db: AsyncSession, material_code: str, vendor_code: str | None
) -> QualityMaterialStandard | None:
    stmt = (
        select(QualityMaterialStandard)
        .where(
            QualityMaterialStandard.material_code == material_code,
            QualityMaterialStandard.vendor_code == vendor_code,
            QualityMaterialStandard.is_deleted == False,  # noqa: E712
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_material_standard_items(
    db: AsyncSession, standard_id: uuid.UUID
) -> list[QualityMaterialStandardItem]:
    stmt = (
        select(QualityMaterialStandardItem)
        .where(
            QualityMaterialStandardItem.standard_id == standard_id,
            QualityMaterialStandardItem.is_deleted == False,  # noqa: E712
        )
        .order_by(QualityMaterialStandardItem.seq, QualityMaterialStandardItem.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_material_standard_item(
    db: AsyncSession, data: dict[str, Any]
) -> QualityMaterialStandardItem:
    item = QualityMaterialStandardItem(**data)
    db.add(item)
    await db.flush()
    return item


async def list_containers_by_request(
    db: AsyncSession, request_id: uuid.UUID
) -> list[QualityMaterialContainer]:
    stmt = select(QualityMaterialContainer).where(
        QualityMaterialContainer.material_request_id == request_id,
        QualityMaterialContainer.is_deleted == False,  # noqa: E712
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_material_request(
    db: AsyncSession, rid: uuid.UUID, data: dict[str, Any]
) -> QualityMaterialRequest:
    """更新请验单字段后 re-fetch（UPDATE 后必须 select，见编码规范）。"""
    req = await get_material_request(db, rid)
    if req is None:
        raise AppException(status_code=404, detail="请验单不存在")
    for key, value in data.items():
        setattr(req, key, value)
    await db.flush()
    stmt = select(QualityMaterialRequest).where(QualityMaterialRequest.id == rid)
    return (await db.execute(stmt)).scalar_one()


# ─── 试剂/仪器台账与请检计划 ───


async def create_lab_item(db: AsyncSession, data: dict[str, Any]) -> QualityLabItem:
    item = QualityLabItem(**data)
    db.add(item)
    await db.flush()
    return item


async def get_lab_item(db: AsyncSession, iid: uuid.UUID) -> QualityLabItem | None:
    stmt = select(QualityLabItem).where(
        QualityLabItem.id == iid, QualityLabItem.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_lab_items(
    db: AsyncSession, item_type: str | None = None, q: str | None = None
) -> list[QualityLabItem]:
    conds = [QualityLabItem.is_deleted == False]  # noqa: E712
    if item_type:
        conds.append(QualityLabItem.item_type == item_type)
    if q:
        conds.append(QualityLabItem.name.ilike(f"%{q}%"))
    stmt = select(QualityLabItem).where(*conds).order_by(QualityLabItem.expiry_date.asc().nulls_last())
    return list((await db.execute(stmt)).scalars().all())


async def update_lab_item(db: AsyncSession, iid: uuid.UUID, data: dict[str, Any]) -> QualityLabItem | None:
    item = await get_lab_item(db, iid)
    if item is None:
        return None
    for key, value in data.items():
        setattr(item, key, value)
    await db.flush()
    stmt = select(QualityLabItem).where(QualityLabItem.id == iid)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_lab_item(db: AsyncSession, iid: uuid.UUID) -> bool:
    item = await get_lab_item(db, iid)
    if item is None:
        return False
    item.is_deleted = True
    await db.flush()
    return True


async def lab_expiry_alerts(db: AsyncSession) -> list[dict[str, Any]]:
    """试剂/仪器临期（≤30天）与已过期清单（推送提醒用）。"""
    from app.core.time import today as _today

    today_str = _today().isoformat()
    deadline = func.to_char(func.now() + text("interval '30 days'"), "YYYY-MM-DD")
    rows = await db.execute(
        select(QualityLabItem).where(
            QualityLabItem.is_deleted == False,  # noqa: E712
            QualityLabItem.expiry_date.is_not(None),
            QualityLabItem.expiry_date <= deadline,
        ).order_by(QualityLabItem.expiry_date)
    )
    return [
        {
            "name": r.name,
            "item_type": r.item_type,
            "expiry_date": r.expiry_date,
            "expired": bool(r.expiry_date and r.expiry_date < today_str),
        }
        for r in rows
    ]


async def create_inspection_plan(db: AsyncSession, data: dict[str, Any]) -> QualityInspectionPlan:
    plan = QualityInspectionPlan(**data)
    db.add(plan)
    await db.flush()
    return plan


async def list_inspection_plans(
    db: AsyncSession, date_str: str | None = None, department: str | None = None
) -> list[QualityInspectionPlan]:
    conds = [QualityInspectionPlan.is_deleted == False]  # noqa: E712
    if date_str:
        conds.append(QualityInspectionPlan.plan_time.like(f"{date_str}%"))
    if department:
        conds.append(QualityInspectionPlan.department.ilike(f"%{department}%"))
    stmt = select(QualityInspectionPlan).where(*conds).order_by(QualityInspectionPlan.plan_time)
    return list((await db.execute(stmt)).scalars().all())


async def get_inspection_plan(db: AsyncSession, pid: uuid.UUID) -> QualityInspectionPlan | None:
    stmt = select(QualityInspectionPlan).where(
        QualityInspectionPlan.id == pid, QualityInspectionPlan.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_inspection_plan_status(
    db: AsyncSession, pid: uuid.UUID, status: str
) -> QualityInspectionPlan | None:
    plan = await get_inspection_plan(db, pid)
    if plan is None:
        return None
    plan.status = status
    await db.flush()
    stmt = select(QualityInspectionPlan).where(QualityInspectionPlan.id == pid)
    return (await db.execute(stmt)).scalar_one_or_none()
