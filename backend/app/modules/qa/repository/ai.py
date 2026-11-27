"""QA AI 分析运行与提案仓储。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    DocumentAIAnalysisRun,
    MasterObjectProposal,
)


async def get_latest_ai_run(
    db: AsyncSession, version_id: uuid.UUID
) -> DocumentAIAnalysisRun | None:
    result = await db.execute(
        select(DocumentAIAnalysisRun)
        .where(
            DocumentAIAnalysisRun.version_id == version_id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
        .order_by(DocumentAIAnalysisRun.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_ai_run(
    db: AsyncSession, run_id: uuid.UUID
) -> DocumentAIAnalysisRun | None:
    result = await db.execute(
        select(DocumentAIAnalysisRun).where(
            DocumentAIAnalysisRun.id == run_id,
            DocumentAIAnalysisRun.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_proposals(
    db: AsyncSession, *, status: str | None = None, page: int = 1, page_size: int = 50
) -> tuple[list[MasterObjectProposal], int]:
    conditions: list[ColumnElement[bool]] = [MasterObjectProposal.is_deleted.is_(False)]
    if status:
        conditions.append(MasterObjectProposal.status == status)
    base = select(MasterObjectProposal).where(*conditions)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
    )
    result = await db.execute(
        base.order_by(MasterObjectProposal.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total
