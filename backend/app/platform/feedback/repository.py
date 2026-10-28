"""系统反馈数据访问。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.feedback.models import Feedback, FeedbackAttachment, FeedbackType


async def create(db: AsyncSession, feedback: Feedback) -> Feedback:
    db.add(feedback)
    await db.flush()
    return feedback


async def get_by_id(
    db: AsyncSession, feedback_id: uuid.UUID, *, for_update: bool = False
) -> Feedback | None:
    stmt = select(Feedback).where(
        Feedback.id == feedback_id,
        Feedback.is_deleted == False,  # noqa: E712
    )
    if for_update:
        # 附件数量/已处理冻结都是 check-then-act，锁父行串行化同一反馈的写路径。
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_paginated(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    is_handled: bool | None = None,
    feedback_type: FeedbackType | None = None,
    created_by: uuid.UUID | None = None,
) -> tuple[list[Feedback], int]:
    """按条件分页，最新提交在前。"""
    stmt = select(Feedback).where(Feedback.is_deleted == False)  # noqa: E712
    if is_handled is not None:
        stmt = stmt.where(Feedback.is_handled == is_handled)
    if feedback_type is not None:
        stmt = stmt.where(Feedback.type == feedback_type.value)
    if created_by is not None:
        stmt = stmt.where(Feedback.created_by == created_by)

    total = (
        await db.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Feedback.created_at.desc(), Feedback.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total)


async def count_pending(db: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(Feedback)
        .where(
            Feedback.is_deleted == False,  # noqa: E712
            Feedback.is_handled == False,  # noqa: E712
        )
    )
    return int((await db.execute(stmt)).scalar_one())


# ───────────────────────── 截图附件 ─────────────────────────


async def add_attachment(
    db: AsyncSession, attachment: FeedbackAttachment
) -> FeedbackAttachment:
    db.add(attachment)
    await db.flush()
    return attachment


async def get_attachment(
    db: AsyncSession, feedback_id: uuid.UUID, attachment_id: uuid.UUID
) -> FeedbackAttachment | None:
    stmt = select(FeedbackAttachment).where(
        FeedbackAttachment.id == attachment_id,
        FeedbackAttachment.feedback_id == feedback_id,
        FeedbackAttachment.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def count_attachments(db: AsyncSession, feedback_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(FeedbackAttachment)
        .where(
            FeedbackAttachment.feedback_id == feedback_id,
            FeedbackAttachment.is_deleted == False,  # noqa: E712
        )
    )
    return int((await db.execute(stmt)).scalar_one())


async def list_attachments_for(
    db: AsyncSession, feedback_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, list[FeedbackAttachment]]:
    """一次 IN 查询取回多条反馈的截图，按上传先后排序，避免列表页 N+1。"""
    grouped: dict[uuid.UUID, list[FeedbackAttachment]] = {
        feedback_id: [] for feedback_id in feedback_ids
    }
    if not feedback_ids:
        return grouped
    stmt = (
        select(FeedbackAttachment)
        .where(
            FeedbackAttachment.feedback_id.in_(list(feedback_ids)),
            FeedbackAttachment.is_deleted == False,  # noqa: E712
        )
        .order_by(FeedbackAttachment.created_at.asc(), FeedbackAttachment.id.asc())
    )
    for attachment in (await db.execute(stmt)).scalars():
        grouped.setdefault(attachment.feedback_id, []).append(attachment)
    return grouped
