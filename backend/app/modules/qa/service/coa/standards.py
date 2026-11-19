"""COA 产品与客户标准配置：CRUD、项目全量替换（软删让号）、标准删除守卫。

守卫口径：
- 产品/标准头：预检唯一 + SAVEPOINT 兜底转 409（apr/deviation 同模式）。
- 标准删除：已有出具报告引用 → 409（先处理报告）；删除时项目随之软删。
- 项目替换：不在载荷中的既有项目统一软删让号（值行 FK 有效，历史值可解释）；
  载荷内 code 冲突 → 400。项目必然启用（无停用态）。
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
    CoaProductFieldIn,
    CoaProductFieldsReplace,
    CoaProductUpdate,
    CoaStandardCreate,
    CoaStandardFieldsReplace,
    CoaStandardItemsReplace,
    CoaStandardUpdate,
)
from app.modules.qa.service.coa.common import (
    _actor_id,
    builtin_key_of,
    get_product_or_404,
    get_standard_or_404,
    item_dict,
    merge_builtin_fields,
    product_dict,
    product_field_dict,
    standard_dict,
    standard_field_dict,
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
    # None 直通 = 不改（schema 口径）：不可空字段的显式 null 直接忽略，避免写 NULL
    updates = {
        k: v
        for k, v in updates.items()
        if v is not None or k in {"name_en", "remark"}
    }
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


# ───────────────────────── 批次信息字段配置 ─────────────────────────
# 产品默认 + 标准覆盖（稀疏）：生效集 = 标准覆盖 ?? 产品默认。


def _field_rows(
    fields: Sequence[CoaProductFieldIn], user: User | None
) -> list[dict[str, Any]]:
    """字段载荷 → ORM 行构造（内置键拒绝 400；key 查重 400；排序缺省按载荷顺序）。"""
    seen_keys: set[str] = set()
    rows: list[dict[str, Any]] = []
    for idx, field in enumerate(fields):
        builtin_key = builtin_key_of(field.key) or builtin_key_of(field.label_cn)
        if builtin_key is not None:
            raise AppException(
                status_code=400,
                message=f"字段 [{field.key}] 与内置字段 {builtin_key} 重复："
                "品名/批号/流水号恒定存在且必填，无需配置",
            )
        if field.key in seen_keys:
            raise AppException(
                status_code=400,
                message=f"字段键 [{field.key}] 在载荷内重复",
            )
        seen_keys.add(field.key)
        rows.append(
            {
                "key": field.key,
                "label_cn": field.label_cn,
                "label_en": field.label_en,
                "field_type": field.field_type,
                "sort_order": field.sort_order if field.sort_order is not None else idx,
                "created_by": _actor_id(user),
                "updated_by": _actor_id(user),
            }
        )
    return rows


def _fields_signature(fields: Sequence[Any]) -> list[tuple[str, str, str, str]]:
    """字段集对比签名：key/中英标签/类型，顺序无关（排序只影响展示）。

    元素兼容三种形态：CoaProductFieldIn 载荷 / ORM 行 / dict。
    """

    def cell(field: Any) -> tuple[str, str, str, str]:
        key = field["key"] if isinstance(field, dict) else field.key
        cn = field["label_cn"] if isinstance(field, dict) else field.label_cn
        en = field["label_en"] if isinstance(field, dict) else field.label_en
        ftype = field["field_type"] if isinstance(field, dict) else field.field_type
        return (key, cn, en or "", ftype)

    return sorted(cell(f) for f in fields)


async def list_product_fields(
    db: AsyncSession, product_id: uuid.UUID
) -> list[dict[str, Any]]:
    await get_product_or_404(db, product_id)
    rows = [product_field_dict(r) for r in await repo.list_product_fields(db, product_id)]
    return merge_builtin_fields(rows)


async def replace_product_fields(
    db: AsyncSession,
    product_id: uuid.UUID,
    payload: CoaProductFieldsReplace,
    user: User | None,
) -> list[dict[str, Any]]:
    """产品默认字段全量替换（硬删+重插）；并发唯一冲突兜底 409。"""
    await get_product_or_404(db, product_id)
    rows = _field_rows(payload.fields, user)
    try:
        async with db.begin_nested():
            await repo.replace_product_fields(db, product_id, rows)
    except IntegrityError as exc:
        raise AppException(
            status_code=409, message="字段配置写入冲突，请刷新后重试"
        ) from exc
    refreshed = await repo.list_product_fields(db, product_id)
    return merge_builtin_fields([product_field_dict(r) for r in refreshed])


async def resolve_standard_fields(
    db: AsyncSession, standard_id: uuid.UUID
) -> tuple[list[dict[str, Any]], bool]:
    """生效字段集 = 内置 3 字段置顶 +（标准覆盖 ?? 产品默认）。

    覆盖与否看标准上的 batch_fields_overridden 标志，而不是「有没有行」：
    显式保存的空自定义集也是覆盖（不回落产品默认）。
    返回 (字段列表, 是否自定义覆盖)；覆盖行不含内置键（写路径已拒绝）。
    """
    standard = await get_standard_or_404(db, standard_id)
    if standard.batch_fields_overridden:
        overrides = await repo.list_standard_fields(db, standard_id)
        return merge_builtin_fields([standard_field_dict(r) for r in overrides]), True
    defaults = await repo.list_product_fields(db, standard.product_id)
    return merge_builtin_fields([product_field_dict(r) for r in defaults]), False


async def replace_standard_fields(
    db: AsyncSession,
    standard_id: uuid.UUID,
    payload: CoaStandardFieldsReplace,
    user: User | None,
) -> dict[str, Any]:
    """标准字段覆盖全量替换（写覆盖=与产品默认解耦）。

    空列表也是有效的自定义集（只保留内置 3 字段），并置覆盖标志。
    """
    standard = await get_standard_or_404(db, standard_id)
    rows = _field_rows(payload.fields, user)
    try:
        async with db.begin_nested():
            await repo.replace_standard_fields(db, standard_id, rows)
            standard.batch_fields_overridden = True
    except IntegrityError as exc:
        raise AppException(
            status_code=409, message="字段配置写入冲突，请刷新后重试"
        ) from exc
    fields, _custom = await resolve_standard_fields(db, standard_id)
    return {"batch_fields": fields, "batch_fields_custom": True}


async def restore_standard_fields(
    db: AsyncSession, standard_id: uuid.UUID
) -> dict[str, Any]:
    """恢复产品默认=删标准覆盖并清覆盖标志。"""
    standard = await get_standard_or_404(db, standard_id)
    async with db.begin_nested():
        await repo.delete_standard_fields(db, standard_id)
        standard.batch_fields_overridden = False
    fields, _custom = await resolve_standard_fields(db, standard_id)
    return {"batch_fields": fields, "batch_fields_custom": False}


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
    fields, custom = await resolve_standard_fields(db, standard_id)
    # 产品默认一并返回：前端做行级差异标注（新增/修改/移除）；内置字段两侧恒同
    defaults = await repo.list_product_fields(db, row.product_id)
    data = standard_dict(
        row,
        items=[item_dict(i) for i in items],
        report_count=report_counts.get(row.id, 0),
    )
    data["batch_fields"] = fields
    data["batch_fields_custom"] = custom
    data["product_fields"] = merge_builtin_fields(
        [product_field_dict(d) for d in defaults]
    )
    return data


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
            # 批次字段：None=沿用产品默认；显式列表与默认一致不落覆盖，
            # 有差异（含空列表=只保留内置字段）才落标准级覆盖（稀疏）
            if payload.batch_fields is not None:
                defaults = await repo.list_product_fields(db, product.id)
                if _fields_signature(payload.batch_fields) != _fields_signature(
                    defaults
                ):
                    await repo.replace_standard_fields(
                        db, row.id, _field_rows(payload.batch_fields, user)
                    )
                    row.batch_fields_overridden = True
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
    # None 直通 = 不改（schema 口径）：不可空字段的显式 null 直接忽略，避免写 NULL
    updates = {
        k: v
        for k, v in updates.items()
        if v is not None or k in {"customer", "market", "version", "remark"}
    }
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
    # 项目随之软删让号（可删标准必无报告 → 项目无值引用，历史不受影响）；
    # 字段覆盖硬删（配置非审计，防孤儿行）
    actor = _actor_id(user)
    row.is_deleted = True
    row.updated_by = actor
    for item in await repo.list_items(db, row.id):
        item.is_deleted = True
        item.updated_by = actor
    async with db.begin_nested():
        await repo.delete_standard_fields(db, row.id)
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
            default_value=item.default_value,
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
    匹配键）；不带 id=新建；既有项目不在载荷中 → 软删让号（值行 FK 有效，
    历史值可解释）。
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
                "default_value",
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
                    default_value=item.default_value,
                    remark=item.remark,
                    created_by=_actor_id(user),
                    updated_by=_actor_id(user),
                )
            )

    # 不在载荷中的既有项目：软删让号（历史值行仍引用该行，FK 有效可解释）
    for r in existing:
        if r.id not in kept_ids:
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
