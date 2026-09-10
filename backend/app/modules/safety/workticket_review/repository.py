"""作业票审核仓储（WorkTicketReviewRepository）。

负责 safety.work_ticket_reviews / work_ticket_review_violations 的落库与按日期查询。
约定：
- 同一审核日以 date + is_deleted=false 作为幂等键（部分唯一索引）；
- review_id 为逻辑外键，不建物理 FK，应用层通过「先删旧明细再批量插入」保证一致性；
- 重跑覆盖旧审核，重建违规明细，保证结果可复现。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    WorkTicketReview,
    WorkTicketReviewViolation,
)

# review 摘要字段，重跑按 date 幂等时整体覆盖
_REVIEW_FIELDS = (
    "date",
    "total",
    "reviewed",
    "violation_count",
    "compliant_count",
    "data_insufficient",
    "status",
    "raw_json",
    "report_markdown",
    "pushed",
    "push_message_id",
    "error",
    "finished_at",
)


class WorkTicketReviewRepository:
    """作业票审核摘要 + 逐票违规明细的持久化仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_date(self, review_date: date) -> WorkTicketReview | None:
        """按审核日期查回生效（未软删）的审核摘要记录。"""
        stmt = (
            select(WorkTicketReview)
            .where(
                WorkTicketReview.date == review_date,
                WorkTicketReview.is_deleted.is_(False),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_violations(
        self,
        review_id: Any,
    ) -> list[WorkTicketReviewViolation]:
        """按审核批次查回违规/数据不足明细（未软删）。"""
        stmt = (
            select(WorkTicketReviewViolation)
            .where(
                WorkTicketReviewViolation.review_id == review_id,
                WorkTicketReviewViolation.is_deleted.is_(False),
            )
            .order_by(WorkTicketReviewViolation.ticket_no, WorkTicketReviewViolation.rule_no)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def save_review(
        self,
        review: WorkTicketReview,
        violations: list[WorkTicketReviewViolation],
    ) -> WorkTicketReview:
        """按 date 幂等保存一单审核（摘要 + 违规明细）。

        - 已存在 date 记录时：覆盖摘要字段（保留原 id/审计字段）；
        - 不存在时：新增摘要记录；
        - 随后删除该 review_id 的旧违规明细并批量插入最新明细。
        """
        existing = await self.get_by_date(review.date)
        if existing is not None:
            for attr in _REVIEW_FIELDS:
                setattr(existing, attr, getattr(review, attr))
            persisted = existing
        else:
            self.session.add(review)
            persisted = review
        await self.session.flush()

        # 重建违规明细：先删旧，再批量插入（逻辑外键，无物理 FK 级联）
        await self.session.execute(
            delete(WorkTicketReviewViolation).where(
                WorkTicketReviewViolation.review_id == persisted.id,
            )
        )
        for item in violations:
            item.review_id = persisted.id
            self.session.add(item)
        await self.session.flush()

        # 铁律：禁止 db.refresh()。flush 已通过 RETURNING 为 INSERT 回填 id 等 server default；
        # 更新路径上的 updated_at 等列需重新 select 查回，统一按 id re-fetch 返回最新对象。
        fresh_stmt = (
            select(WorkTicketReview)
            .where(WorkTicketReview.id == persisted.id)
        )
        fresh_result = await self.session.execute(fresh_stmt)
        return fresh_result.scalar_one()
