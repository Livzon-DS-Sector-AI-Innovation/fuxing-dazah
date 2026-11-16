"""COA 产品与客户标准配置：CRUD、项目全量替换（引用守卫）、标准删除守卫。

守卫口径：
- 产品/标准头：预检唯一 + SAVEPOINT 兜底转 409（apr/deviation 同模式）。
- 标准删除：已有出具报告引用 → 409（先处理报告）；删除时项目随之软删。
- 项目替换：不在载荷中的既有项目——被报告值引用的停用保留（is_active=false，
  历史值可解释），无引用的软删让号；载荷内 code 冲突 → 400。
- 项目 code 由名称归一化生成，标准内唯一；改名（替换更新）会同步重算——
  code 是 docx 导入匹配键，也是出具登记矩阵跨标准合并同名列的依据。
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.qa.models import (
    CoaProduct,
    CoaSourceType,
    CoaStandard,
    CoaStandardItem,
)
from app.modules.qa.repository import coa as repo
from app.modules.qa.schemas.coa import (
    CoaItemIn,
    CoaProductCreate,
    CoaProductUpdate,
    CoaStandardCreate,
    CoaStandardItemsReplace,
    CoaStandardUpdate,
)
from app.modules.qa.service.coa.common import (
    _actor_id,
    get_product_or_404,
    get_standard_or_404,
    item_dict,
    product_dict,
    standard_dict,
)
from app.modules.qa.service.coa.docx_parse import item_code
from app.platform.identity.models import User

# ───────────────────────── 产品 ─────────────────────────


async def list_products(
    db: AsyncSession, *, active_only: bool = False
) -> list[dict[str, Any]]:
    rows = await repo.list_products(db, active_only=active_only)
    counts = await repo.count_standards_by_product(db)
    return [product_dict(r, standard_count=counts.get(r.id, 0)) for r in rows]


async def create_product(
    db: AsyncSession, payload: CoaProductCreate, user: User | None
) -> dict[str, Any]:
    code = payload.code.strip().upper()
    if await repo.find_product_by_code(db, code):
        raise AppException(status_code=409, message=f"产品短码 {code} 已存在")
    if await repo.find_product_by_name(db, payload.name):
        raise AppException(status_code=409, message=f"产品名称 {payload.name} 已存在")
    row = CoaProduct(
        code=code,
        name=payload.name,
        name_en=payload.name_en,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise AppException(status_code=409, message="产品短码或名称已被占用") from exc
    return product_dict(row)


async def update_product(
    db: AsyncSession,
    product_id: uuid.UUID,
    payload: CoaProductUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await get_product_or_404(db, product_id)
    updates = payload.model_dump(exclude_unset=True)
    if "code" in updates:
        code = updates["code"].strip().upper()
        if code != row.code and await repo.find_product_by_code(
            db, code, exclude_id=row.id
        ):
            raise AppException(status_code=409, message=f"产品短码 {code} 已存在")
        updates["code"] = code
    if "name" in updates and updates["name"] != row.name:
        if await repo.find_product_by_name(db, updates["name"], exclude_id=row.id):
            raise AppException(
                status_code=409, message=f"产品名称 {updates['name']} 已存在"
            )
    for key, value in updates.items():
        setattr(row, key, value)
    row.updated_by = _actor_id(user)
    async with db.begin_nested():
        await db.flush()
    return product_dict(row)


# ───────────────────────── 客户标准 ─────────────────────────


async def list_standards(
    db: AsyncSession,
    *,
    product_id: uuid.UUID | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    rows = await repo.list_standards(db, product_id=product_id, active_only=active_only)
    item_counts = await repo.count_items_by_standard(db)
    report_counts = await repo.count_reports_by_standard(db)
    return [
        standard_dict(
            r,
            item_count=item_counts.get(r.id, 0),
            report_count=report_counts.get(r.id, 0),
        )
        for r in rows
    ]


async def get_standard_detail(
    db: AsyncSession, standard_id: uuid.UUID
) -> dict[str, Any]:
    row = await get_standard_or_404(db, standard_id)
    items = await repo.list_items(db, standard_id)  # 含停用（配置页可见全量）
    report_counts = await repo.count_reports_by_standard(db)
    return standard_dict(
        row,
        items=[item_dict(i) for i in items],
        report_count=report_counts.get(row.id, 0),
    )


async def create_standard(
    db: AsyncSession, payload: CoaStandardCreate, user: User | None
) -> dict[str, Any]:
    product = await get_product_or_404(db, uuid.UUID(payload.product_id))
    code = payload.code.strip()
    if await repo.find_standard_by_code(db, product.id, code):
        raise AppException(
            status_code=409, message=f"产品 {product.code} 下模板编号 {code} 已存在"
        )
    row = CoaStandard(
        product_id=product.id,
        code=code,
        name=payload.name,
        customer=payload.customer,
        market=payload.market,
        version=payload.version,
        is_active=payload.is_active,
        source=CoaSourceType.IMPORT.value
        if payload.raw_extract
        else CoaSourceType.MANUAL.value,
        raw_extract=payload.raw_extract,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
            await _insert_items(db, row.id, payload.items)
    except IntegrityError as exc:
        raise AppException(
            status_code=409, message="模板编号冲突，请刷新后重试"
        ) from exc
    return await get_standard_detail(db, row.id)


async def update_standard(
    db: AsyncSession,
    standard_id: uuid.UUID,
    payload: CoaStandardUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await get_standard_or_404(db, standard_id)
    updates = payload.model_dump(exclude_unset=True)
    if "code" in updates:
        code = updates["code"].strip()
        if code != row.code and await repo.find_standard_by_code(
            db, row.product_id, code, exclude_id=row.id
        ):
            raise AppException(status_code=409, message=f"模板编号 {code} 已存在")
        updates["code"] = code
    for key, value in updates.items():
        setattr(row, key, value)
    row.updated_by = _actor_id(user)
    async with db.begin_nested():
        await db.flush()
    return await get_standard_detail(db, standard_id)


async def delete_standard(
    db: AsyncSession, standard_id: uuid.UUID, user: User | None
) -> None:
    row = await get_standard_or_404(db, standard_id)
    report_counts = await repo.count_reports_by_standard(db)
    if report_counts.get(row.id, 0) > 0:
        raise AppException(
            status_code=409,
            message="该标准已有出具登记，不能删除；如需退役请停用",
        )
    # 项目随之软删让号（可删标准必无报告 → 项目无值引用，历史不受影响）
    actor = _actor_id(user)
    row.is_deleted = True
    row.updated_by = actor
    for item in await repo.list_items(db, row.id):
        item.is_deleted = True
        item.updated_by = actor
    async with db.begin_nested():
        await db.flush()


# ───────────────────────── 标准项目 ─────────────────────────


async def _insert_items(
    db: AsyncSession, standard_id: uuid.UUID, items: Sequence[CoaItemIn]
) -> list[CoaStandardItem]:
    """按载荷顺序落库；code 归一化生成 + 载荷内查重。"""
    seen_codes: set[str] = set()
    rows: list[CoaStandardItem] = []
    for idx, item in enumerate(items):
        code = item.code or item_code(item.name_cn, item.name_en)
        if code in seen_codes:
            raise AppException(
                status_code=400,
                message=f"项目 [{item.name_cn}] 与已有项目归一化后同码（{code}），请改名或合并",
            )
        seen_codes.add(code)
        row = CoaStandardItem(
            standard_id=standard_id,
            code=code,
            group_name=item.group_name,
            name_cn=item.name_cn,
            name_en=item.name_en,
            value_type=item.value_type,
            unit=item.unit,
            spec_text=item.spec_text,
            spec_min=item.spec_min,
            spec_max=item.spec_max,
            sort_order=item.sort_order if item.sort_order is not None else idx,
            is_active=item.is_active,
            remark=item.remark,
        )
        db.add(row)
        rows.append(row)
    if rows:
        await db.flush()
    return rows


async def replace_items(
    db: AsyncSession,
    standard_id: uuid.UUID,
    payload: CoaStandardItemsReplace,
    user: User | None,
) -> dict[str, Any]:
    """项目全量替换。

    载荷带 id=保留更新（值引用不断，code 缺省由当前中英文名重算=改名即同步
    匹配键）；不带 id=新建；既有项目不在载荷中：被值引用 → 停用保留，
    无引用 → 软删让号。
    """
    standard = await get_standard_or_404(db, standard_id)
    existing = await repo.list_items(db, standard_id)
    by_id = {r.id: r for r in existing}

    kept_ids: set[uuid.UUID] = set()
    seen_codes: set[str] = set()
    for idx, item in enumerate(payload.items):
        code = item.code or item_code(item.name_cn, item.name_en)
        if code in seen_codes:
            raise AppException(
                status_code=400,
                message=f"项目 [{item.name_cn}] 在载荷内重复（{code}）",
            )
        seen_codes.add(code)
        sort = item.sort_order if item.sort_order is not None else idx
        if item.id:
            row = by_id.get(uuid.UUID(item.id))
            if row is None:
                raise NotFoundException("标准项目", item.id)
            for key in (
                "group_name",
                "name_cn",
                "name_en",
                "value_type",
                "unit",
                "spec_text",
                "spec_min",
                "spec_max",
                "is_active",
                "remark",
            ):
                setattr(row, key, getattr(item, key))
            row.code = code  # 显式传 code 才覆盖，缺省由当前中英文名重算
            row.sort_order = sort
            row.updated_by = _actor_id(user)
            kept_ids.add(row.id)
        else:
            db.add(
                CoaStandardItem(
                    standard_id=standard_id,
                    code=code,
                    group_name=item.group_name,
                    name_cn=item.name_cn,
                    name_en=item.name_en,
                    value_type=item.value_type,
                    unit=item.unit,
                    spec_text=item.spec_text,
                    spec_min=item.spec_min,
                    spec_max=item.spec_max,
                    sort_order=sort,
                    is_active=item.is_active,
                    remark=item.remark,
                    created_by=_actor_id(user),
                    updated_by=_actor_id(user),
                )
            )

    # 不在载荷中的既有项目：引用守卫
    removed = [r for r in existing if r.id not in kept_ids]
    if removed:
        referenced = await repo.item_ids_with_values(db, [r.id for r in removed])
        for r in removed:
            if r.id in referenced:
                r.is_active = False
                r.updated_by = _actor_id(user)
            else:
                r.is_deleted = True
                r.updated_by = _actor_id(user)

    standard.updated_by = _actor_id(user)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise AppException(
            status_code=409, message="项目编号冲突（同码项目已存在），请检查重复项"
        ) from exc
    return await get_standard_detail(db, standard_id)
