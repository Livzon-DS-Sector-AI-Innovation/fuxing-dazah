"""QA 年度产品审核（APR）数据访问层：只负责 SQL，校验/审计由 service 编排。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    AprAnnualReview,
    AprBatch,
    AprItem,
    AprProduct,
    AprSection,
    AprValue,
)
from app.shared.sql import escape_like

# ───────────────────────── 产品 ─────────────────────────


async def list_products(
    db: AsyncSession, *, active_only: bool = False
) -> list[AprProduct]:
    conditions: list[ColumnElement[bool]] = [AprProduct.is_deleted.is_(False)]
    if active_only:
        conditions.append(AprProduct.is_active.is_(True))
    result = await db.execute(
        select(AprProduct)
        .where(*conditions)
        .order_by(AprProduct.sort_order, AprProduct.code)
    )
    return list(result.scalars())


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> AprProduct | None:
    result = await db.execute(
        select(AprProduct)
        .where(AprProduct.id == product_id, AprProduct.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_product_by_code(
    db: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> AprProduct | None:
    conditions: list[ColumnElement[bool]] = [
        AprProduct.code == code,
        AprProduct.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(AprProduct.id != exclude_id)
    result = await db.execute(select(AprProduct).where(*conditions))
    return result.scalar_one_or_none()


async def find_product_by_name(
    db: AsyncSession, name: str, *, exclude_id: uuid.UUID | None = None
) -> AprProduct | None:
    conditions: list[ColumnElement[bool]] = [
        AprProduct.name == name,
        AprProduct.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(AprProduct.id != exclude_id)
    result = await db.execute(select(AprProduct).where(*conditions))
    return result.scalar_one_or_none()


async def count_sections_of_product(db: AsyncSession, product_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(AprSection)
        .where(AprSection.product_id == product_id, AprSection.is_deleted.is_(False))
    )
    return int(result.scalar_one())


async def count_batches_of_product(db: AsyncSession, product_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(AprBatch)
        .where(AprBatch.product_id == product_id, AprBatch.is_deleted.is_(False))
    )
    return int(result.scalar_one())


async def count_sections_and_items_by_product(
    db: AsyncSession,
) -> dict[uuid.UUID, tuple[int, int]]:
    """一次查出每个产品的段数与列定义数（配置页展示「已配置多少」用）。"""
    section_rows = await db.execute(
        select(AprSection.product_id, func.count())
        .where(AprSection.is_deleted.is_(False))
        .group_by(AprSection.product_id)
    )
    item_rows = await db.execute(
        select(AprSection.product_id, func.count(AprItem.id))
        .select_from(AprSection)
        .join(AprItem, AprItem.section_id == AprSection.id)
        .where(AprSection.is_deleted.is_(False), AprItem.is_deleted.is_(False))
        .group_by(AprSection.product_id)
    )
    section_counts = {product_id: int(count) for product_id, count in section_rows}
    item_counts = {product_id: int(count) for product_id, count in item_rows}
    return {
        product_id: (section_counts.get(product_id, 0), item_counts.get(product_id, 0))
        for product_id in section_counts.keys() | item_counts.keys()
    }


# ───────────────────────── 段 ─────────────────────────


async def list_sections(db: AsyncSession, product_id: uuid.UUID) -> list[AprSection]:
    result = await db.execute(
        select(AprSection)
        .where(AprSection.product_id == product_id, AprSection.is_deleted.is_(False))
        .order_by(AprSection.sort_order, AprSection.created_at)
    )
    return list(result.scalars())


async def get_section(db: AsyncSession, section_id: uuid.UUID) -> AprSection | None:
    result = await db.execute(
        select(AprSection)
        .where(AprSection.id == section_id, AprSection.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_section_by_name(
    db: AsyncSession,
    product_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> AprSection | None:
    """同产品下的同名段（段名唯一作用域 = 产品）。"""
    conditions: list[ColumnElement[bool]] = [
        AprSection.product_id == product_id,
        AprSection.name == name,
        AprSection.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(AprSection.id != exclude_id)
    result = await db.execute(select(AprSection).where(*conditions))
    return result.scalar_one_or_none()


async def count_batches_of_section(db: AsyncSession, section_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(AprBatch)
        .where(AprBatch.section_id == section_id, AprBatch.is_deleted.is_(False))
    )
    return int(result.scalar_one())


# ───────────────────────── 列定义 ─────────────────────────


async def list_items(
    db: AsyncSession, section_id: uuid.UUID, *, active_only: bool = False
) -> list[AprItem]:
    conditions: list[ColumnElement[bool]] = [
        AprItem.section_id == section_id,
        AprItem.is_deleted.is_(False),
    ]
    if active_only:
        conditions.append(AprItem.is_active.is_(True))
    result = await db.execute(
        select(AprItem)
        .where(*conditions)
        .order_by(AprItem.sort_order, AprItem.created_at)
    )
    return list(result.scalars())


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> AprItem | None:
    result = await db.execute(
        select(AprItem)
        .where(AprItem.id == item_id, AprItem.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_item_by_code(
    db: AsyncSession, section_id: uuid.UUID, code: str
) -> AprItem | None:
    result = await db.execute(
        select(AprItem).where(
            AprItem.section_id == section_id,
            AprItem.code == code,
            AprItem.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_item_codes(db: AsyncSession, section_id: uuid.UUID) -> set[str]:
    """段内已占用的列编码集合（批量建列查重用）。"""
    result = await db.execute(
        select(AprItem.code).where(
            AprItem.section_id == section_id,
            AprItem.is_deleted.is_(False),
        )
    )
    return {code for code in result.scalars() if code}


async def max_sort_order(db: AsyncSession, section_id: uuid.UUID) -> int:
    """段内最大列顺序；空段返回 0。"""
    result = await db.execute(
        select(func.coalesce(func.max(AprItem.sort_order), 0)).where(
            AprItem.section_id == section_id,
            AprItem.is_deleted.is_(False),
        )
    )
    return int(result.scalar_one())


async def count_values_of_item(db: AsyncSession, item_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(AprValue)
        .where(AprValue.item_id == item_id, AprValue.is_deleted.is_(False))
    )
    return int(result.scalar_one())


# ───────────────────────── 批次 ─────────────────────────


async def list_batches(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    year: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[AprBatch], int]:
    conditions: list[ColumnElement[bool]] = [
        AprBatch.section_id == section_id,
        AprBatch.is_deleted.is_(False),
    ]
    if year is not None:
        conditions.append(AprBatch.year == year)
    if keyword:
        term = f"%{escape_like(keyword.strip())}%"
        conditions.append(AprBatch.batch_no.ilike(term, escape="\\"))
    base = select(AprBatch).where(*conditions)
    total = int(
        (
            await db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
    )
    result = await db.execute(
        base.order_by(AprBatch.seq.nulls_last(), AprBatch.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total


async def list_batches_of_section(
    db: AsyncSession, section_id: uuid.UUID, *, year: int | None = None
) -> list[AprBatch]:
    """汇总/趋势用：不分页全量（单段单年批次量级为几十）。"""
    conditions: list[ColumnElement[bool]] = [
        AprBatch.section_id == section_id,
        AprBatch.is_deleted.is_(False),
    ]
    if year is not None:
        conditions.append(AprBatch.year == year)
    result = await db.execute(
        select(AprBatch)
        .where(*conditions)
        .order_by(AprBatch.seq.nulls_last(), AprBatch.created_at)
    )
    return list(result.scalars())


async def get_batch(db: AsyncSession, batch_id: uuid.UUID) -> AprBatch | None:
    result = await db.execute(
        select(AprBatch)
        .where(AprBatch.id == batch_id, AprBatch.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_batch(
    db: AsyncSession, section_id: uuid.UUID, year: int, batch_no: str
) -> AprBatch | None:
    result = await db.execute(
        select(AprBatch).where(
            AprBatch.section_id == section_id,
            AprBatch.year == year,
            AprBatch.batch_no == batch_no,
            AprBatch.is_deleted.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def count_batches_in_year(
    db: AsyncSession, product_id: uuid.UUID, year: int
) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(AprBatch)
        .where(
            AprBatch.product_id == product_id,
            AprBatch.year == year,
            AprBatch.is_deleted.is_(False),
        )
    )
    return int(result.scalar_one())


async def distinct_batch_years(db: AsyncSession, product_id: uuid.UUID) -> list[int]:
    result = await db.execute(
        select(AprBatch.year)
        .where(AprBatch.product_id == product_id, AprBatch.is_deleted.is_(False))
        .distinct()
        .order_by(AprBatch.year.desc())
    )
    return [int(y) for y in result.scalars()]


# ───────────────────────── 值 ─────────────────────────


async def list_values_of_batch(db: AsyncSession, batch_id: uuid.UUID) -> list[AprValue]:
    result = await db.execute(
        select(AprValue)
        .where(AprValue.batch_id == batch_id, AprValue.is_deleted.is_(False))
        .order_by(AprValue.row_seq, AprItem.sort_order)
        .join(AprItem, AprValue.item_id == AprItem.id, isouter=True)
    )
    return list(result.scalars().unique())


async def replace_batch_values(
    db: AsyncSession,
    batch_id: uuid.UUID,
    rows: Sequence[dict[str, Any]],
    *,
    actor_id: uuid.UUID | None,
) -> int:
    """全量替换某批次的值：硬删旧值 + 批量插入（网格单元格非审计对象）。"""
    await db.execute(
        delete(AprValue).where(
            AprValue.batch_id == batch_id,
            # 软删残留一并清掉，避免部分唯一索引埋雷。
        )
    )
    if not rows:
        return 0
    payload = [
        {**row, "batch_id": batch_id, "created_by": actor_id, "updated_by": actor_id}
        for row in rows
    ]
    await db.execute(insert(AprValue), payload)
    return len(payload)


async def delete_values_of_batch(db: AsyncSession, batch_id: uuid.UUID) -> None:
    await db.execute(delete(AprValue).where(AprValue.batch_id == batch_id))


async def load_section_values(
    db: AsyncSession,
    section_id: uuid.UUID,
    *,
    year: int | None = None,
    item_ids: Sequence[uuid.UUID] | None = None,
) -> list[Any]:
    """汇总用取值查询：返回 (batch_id, item_id, row_seq, value_num, value_text, row_label)。"""
    conditions: list[ColumnElement[bool]] = [
        AprBatch.section_id == section_id,
        AprBatch.is_deleted.is_(False),
        AprValue.is_deleted.is_(False),
    ]
    if year is not None:
        conditions.append(AprBatch.year == year)
    if item_ids:
        conditions.append(AprValue.item_id.in_(list(item_ids)))
    result = await db.execute(
        select(
            AprValue.batch_id,
            AprValue.item_id,
            AprValue.row_seq,
            AprValue.value_num,
            AprValue.value_text,
            AprValue.row_label,
        )
        .join(AprBatch, AprValue.batch_id == AprBatch.id)
        .where(*conditions)
    )
    return list(result.all())


async def load_numeric_series(
    db: AsyncSession, item_id: uuid.UUID, *, year: int | None = None
) -> list[Any]:
    """趋势序列：数值行 + 文字结果行（未检出等），按批次序。

    返回 (batch_id, batch_no, seq, year, row_seq, value_num, value_text)；
    文字行 value_num 为空，由 service 按列口径决定按 0 计入还是排除。
    """
    conditions: list[ColumnElement[bool]] = [
        AprValue.item_id == item_id,
        AprValue.is_deleted.is_(False),
        AprBatch.is_deleted.is_(False),
        or_(AprValue.value_num.is_not(None), AprValue.value_text.is_not(None)),
    ]
    if year is not None:
        conditions.append(AprBatch.year == year)
    result = await db.execute(
        select(
            AprValue.batch_id,
            AprBatch.batch_no,
            AprBatch.seq,
            AprBatch.year,
            AprValue.row_seq,
            AprValue.value_num,
            AprValue.value_text,
        )
        .join(AprBatch, AprValue.batch_id == AprBatch.id)
        .where(*conditions)
        # row_seq 兜底同批次多行（multi_row）的稳定顺序
        .order_by(
            AprBatch.year, AprBatch.seq.nulls_last(), AprBatch.created_at,
            AprValue.row_seq,
        )
    )
    return list(result.all())


async def has_numeric_values(db: AsyncSession, item_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(AprValue)
        .where(
            AprValue.item_id == item_id,
            AprValue.is_deleted.is_(False),
            AprValue.value_num.is_not(None),
        )
        .limit(1)
    )
    return int(result.scalar_one()) > 0


async def count_values_in_locked_years(db: AsyncSession, item_id: uuid.UUID) -> int:
    """该列落在「已锁定年度」里的已录值行数（列限度编辑守卫用）。"""
    result = await db.execute(
        select(func.count())
        .select_from(AprValue)
        .join(AprBatch, AprValue.batch_id == AprBatch.id)
        .join(
            AprAnnualReview,
            (AprAnnualReview.product_id == AprBatch.product_id)
            & (AprAnnualReview.year == AprBatch.year)
            & (AprAnnualReview.status == "locked")
            & (AprAnnualReview.is_deleted.is_(False)),
        )
        .where(AprValue.item_id == item_id, AprValue.is_deleted.is_(False))
    )
    return int(result.scalar_one())


# ───────────────────────── 年度锁定 ─────────────────────────


async def get_annual_review(
    db: AsyncSession,
    product_id: uuid.UUID,
    year: int,
    *,
    for_update: bool = False,
) -> AprAnnualReview | None:
    """for_update=True 对锁定行加行锁：写守卫与锁定/解锁串行化用。"""
    stmt = select(AprAnnualReview).where(
        AprAnnualReview.product_id == product_id,
        AprAnnualReview.year == year,
        AprAnnualReview.is_deleted.is_(False),
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_annual_reviews(
    db: AsyncSession, product_id: uuid.UUID
) -> list[AprAnnualReview]:
    result = await db.execute(
        select(AprAnnualReview)
        .where(
            AprAnnualReview.product_id == product_id,
            AprAnnualReview.is_deleted.is_(False),
        )
        .order_by(AprAnnualReview.year.desc())
    )
    return list(result.scalars())


def touch_lock_state(
    review: AprAnnualReview,
    *,
    locked: bool,
    actor_id: uuid.UUID | None,
) -> None:
    review.status = "locked" if locked else "open"
    if locked:
        review.locked_at = datetime.now(UTC)
        review.locked_by = actor_id
    else:
        review.locked_at = None
        review.locked_by = None


def new_annual_review(
    product_id: uuid.UUID, year: int, *, actor_id: uuid.UUID | None
) -> AprAnnualReview:
    return AprAnnualReview(
        product_id=product_id,
        year=year,
        status="open",
        created_by=actor_id,
        updated_by=actor_id,
    )
