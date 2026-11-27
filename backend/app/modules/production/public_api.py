"""生产模块的稳定公共接口。

其他模块如需查询生产数据，请通过此文件中的函数调用，不要直接 import
本模块的 service/repository/models。

这里故意只返回不可变的轻量摘要对象，而不是 ORM 实例。这样调用方可以保存
自己的快照，同时生产模块内部表结构或业务服务的调整不会成为跨模块契约。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import IntermediateType, Product
from app.shared.sql import escape_like


@dataclass(frozen=True, slots=True)
class ProductBrief:
    """产品摘要，供其他模块做存在性校验和来源快照。"""

    id: uuid.UUID
    code: str | None
    name: str
    is_deleted: bool = False

    @property
    def product_code(self) -> str | None:
        """兼容生产模块原有字段命名。"""
        return self.code

    @property
    def product_name(self) -> str:
        """兼容生产模块原有字段命名。"""
        return self.name

    @property
    def is_active(self) -> bool:
        """跨模块统一的启用状态表达。"""
        return not self.is_deleted


@dataclass(frozen=True, slots=True)
class IntermediateTypeBrief:
    """生产中间体类型摘要（QA 物料映射使用类型级对象）。"""

    id: uuid.UUID
    code: str
    name: str
    category: str | None = None
    is_product: bool = False
    is_deleted: bool = False
    product_id: uuid.UUID | None = None

    @property
    def intermediate_type_code(self) -> str:
        return self.code

    @property
    def intermediate_type_name(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return not self.is_deleted


def _clean_keyword(keyword: str | None) -> str | None:
    """清理跨模块搜索关键词；纯空白按未传入处理。"""
    if keyword is None:
        return None
    value = keyword.strip()
    return value or None


def _normalize_ids(
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
) -> list[uuid.UUID]:
    """将 UUID/UUID 字符串选择器归一化，忽略无效值。"""
    if ids is None:
        return []
    values: Sequence[uuid.UUID | str]
    if isinstance(ids, (uuid.UUID, str)):
        values = [ids]
    else:
        values = ids
    result: list[uuid.UUID] = []
    for value in values:
        if isinstance(value, uuid.UUID):
            result.append(value)
            continue
        if isinstance(value, str):
            try:
                result.append(uuid.UUID(value))
            except ValueError:
                # 无效/未知 ID 与不存在记录统一按缺失处理，避免把原始字符串
                # 交给 asyncpg 的 UUID 参数转换器而产生 500。
                continue
    return result


def _briefs_in_input_order[T: ProductBrief | IntermediateTypeBrief](
    ids: Sequence[uuid.UUID],
    rows: list[T],
) -> list[T]:
    """按调用方传入的 ID 顺序返回摘要，并去掉重复 ID。

    对来源关联表单而言，稳定顺序比数据库默认返回顺序更可预测；不存在或
    已删除的 ID 会被省略，调用方可通过长度/ID 集合判断校验失败。
    """
    by_id = {row.id: row for row in rows}
    result: list[T] = []
    seen: set[uuid.UUID] = set()
    for item_id in ids:
        if item_id in seen:
            continue
        seen.add(item_id)
        row = by_id.get(item_id)
        if row is not None:
            result.append(row)
    return result


async def get_product_briefs(
    db: AsyncSession,
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
    *,
    include_deleted: bool = False,
) -> list[ProductBrief]:
    """按 ID 批量获取产品摘要。

    默认只返回未软删除产品；不存在的 ID 会从结果中省略。``include_deleted``
    仅用于历史快照核验，不改变默认跨模块读取口径。
    """
    normalized_ids = _normalize_ids(ids)
    if not normalized_ids:
        return []
    stmt = select(Product).where(Product.id.in_(normalized_ids))
    if not include_deleted:
        stmt = stmt.where(Product.is_deleted == False)  # noqa: E712
    rows = list((await db.execute(stmt)).scalars())
    briefs = [
        ProductBrief(
            id=row.id,
            code=row.product_code,
            name=row.product_name,
            is_deleted=bool(getattr(row, "is_deleted", False)),
        )
        for row in rows
    ]
    return _briefs_in_input_order(normalized_ids, briefs)


async def get_product_brief(
    db: AsyncSession,
    product_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> ProductBrief | None:
    """按 ID 获取单个产品摘要。"""
    rows = await get_product_briefs(
        db, [product_id], include_deleted=include_deleted,
    )
    return rows[0] if rows else None


async def list_products(
    db: AsyncSession,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    *,
    include_deleted: bool = False,
) -> tuple[list[ProductBrief], int]:
    """搜索/分页返回产品摘要及总数。

    关键词匹配产品编码或名称；分页参数会被钳制到最小值 1，避免跨模块调用
    因用户输入负数 offset。
    """
    page = max(page, 1)
    page_size = max(page_size, 1)
    value = _clean_keyword(keyword)

    filters = []
    if not include_deleted:
        filters.append(Product.is_deleted == False)  # noqa: E712
    if value:
        pattern = f"%{escape_like(value)}%"
        filters.append(
            or_(
                Product.product_code.ilike(pattern, escape="\\"),
                Product.product_name.ilike(pattern, escape="\\"),
            )
        )

    count_stmt = select(func.count(Product.id)).select_from(Product)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = select(Product)
    if filters:
        stmt = stmt.where(*filters)
    stmt = (
        stmt.order_by(Product.product_name, Product.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars())
    return [
        ProductBrief(
            id=row.id,
            code=row.product_code,
            name=row.product_name,
            is_deleted=bool(getattr(row, "is_deleted", False)),
        )
        for row in rows
    ], total


async def search_products(
    db: AsyncSession,
    keyword: str,
    *,
    page: int = 1,
    page_size: int = 20,
    include_deleted: bool = False,
) -> tuple[list[ProductBrief], int]:
    """``list_products`` 的语义化搜索别名。"""
    return await list_products(
        db,
        keyword=keyword,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
    )


async def get_intermediate_type_briefs(
    db: AsyncSession,
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
    *,
    include_deleted: bool = False,
) -> list[IntermediateTypeBrief]:
    """按 ID 批量获取中间体类型摘要（QA 物料只映射到类型级对象）。"""
    normalized_ids = _normalize_ids(ids)
    if not normalized_ids:
        return []
    stmt = select(IntermediateType).where(IntermediateType.id.in_(normalized_ids))
    if not include_deleted:
        stmt = stmt.where(IntermediateType.is_deleted == False)  # noqa: E712
    rows = list((await db.execute(stmt)).scalars())
    briefs = [
        IntermediateTypeBrief(
            id=row.id,
            code=row.code,
            name=row.name,
            category=row.category,
            is_product=bool(row.is_product),
            is_deleted=bool(getattr(row, "is_deleted", False)),
            product_id=row.product_id,
        )
        for row in rows
    ]
    return _briefs_in_input_order(normalized_ids, briefs)


async def get_intermediate_type_brief(
    db: AsyncSession,
    intermediate_type_id: uuid.UUID,
    *,
    include_deleted: bool = False,
) -> IntermediateTypeBrief | None:
    """按 ID 获取单个中间体类型摘要。"""
    rows = await get_intermediate_type_briefs(
        db,
        [intermediate_type_id],
        include_deleted=include_deleted,
    )
    return rows[0] if rows else None


async def list_intermediate_types(
    db: AsyncSession,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    *,
    include_deleted: bool = False,
) -> tuple[list[IntermediateTypeBrief], int]:
    """搜索/分页返回中间体类型摘要及总数。"""
    page = max(page, 1)
    page_size = max(page_size, 1)
    value = _clean_keyword(keyword)

    filters = []
    if not include_deleted:
        filters.append(IntermediateType.is_deleted == False)  # noqa: E712
    if value:
        pattern = f"%{escape_like(value)}%"
        filters.append(
            or_(
                IntermediateType.code.ilike(pattern, escape="\\"),
                IntermediateType.name.ilike(pattern, escape="\\"),
                IntermediateType.category.ilike(pattern, escape="\\"),
            )
        )

    count_stmt = select(func.count(IntermediateType.id)).select_from(
        IntermediateType
    )
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int((await db.execute(count_stmt)).scalar_one())

    stmt = select(IntermediateType)
    if filters:
        stmt = stmt.where(*filters)
    stmt = (
        stmt.order_by(IntermediateType.code, IntermediateType.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars())
    return [
        IntermediateTypeBrief(
            id=row.id,
            code=row.code,
            name=row.name,
            category=row.category,
            is_product=bool(row.is_product),
            is_deleted=bool(getattr(row, "is_deleted", False)),
            product_id=row.product_id,
        )
        for row in rows
    ], total


async def search_intermediate_types(
    db: AsyncSession,
    keyword: str,
    *,
    page: int = 1,
    page_size: int = 20,
    include_deleted: bool = False,
) -> tuple[list[IntermediateTypeBrief], int]:
    """``list_intermediate_types`` 的语义化搜索别名。"""
    return await list_intermediate_types(
        db,
        keyword=keyword,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
    )


# 兼容一些调用方使用 ``*_by_ids`` 的命名习惯；保留同一份实现和返回契约。
get_products_by_ids = get_product_briefs
get_intermediate_types_by_ids = get_intermediate_type_briefs


__all__ = [
    "ProductBrief",
    "IntermediateTypeBrief",
    "get_product_briefs",
    "get_product_brief",
    "get_products_by_ids",
    "list_products",
    "search_products",
    "get_intermediate_type_briefs",
    "get_intermediate_type_brief",
    "get_intermediate_types_by_ids",
    "list_intermediate_types",
    "search_intermediate_types",
]
