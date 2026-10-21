"""环境监测数据读写：监测点台账与监测记录。只负责查询与持久化，不做业务判断。"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.quality.models import QualityEnvPoint, QualityEnvRecord

# ─── 监测点台账 ───


async def create_env_point(db: AsyncSession, data: dict[str, Any]) -> QualityEnvPoint:
    point = QualityEnvPoint(**data)
    db.add(point)
    await db.flush()
    return point


async def get_env_point(db: AsyncSession, pid: uuid.UUID) -> QualityEnvPoint | None:
    stmt = select(QualityEnvPoint).where(
        QualityEnvPoint.id == pid, QualityEnvPoint.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_env_points(
    db: AsyncSession,
    room: str | None = None,
    monitor_type: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
) -> list[QualityEnvPoint]:
    conds = [QualityEnvPoint.is_deleted == False]  # noqa: E712
    if room:
        conds.append(QualityEnvPoint.room.ilike(f"%{room}%"))
    if monitor_type:
        conds.append(QualityEnvPoint.monitor_type == monitor_type)
    if status:
        conds.append(QualityEnvPoint.status == status)
    if keyword:
        conds.append(QualityEnvPoint.point_no.ilike(f"%{keyword}%"))
    stmt = select(QualityEnvPoint).where(*conds).order_by(QualityEnvPoint.room, QualityEnvPoint.point_no)
    return list((await db.execute(stmt)).scalars().all())


async def update_env_point(db: AsyncSession, pid: uuid.UUID, data: dict[str, Any]) -> QualityEnvPoint | None:
    point = await get_env_point(db, pid)
    if point is None:
        return None
    for key, value in data.items():
        setattr(point, key, value)
    await db.flush()
    stmt = select(QualityEnvPoint).where(QualityEnvPoint.id == pid)
    return (await db.execute(stmt)).scalar_one_or_none()


async def delete_env_point(db: AsyncSession, pid: uuid.UUID) -> bool:
    point = await get_env_point(db, pid)
    if point is None:
        return False
    point.is_deleted = True
    await db.flush()
    return True


# ─── 监测记录 ───


async def create_env_record(db: AsyncSession, data: dict[str, Any]) -> QualityEnvRecord:
    rec = QualityEnvRecord(**data)
    db.add(rec)
    await db.flush()
    return rec


async def get_env_record(db: AsyncSession, rid: uuid.UUID) -> QualityEnvRecord | None:
    stmt = select(QualityEnvRecord).where(
        QualityEnvRecord.id == rid, QualityEnvRecord.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_env_records(
    db: AsyncSession,
    point_id: uuid.UUID | None = None,
    judge: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    """监测记录列表（联查点位信息与填报人姓名）。"""
    from app.platform.identity.models import User as IdentityUser

    user_alias = aliased(IdentityUser)
    stmt = (
        select(QualityEnvRecord, QualityEnvPoint, user_alias.name)
        .join(QualityEnvPoint, QualityEnvPoint.id == QualityEnvRecord.point_id)
        .join(user_alias, user_alias.id == QualityEnvRecord.recorded_by, isouter=True)
        .where(
            QualityEnvRecord.is_deleted == False,  # noqa: E712
            QualityEnvPoint.is_deleted == False,  # noqa: E712
        )
    )
    if point_id:
        stmt = stmt.where(QualityEnvRecord.point_id == point_id)
    if judge:
        stmt = stmt.where(QualityEnvRecord.judge == judge)
    if date_from:
        stmt = stmt.where(QualityEnvRecord.record_date >= date_from)
    if date_to:
        stmt = stmt.where(QualityEnvRecord.record_date <= date_to)
    stmt = stmt.order_by(QualityEnvRecord.record_date.desc(), QualityEnvRecord.created_at.desc())
    out: list[dict[str, Any]] = []
    for r, p, by_name in (await db.execute(stmt)).all():
        out.append({
            "id": r.id,
            "point_id": r.point_id,
            "room": p.room,
            "point_no": p.point_no,
            "monitor_type": p.monitor_type,
            "record_date": r.record_date,
            "result_value": r.result_value,
            "alert_limit": r.alert_limit,
            "action_limit": r.action_limit,
            "judge": r.judge,
            "recorded_by": r.recorded_by,
            "recorded_by_name": by_name,
            "remark": r.remark,
            "created_at": r.created_at,
        })
    return out


async def delete_env_record(db: AsyncSession, rid: uuid.UUID) -> bool:
    rec = await get_env_record(db, rid)
    if rec is None:
        return False
    rec.is_deleted = True
    await db.flush()
    return True
