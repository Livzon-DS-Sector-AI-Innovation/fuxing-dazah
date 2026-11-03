"""QA 偏差管理数据访问层：只负责 SQL，状态/校验/审计由 service 编排。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    Capa,
    CapaAction,
    CapaStatusLog,
    Deviation,
    DeviationAttachment,
    DeviationHypothesisTest,
    DeviationItem,
    DeviationStatusLog,
)
from app.shared.sql import escape_like

# 重复偏差：同部门同组别同根因分类在 3 个月内再发。
REPEAT_WINDOW = timedelta(days=90)


# ───────────────────────── 偏差 ─────────────────────────


async def get_deviation(
    db: AsyncSession, deviation_id: uuid.UUID, *, for_update: bool = False
) -> Deviation | None:
    stmt = (
        select(Deviation)
        .where(Deviation.id == deviation_id, Deviation.is_deleted.is_(False))
        # 写操作后重新读取时强制覆盖 identity map，避免返回旧的 updated_at。
        .execution_options(populate_existing=True)
    )
    if for_update:
        # 状态流转/延期/删除等写路径串行化同一偏差，避免并发双写。
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_deviations_by_ids(
    db: AsyncSession, ids: Sequence[uuid.UUID]
) -> list[Deviation]:
    if not ids:
        return []
    result = await db.execute(
        select(Deviation).where(
            Deviation.id.in_(list(ids)), Deviation.is_deleted.is_(False)
        )
    )
    return list(result.scalars())


async def get_max_deviation_no(db: AsyncSession, prefix: str) -> str | None:
    """当月已用的最大编号；软删行也算，避免编号复用。

    先按长度再按字面排序，流水号溢出三位时仍能取到真正的最大值。
    """
    result = await db.execute(
        select(Deviation.deviation_no)
        .where(Deviation.deviation_no.like(f"{escape_like(prefix)}%", escape="\\"))
        .order_by(
            func.length(Deviation.deviation_no).desc(), Deviation.deviation_no.desc()
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_deviations(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    status: str | None = None,
    classification: str | None = None,
    root_cause_category: str | None = None,
    department_name: str | None = None,
    is_repeat: bool | None = None,
    overdue_only: bool = False,
    discovery_from: date | None = None,
    discovery_to: date | None = None,
    today: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Deviation], int]:
    conditions: list[ColumnElement[bool]] = [Deviation.is_deleted.is_(False)]
    if status:
        conditions.append(Deviation.status == status)
    if classification:
        conditions.append(Deviation.classification == classification)
    if root_cause_category:
        conditions.append(Deviation.root_cause_category == root_cause_category)
    if department_name:
        conditions.append(Deviation.department_name == department_name)
    if is_repeat is not None:
        conditions.append(Deviation.is_repeat.is_(is_repeat))
    if overdue_only and today is not None:
        conditions.append(Deviation.status != "closed")
        conditions.append(Deviation.due_date < today)
    if discovery_from:
        conditions.append(Deviation.discovery_date >= discovery_from)
    if discovery_to:
        conditions.append(Deviation.discovery_date <= discovery_to)
    if keyword:
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                Deviation.deviation_no.ilike(term, escape="\\"),
                Deviation.description.ilike(term, escape="\\"),
                Deviation.department_name.ilike(term, escape="\\"),
                Deviation.reporter_name.ilike(term, escape="\\"),
                Deviation.id.in_(
                    select(DeviationItem.deviation_id).where(
                        DeviationItem.is_deleted.is_(False),
                        or_(
                            DeviationItem.name.ilike(term, escape="\\"),
                            DeviationItem.batch_no.ilike(term, escape="\\"),
                        ),
                    )
                ),
            )
        )
    base = select(Deviation).where(*conditions)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
    )
    result = await db.execute(
        base.order_by(Deviation.deviation_no.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def count_deviations_by_status(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(Deviation.status, func.count())
        .where(Deviation.is_deleted.is_(False))
        .group_by(Deviation.status)
    )
    return {str(status): int(count) for status, count in result.all()}


async def find_repeat_candidates(
    db: AsyncSession, deviation: Deviation
) -> list[Deviation]:
    """同部门（同组别）同根因分类、发现日期在前后 3 个月内的其他偏差。"""
    if not deviation.root_cause_category or not deviation.department_name:
        return []
    conditions: list[ColumnElement[bool]] = [
        Deviation.is_deleted.is_(False),
        Deviation.id != deviation.id,
        Deviation.department_name == deviation.department_name,
        Deviation.root_cause_category == deviation.root_cause_category,
        Deviation.discovery_date >= deviation.discovery_date - REPEAT_WINDOW,
        Deviation.discovery_date <= deviation.discovery_date + REPEAT_WINDOW,
    ]
    if deviation.group_name:
        conditions.append(Deviation.group_name == deviation.group_name)
    result = await db.execute(
        select(Deviation).where(*conditions).order_by(Deviation.discovery_date.desc())
    )
    return list(result.scalars())


async def get_items(db: AsyncSession, deviation_id: uuid.UUID) -> list[DeviationItem]:
    result = await db.execute(
        select(DeviationItem)
        .where(
            DeviationItem.deviation_id == deviation_id,
            DeviationItem.is_deleted.is_(False),
        )
        .order_by(DeviationItem.sort_order, DeviationItem.created_at)
    )
    return list(result.scalars())


async def get_hypothesis_tests(
    db: AsyncSession, deviation_id: uuid.UUID
) -> list[DeviationHypothesisTest]:
    result = await db.execute(
        select(DeviationHypothesisTest)
        .where(
            DeviationHypothesisTest.deviation_id == deviation_id,
            DeviationHypothesisTest.is_deleted.is_(False),
        )
        .order_by(
            DeviationHypothesisTest.sort_order, DeviationHypothesisTest.created_at
        )
    )
    return list(result.scalars())


async def get_status_logs(
    db: AsyncSession, deviation_id: uuid.UUID
) -> list[DeviationStatusLog]:
    result = await db.execute(
        select(DeviationStatusLog)
        .where(
            DeviationStatusLog.deviation_id == deviation_id,
            DeviationStatusLog.is_deleted.is_(False),
        )
        .order_by(DeviationStatusLog.created_at)
    )
    return list(result.scalars())


async def get_attachments(
    db: AsyncSession, deviation_id: uuid.UUID
) -> list[DeviationAttachment]:
    result = await db.execute(
        select(DeviationAttachment)
        .where(
            DeviationAttachment.deviation_id == deviation_id,
            DeviationAttachment.is_deleted.is_(False),
        )
        .order_by(DeviationAttachment.created_at)
    )
    return list(result.scalars())


async def get_attachment(
    db: AsyncSession, deviation_id: uuid.UUID, attachment_id: uuid.UUID
) -> DeviationAttachment | None:
    result = await db.execute(
        select(DeviationAttachment).where(
            DeviationAttachment.id == attachment_id,
            DeviationAttachment.deviation_id == deviation_id,
            DeviationAttachment.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


# ───────────────────────── CAPA ─────────────────────────


async def get_capa(
    db: AsyncSession, capa_id: uuid.UUID, *, for_update: bool = False
) -> Capa | None:
    stmt = (
        select(Capa)
        .where(Capa.id == capa_id, Capa.is_deleted.is_(False))
        # 同 get_deviation：UPDATE 后必须覆盖缓存值。
        .execution_options(populate_existing=True)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_capas_for_deviation(
    db: AsyncSession, deviation_id: uuid.UUID
) -> list[Capa]:
    result = await db.execute(
        select(Capa)
        .where(Capa.deviation_id == deviation_id, Capa.is_deleted.is_(False))
        .order_by(Capa.created_at)
    )
    return list(result.scalars())


async def count_capas_for_deviation(db: AsyncSession, deviation_id: uuid.UUID) -> int:
    """含软删行：编号后缀不复用。"""
    result = await db.execute(
        select(func.count()).select_from(Capa).where(Capa.deviation_id == deviation_id)
    )
    return int(result.scalar_one())


async def list_capas(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    status: str | None = None,
    severity: str | None = None,
    deviation_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Capa], int]:
    conditions: list[ColumnElement[bool]] = [Capa.is_deleted.is_(False)]
    if status:
        conditions.append(Capa.status == status)
    if severity:
        conditions.append(Capa.severity == severity)
    if deviation_id:
        conditions.append(Capa.deviation_id == deviation_id)
    if keyword:
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(
            or_(
                Capa.capa_no.ilike(term, escape="\\"),
                Capa.summary.ilike(term, escape="\\"),
                Capa.responsible_department_name.ilike(term, escape="\\"),
            )
        )
    base = select(Capa).where(*conditions)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
    )
    result = await db.execute(
        base.order_by(Capa.capa_no.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def count_capas_by_status(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(
        select(Capa.status, func.count())
        .where(Capa.is_deleted.is_(False))
        .group_by(Capa.status)
    )
    return {str(status): int(count) for status, count in result.all()}


async def get_capa_actions(db: AsyncSession, capa_id: uuid.UUID) -> list[CapaAction]:
    result = await db.execute(
        select(CapaAction)
        .where(CapaAction.capa_id == capa_id, CapaAction.is_deleted.is_(False))
        .order_by(CapaAction.sort_order, CapaAction.created_at)
    )
    return list(result.scalars())


async def get_capa_action(
    db: AsyncSession, capa_id: uuid.UUID, action_id: uuid.UUID
) -> CapaAction | None:
    result = await db.execute(
        select(CapaAction).where(
            CapaAction.id == action_id,
            CapaAction.capa_id == capa_id,
            CapaAction.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def get_capa_status_logs(
    db: AsyncSession, capa_id: uuid.UUID
) -> list[CapaStatusLog]:
    result = await db.execute(
        select(CapaStatusLog)
        .where(CapaStatusLog.capa_id == capa_id, CapaStatusLog.is_deleted.is_(False))
        .order_by(CapaStatusLog.created_at)
    )
    return list(result.scalars())
