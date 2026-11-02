"""环境监测数据读写：监测点台账与监测记录。只负责查询与持久化，不做业务判断。"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.modules.quality.models import (
    QualityBatchRelease,
    QualityEnvPoint,
    QualityEnvRecord,
    QualityShiftConfig,
    QualityShiftTeam,
)

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
    handle_status: str | None = None,
) -> list[dict[str, Any]]:
    """监测记录列表（联查点位信息、填报人/处理人姓名）。"""
    from app.platform.identity.models import User as IdentityUser

    recorder = aliased(IdentityUser)
    handler = aliased(IdentityUser)
    stmt = (
        select(QualityEnvRecord, QualityEnvPoint, recorder.name, handler.name)
        .join(QualityEnvPoint, QualityEnvPoint.id == QualityEnvRecord.point_id)
        .join(recorder, recorder.id == QualityEnvRecord.recorded_by, isouter=True)
        .join(handler, handler.id == QualityEnvRecord.handled_by, isouter=True)
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
    if handle_status:
        stmt = stmt.where(QualityEnvRecord.handle_status == handle_status)
    stmt = stmt.order_by(QualityEnvRecord.record_date.desc(), QualityEnvRecord.created_at.desc())
    out: list[dict[str, Any]] = []
    for r, p, by_name, handled_name in (await db.execute(stmt)).all():
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
            "handle_status": r.handle_status,
            "handled_at": r.handled_at,
            "handled_by": r.handled_by,
            "handled_by_name": handled_name,
            "handled_remark": r.handled_remark,
            "recorded_by": r.recorded_by,
            "recorded_by_name": by_name,
            "remark": r.remark,
            "created_at": r.created_at,
        })
    return out


async def handle_env_record(db: AsyncSession, rid: uuid.UUID, data: dict[str, Any]) -> QualityEnvRecord | None:
    """超行动限记录闭环：标记已处理（处理人/日期/说明）。"""
    rec = await get_env_record(db, rid)
    if rec is None:
        return None
    for key, value in data.items():
        setattr(rec, key, value)
    await db.flush()
    stmt = select(QualityEnvRecord).where(QualityEnvRecord.id == rid)
    return (await db.execute(stmt)).scalar_one_or_none()


async def env_missed_points(db: AsyncSession) -> list[dict[str, Any]]:
    """应测未测点名：weekly 点位本周无记录 / monthly 点位本月无记录（per_batch 不参与自动点名）。"""
    from datetime import timedelta

    from app.core.time import today as _today

    t = _today()
    week_start = (t - timedelta(days=t.weekday())).isoformat()
    month_start = t.replace(day=1).isoformat()
    points = (await db.execute(
        select(QualityEnvPoint).where(
            QualityEnvPoint.is_deleted == False,  # noqa: E712
            QualityEnvPoint.status == "active",
            QualityEnvPoint.frequency.in_(["weekly", "monthly"]),
        ).order_by(QualityEnvPoint.room, QualityEnvPoint.point_no)
    )).scalars()
    out: list[dict[str, Any]] = []
    for p in points:
        threshold = week_start if p.frequency == "weekly" else month_start
        last = (await db.execute(
            select(func.max(QualityEnvRecord.record_date)).where(
                QualityEnvRecord.point_id == p.id,
                QualityEnvRecord.is_deleted == False,  # noqa: E712
            )
        )).scalar_one_or_none()
        if last is None or last < threshold:
            out.append({
                "room": p.room,
                "point_no": p.point_no,
                "monitor_type": p.monitor_type,
                "frequency": p.frequency,
                "last_date": last,
            })
    return out


async def delete_env_record(db: AsyncSession, rid: uuid.UUID) -> bool:
    rec = await get_env_record(db, rid)
    if rec is None:
        return False
    rec.is_deleted = True
    await db.flush()
    return True


async def env_trend(db: AsyncSession, point_id: uuid.UUID, days: int = 90) -> dict[str, Any] | None:
    """点位监测趋势：近 N 天记录时间序列 + 点位当前警戒/行动限（画控制线用）。"""
    from datetime import timedelta

    from app.core.time import today as _today

    point = await get_env_point(db, point_id)
    if point is None:
        return None
    date_from = (_today() - timedelta(days=days)).isoformat()
    rows = (await db.execute(
        select(QualityEnvRecord).where(
            QualityEnvRecord.point_id == point_id,
            QualityEnvRecord.is_deleted == False,  # noqa: E712
            QualityEnvRecord.record_date >= date_from,
        ).order_by(QualityEnvRecord.record_date)
    )).scalars()
    items = [
        {"record_date": r.record_date, "result_value": r.result_value, "judge": r.judge}
        for r in rows
    ]
    return {
        "room": point.room,
        "point_no": point.point_no,
        "monitor_type": point.monitor_type,
        "alert_limit": point.alert_limit,
        "action_limit": point.action_limit,
        "items": items,
    }


# ─── 批放行记录 ───


async def create_batch_release(db: AsyncSession, data: dict[str, Any]) -> QualityBatchRelease:
    rec = QualityBatchRelease(**data)
    db.add(rec)
    await db.flush()
    return rec


async def get_batch_release(db: AsyncSession, rid: uuid.UUID) -> QualityBatchRelease | None:
    stmt = select(QualityBatchRelease).where(
        QualityBatchRelease.id == rid, QualityBatchRelease.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_batch_releases(
    db: AsyncSession, batch_no: str | None = None, status: str | None = None
) -> list[QualityBatchRelease]:
    conds = [QualityBatchRelease.is_deleted == False]  # noqa: E712
    if batch_no:
        conds.append(QualityBatchRelease.batch_no.ilike(f"%{batch_no}%"))
    if status:
        conds.append(QualityBatchRelease.status == status)
    stmt = select(QualityBatchRelease).where(*conds).order_by(QualityBatchRelease.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())


async def get_batch_release_by_batch(db: AsyncSession, batch_no: str) -> QualityBatchRelease | None:
    stmt = select(QualityBatchRelease).where(
        QualityBatchRelease.batch_no == batch_no, QualityBatchRelease.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_batch_release(db: AsyncSession, rid: uuid.UUID, data: dict[str, Any]) -> QualityBatchRelease | None:
    rec = await get_batch_release(db, rid)
    if rec is None:
        return None
    for key, value in data.items():
        setattr(rec, key, value)
    await db.flush()
    stmt = select(QualityBatchRelease).where(QualityBatchRelease.id == rid)
    return (await db.execute(stmt)).scalar_one_or_none()


# ─── 排班班组与轮换 ───


async def list_shift_teams(db: AsyncSession, group_key: str | None = None) -> list[QualityShiftTeam]:
    conds = [QualityShiftTeam.is_deleted == False]  # noqa: E712
    if group_key:
        conds.append(QualityShiftTeam.group_key == group_key)
    stmt = select(QualityShiftTeam).where(*conds).order_by(QualityShiftTeam.seq, QualityShiftTeam.created_at)
    return list((await db.execute(stmt)).scalars().all())


async def get_shift_team(db: AsyncSession, tid: uuid.UUID) -> QualityShiftTeam | None:
    stmt = select(QualityShiftTeam).where(
        QualityShiftTeam.id == tid, QualityShiftTeam.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def item_group(item_name: str, mapping: dict[str, list[str]] | None) -> str:
    """项目名 → 组别（关键词匹配）：仪器组/生物组/理化组，未匹配回退理化组。"""
    mapping = mapping or {}
    for group, keywords in mapping.items():
        for kw in keywords:
            if kw and kw in item_name:
                return group
    return "理化组"


async def group_duty(
    db: AsyncSession, group_key: str, on_date: str
) -> dict[str, Any]:
    """某组别当日当班：该组班组按该组轮换配置计算（无配置回退全局 rotation）。"""
    cfg = await get_shift_config(db, "rotation")
    value = (cfg.value or {}) if cfg else {}
    start_date = value.get("start_date")
    period_days = int(value.get("period_days") or 3)
    duty_count = int(value.get("duty_teams") or 2)
    team_order = value.get("team_order") or []
    teams = await list_shift_teams(db, group_key=group_key)
    team_dicts = [{"id": str(t.id), "name": t.name, "member_ids": t.member_ids or []} for t in teams]
    duty = (
        shift_duty_teams(team_dicts, start_date, period_days, duty_count, on_date, team_order)
        if start_date else team_dicts[:duty_count]
    )
    member_ids: list[str] = []
    for t in duty:
        member_ids.extend(t["member_ids"])
    return {
        "group": group_key,
        "configured": bool(start_date),
        "teams": [{"id": t["id"], "name": t["name"]} for t in duty],
        "members": member_ids,
    }


async def group_member_ids(db: AsyncSession, group_key: str) -> set[str]:
    """组别全部成员（该组所有班组并集），用于分配权限校验。"""
    out: set[str] = set()
    for t in await list_shift_teams(db, group_key=group_key):
        out.update(t.member_ids or [])
    return out


async def user_shift_groups(db: AsyncSession, user_id: uuid.UUID) -> set[str]:
    """用户所属组别：出现在哪些组别的班组成员名单中（未编入任何班组则返回空集=不限组）。"""
    out: set[str] = set()
    uid = str(user_id)
    for t in await list_shift_teams(db):
        if uid in (t.member_ids or []):
            out.add(t.group_key)
    return out


async def upsert_shift_team(db: AsyncSession, tid: uuid.UUID | None, data: dict[str, Any]) -> QualityShiftTeam:
    if tid is not None:
        team = await get_shift_team(db, tid)
        if team is None:
            raise ValueError("班组不存在")
        for key, value in data.items():
            setattr(team, key, value)
    else:
        team = QualityShiftTeam(**data)
        db.add(team)
    await db.flush()
    return team


async def delete_shift_team(db: AsyncSession, tid: uuid.UUID) -> bool:
    team = await get_shift_team(db, tid)
    if team is None:
        return False
    team.is_deleted = True
    await db.flush()
    return True


async def get_shift_config(db: AsyncSession, key: str) -> QualityShiftConfig | None:
    stmt = select(QualityShiftConfig).where(
        QualityShiftConfig.key == key, QualityShiftConfig.is_deleted == False  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def upsert_shift_config(db: AsyncSession, key: str, value: dict[str, Any]) -> QualityShiftConfig:
    cfg = await get_shift_config(db, key)
    if cfg is None:
        cfg = QualityShiftConfig(key=key, value=value)
        db.add(cfg)
    else:
        cfg.value = value
    await db.flush()
    return cfg


def shift_duty_teams(
    teams: list[dict[str, Any]],
    start_date: str,
    period_days: int,
    duty_count: int,
    on_date: str,
    team_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    """按轮换规则算当日当班班组。

    team_order 非空：班组按该顺序排列（未列出的班组不参与轮换），
    每 period_days 天滑一位，同时 duty_count 个班组当班；
    为空则 teams 按 seq 排序滑窗。
    """
    from datetime import date

    ordered = teams
    if team_order:
        by_name = {t["name"]: t for t in teams}
        ordered = [by_name[name] for name in team_order if name in by_name]
    n = len(ordered)
    if n == 0 or duty_count <= 0:
        return []
    d0 = date.fromisoformat(start_date)
    d1 = date.fromisoformat(on_date)
    days = (d1 - d0).days
    k = (max(days, 0) // max(period_days, 1)) % n
    out = []
    for i in range(min(duty_count, n)):
        out.append(ordered[(k + i) % n])
    return out
