"""物料容器数据读写。只负责查询与持久化，不做业务判断。"""

import uuid
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quality.models import (
    QualityContainerMovement,
    QualityMaterial,
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
