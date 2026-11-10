"""PQR 年度锁定：产品×年度定稿后冻结数据，写入方按此拦截。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import AprAnnualReview
from app.modules.qa.repository import apr as repo
from app.modules.qa.service.apr.common import _actor_id, _audit, _get_product_or_404
from app.platform.identity.models import User


def _review_dict(row: AprAnnualReview) -> dict[str, Any]:
    return {
        "product_id": str(row.product_id),
        "year": row.year,
        "status": row.status,
        "locked_at": row.locked_at.isoformat() if row.locked_at else None,
        "locked_by": str(row.locked_by) if row.locked_by else None,
    }


async def list_annual_reviews(
    db: AsyncSession, product_id: uuid.UUID
) -> list[dict[str, Any]]:
    await _get_product_or_404(db, product_id)
    return [_review_dict(r) for r in await repo.list_annual_reviews(db, product_id)]


async def set_annual_review_lock(
    db: AsyncSession,
    product_id: uuid.UUID,
    year: int,
    *,
    locked: bool,
    user: User | None,
) -> dict[str, Any]:
    product = await _get_product_or_404(db, product_id)
    if locked and await repo.count_batches_in_year(db, product_id, year) == 0:
        raise AppException(
            status_code=422,
            message=f"{product.name} {year} 年度没有任何批次数据，无需锁定。",
        )
    # FOR UPDATE 读锁定行：与写入方的 _ensure_year_open 串行化，同时把
    # 「重复锁/重复解锁」的比对也置于行锁之后，避免交错窗口里双双通过。
    review = await repo.get_annual_review(db, product_id, year, for_update=True)
    if review is None:
        review = repo.new_annual_review(product_id, year, actor_id=_actor_id(user))
        try:
            # 两个首锁请求并发插入会撞 uq_qa_apr_annual_reviews_product_year，
            # 回滚到 SAVEPOINT 后按对方已提交的结果重读判定。
            async with db.begin_nested():
                db.add(review)
                await db.flush()
        except IntegrityError:
            review = await repo.get_annual_review(db, product_id, year, for_update=True)
            assert review is not None
    if review.status == ("locked" if locked else "open"):
        raise AppException(
            status_code=422,
            message=f"{product.name} {year} 年度当前已是"
            f"{'锁定' if locked else '开放'}状态。",
        )
    repo.touch_lock_state(review, locked=locked, actor_id=_actor_id(user))
    review.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="lock" if locked else "unlock",
        user=user,
        resource_type="apr_annual_review",
        resource_id=review.id,
        extra={"product": product.name, "year": year},
    )
    return _review_dict(review)
