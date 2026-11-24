"""QA COA 数据访问层：只负责 SQL，校验/守卫由 service 编排。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.qa.models import (
    CoaProduct,
    CoaProductField,
    CoaReport,
    CoaReportValue,
    CoaStandard,
    CoaStandardField,
    CoaStandardItem,
)

# ───────────────────────── 产品 ─────────────────────────


async def list_products(
    db: AsyncSession, *, active_only: bool = False
) -> list[CoaProduct]:
    conditions: list[ColumnElement[bool]] = [CoaProduct.is_deleted.is_(False)]
    if active_only:
        conditions.append(CoaProduct.is_active.is_(True))
    result = await db.execute(
        select(CoaProduct)
        .where(*conditions)
        .order_by(CoaProduct.sort_order, CoaProduct.code)
    )
    return list(result.scalars())


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> CoaProduct | None:
    result = await db.execute(
        select(CoaProduct)
        .where(CoaProduct.id == product_id, CoaProduct.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_product_by_code(
    db: AsyncSession, code: str, *, exclude_id: uuid.UUID | None = None
) -> CoaProduct | None:
    conditions: list[ColumnElement[bool]] = [
        CoaProduct.code == code,
        CoaProduct.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(CoaProduct.id != exclude_id)
    result = await db.execute(select(CoaProduct).where(*conditions))
    return result.scalar_one_or_none()


async def find_product_by_name(
    db: AsyncSession, name: str, *, exclude_id: uuid.UUID | None = None
) -> CoaProduct | None:
    conditions: list[ColumnElement[bool]] = [
        CoaProduct.name == name,
        CoaProduct.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(CoaProduct.id != exclude_id)
    result = await db.execute(select(CoaProduct).where(*conditions))
    return result.scalar_one_or_none()


async def count_standards_by_product(db: AsyncSession) -> dict[uuid.UUID, int]:
    result = await db.execute(
        select(CoaStandard.product_id, func.count())
        .where(CoaStandard.is_deleted.is_(False))
        .group_by(CoaStandard.product_id)
    )
    return {product_id: int(count) for product_id, count in result}


# ───────────────────────── 产品批次信息字段配置 ─────────────────────────


async def list_product_fields(
    db: AsyncSession, product_id: uuid.UUID
) -> list[CoaProductField]:
    result = await db.execute(
        select(CoaProductField)
        .where(
            CoaProductField.product_id == product_id,
            CoaProductField.is_deleted.is_(False),
        )
        .order_by(CoaProductField.sort_order, CoaProductField.created_at)
    )
    return list(result.scalars())


async def replace_product_fields(
    db: AsyncSession,
    product_id: uuid.UUID,
    rows: list[dict[str, Any]],
) -> None:
    """字段配置全量替换：硬删后批量插入（配置非审计对象，报告值同款）。"""
    await db.execute(
        delete(CoaProductField).where(CoaProductField.product_id == product_id)
    )
    if rows:
        for row in rows:
            db.add(CoaProductField(product_id=product_id, **row))
        await db.flush()


# ───────────────────────── 客户标准 ─────────────────────────


async def list_standards(
    db: AsyncSession,
    *,
    product_id: uuid.UUID | None = None,
    active_only: bool = False,
) -> list[CoaStandard]:
    conditions: list[ColumnElement[bool]] = [CoaStandard.is_deleted.is_(False)]
    if product_id is not None:
        conditions.append(CoaStandard.product_id == product_id)
    if active_only:
        conditions.append(CoaStandard.is_active.is_(True))
    result = await db.execute(
        select(CoaStandard)
        .where(*conditions)
        .order_by(CoaStandard.product_id, CoaStandard.code)
    )
    return list(result.scalars())


async def get_standard(db: AsyncSession, standard_id: uuid.UUID) -> CoaStandard | None:
    result = await db.execute(
        select(CoaStandard)
        .where(CoaStandard.id == standard_id, CoaStandard.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_standard_by_code(
    db: AsyncSession,
    product_id: uuid.UUID,
    code: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> CoaStandard | None:
    conditions: list[ColumnElement[bool]] = [
        CoaStandard.product_id == product_id,
        CoaStandard.code == code,
        CoaStandard.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(CoaStandard.id != exclude_id)
    result = await db.execute(select(CoaStandard).where(*conditions))
    return result.scalar_one_or_none()


async def count_items_by_standard(db: AsyncSession) -> dict[uuid.UUID, int]:
    result = await db.execute(
        select(CoaStandardItem.standard_id, func.count())
        .where(CoaStandardItem.is_deleted.is_(False))
        .group_by(CoaStandardItem.standard_id)
    )
    return {standard_id: int(count) for standard_id, count in result}


async def count_reports_by_standard(db: AsyncSession) -> dict[uuid.UUID, int]:
    result = await db.execute(
        select(CoaReport.standard_id, func.count())
        .where(CoaReport.is_deleted.is_(False))
        .group_by(CoaReport.standard_id)
    )
    return {standard_id: int(count) for standard_id, count in result}


# ───────────────────────── 标准级字段覆盖（稀疏） ─────────────────────────


async def list_standard_fields(
    db: AsyncSession, standard_id: uuid.UUID
) -> list[CoaStandardField]:
    result = await db.execute(
        select(CoaStandardField)
        .where(
            CoaStandardField.standard_id == standard_id,
            CoaStandardField.is_deleted.is_(False),
        )
        .order_by(CoaStandardField.sort_order, CoaStandardField.created_at)
    )
    return list(result.scalars())


async def replace_standard_fields(
    db: AsyncSession,
    standard_id: uuid.UUID,
    rows: list[dict[str, Any]],
) -> None:
    """标准字段覆盖全量替换：硬删后批量插入（配置非审计对象）。"""
    await db.execute(
        delete(CoaStandardField).where(CoaStandardField.standard_id == standard_id)
    )
    if rows:
        for row in rows:
            db.add(CoaStandardField(standard_id=standard_id, **row))
        await db.flush()


async def delete_standard_fields(db: AsyncSession, standard_id: uuid.UUID) -> None:
    """恢复产品默认=删覆盖；删除标准时也走这里清孤儿。"""
    await db.execute(
        delete(CoaStandardField).where(CoaStandardField.standard_id == standard_id)
    )


# ───────────────────────── 标准项目 ─────────────────────────


async def list_items(
    db: AsyncSession, standard_id: uuid.UUID
) -> list[CoaStandardItem]:
    result = await db.execute(
        select(CoaStandardItem)
        .where(
            CoaStandardItem.standard_id == standard_id,
            CoaStandardItem.is_deleted.is_(False),
        )
        .order_by(CoaStandardItem.sort_order, CoaStandardItem.created_at)
    )
    return list(result.scalars())


async def list_items_of_standards(
    db: AsyncSession, standard_ids: list[uuid.UUID]
) -> list[CoaStandardItem]:
    if not standard_ids:
        return []
    result = await db.execute(
        select(CoaStandardItem)
        .where(
            CoaStandardItem.standard_id.in_(standard_ids),
            CoaStandardItem.is_deleted.is_(False),
        )
        .order_by(CoaStandardItem.standard_id, CoaStandardItem.sort_order)
    )
    return list(result.scalars())


async def get_item(db: AsyncSession, item_id: uuid.UUID) -> CoaStandardItem | None:
    result = await db.execute(
        select(CoaStandardItem).where(
            CoaStandardItem.id == item_id, CoaStandardItem.is_deleted.is_(False)
        )
    )
    return result.scalar_one_or_none()


# ───────────────────────── 出具报告 ─────────────────────────


async def list_reports(db: AsyncSession, product_id: uuid.UUID) -> list[CoaReport]:
    result = await db.execute(
        select(CoaReport)
        .where(CoaReport.product_id == product_id, CoaReport.is_deleted.is_(False))
        .order_by(CoaReport.created_at.desc())
    )
    return list(result.scalars())


async def get_report(db: AsyncSession, report_id: uuid.UUID) -> CoaReport | None:
    result = await db.execute(
        select(CoaReport)
        .where(CoaReport.id == report_id, CoaReport.is_deleted.is_(False))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def find_report_by_batch(
    db: AsyncSession,
    product_id: uuid.UUID,
    standard_id: uuid.UUID,
    batch_no: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> CoaReport | None:
    conditions: list[ColumnElement[bool]] = [
        CoaReport.product_id == product_id,
        CoaReport.standard_id == standard_id,
        CoaReport.batch_no == batch_no,
        CoaReport.is_deleted.is_(False),
    ]
    if exclude_id is not None:
        conditions.append(CoaReport.id != exclude_id)
    result = await db.execute(select(CoaReport).where(*conditions))
    return result.scalar_one_or_none()


async def count_reports_by_product(db: AsyncSession, product_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(CoaReport)
        .where(CoaReport.product_id == product_id, CoaReport.is_deleted.is_(False))
    )
    return int(result.scalar_one())


# ───────────────────────── 结果值 ─────────────────────────


async def list_values_by_report(
    db: AsyncSession, report_id: uuid.UUID
) -> list[CoaReportValue]:
    result = await db.execute(
        select(CoaReportValue).where(CoaReportValue.report_id == report_id)
    )
    return list(result.scalars())


async def list_values_of_reports(
    db: AsyncSession, report_ids: list[uuid.UUID]
) -> list[CoaReportValue]:
    """矩阵透视：一批报告的全量值（值行无软删语义，硬删+重插）。"""
    if not report_ids:
        return []
    result = await db.execute(
        select(CoaReportValue).where(CoaReportValue.report_id.in_(report_ids))
    )
    return list(result.scalars())


async def replace_report_values(
    db: AsyncSession,
    report_id: uuid.UUID,
    rows: list[dict[str, Any]],
) -> None:
    """值全量替换：硬删后批量插入（矩阵单元格非审计对象，APR 同款）。"""
    await db.execute(
        delete(CoaReportValue).where(CoaReportValue.report_id == report_id)
    )
    if rows:
        for row in rows:
            db.add(CoaReportValue(report_id=report_id, **row))
        await db.flush()


async def delete_report_values(db: AsyncSession, report_id: uuid.UUID) -> None:
    await db.execute(
        delete(CoaReportValue).where(CoaReportValue.report_id == report_id)
    )
