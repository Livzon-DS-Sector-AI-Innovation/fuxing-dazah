"""QA 年度产品审核（APR）业务编排：模板配置 / 批次录入 / 趋势 / 汇总 / 年度锁定。

统计量（均值/极值/±3σ）一律本层查询时计算；数值列允许录入文字结果
（未检出等），原始记录保留文字，统计口径由列定义 nd_policy 决定。
值保存为全量替换（硬删+插入）。
锁定口径：产品×年度 locked 后拦截批次与值的全部写操作；列定义的限度
（spec/oot）在锁定年度已有录入值时同样冻结（防改写历史 OOS/OOT 判定），
其余模板字段（名称/单位/排序等）不随年度锁定。
"""

from __future__ import annotations

import statistics
import uuid
from typing import Any
from unicodedata import normalize as _nfkc

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.qa.models import (
    AprAnnualReview,
    AprBatch,
    AprItem,
    AprNdPolicy,
    AprProduct,
    AprSection,
    AprValueType,
)
from app.modules.qa.repository import apr as repo
from app.modules.qa.schemas.apr import (
    AprBatchCreate,
    AprBatchUpdate,
    AprBatchValuesIn,
    AprItemBase,
    AprItemCreate,
    AprItemsBulkCreate,
    AprItemUpdate,
    AprProductCreate,
    AprProductUpdate,
    AprSectionCreate,
    AprSectionUpdate,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

# 趋势/汇总统计最少样本数：低于该值不给 ±3σ（单点无意义）。
MIN_STATS_SAMPLES = 2

# 列定义的限度字段：改写历史 OOS/OOT 判定，锁定年度有值时冻结。
_LIMIT_FIELDS = ("spec_min", "spec_max", "oot_min", "oot_max")


# ───────────────────────── 通用辅助 ─────────────────────────


def _actor_id(user: User | None) -> uuid.UUID | None:
    return user.id if user is not None else None


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    user: User | None,
    resource_type: str,
    resource_id: uuid.UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    await record_audit_log(
        db,
        action=action,
        user=user,
        user_id=_actor_id(user),
        resource_type=f"qa.{resource_type}",
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        extra=extra,
    )


async def _get_product_or_404(db: AsyncSession, product_id: uuid.UUID) -> AprProduct:
    product = await repo.get_product(db, product_id)
    if product is None:
        raise NotFoundException("APR 产品", str(product_id))
    return product


async def _get_section_or_404(db: AsyncSession, section_id: uuid.UUID) -> AprSection:
    section = await repo.get_section(db, section_id)
    if section is None:
        raise NotFoundException("模板段", str(section_id))
    return section


async def _get_batch_or_404(db: AsyncSession, batch_id: uuid.UUID) -> AprBatch:
    batch = await repo.get_batch(db, batch_id)
    if batch is None:
        raise NotFoundException("批次", str(batch_id))
    return batch


async def _get_item_or_404(db: AsyncSession, item_id: uuid.UUID) -> AprItem:
    item = await repo.get_item(db, item_id)
    if item is None:
        raise NotFoundException("列定义", str(item_id))
    return item


async def _ensure_year_open(db: AsyncSession, product_id: uuid.UUID, year: int) -> None:
    """产品×年度已锁定则拒绝写操作。

    行已存在时对锁定行加 FOR UPDATE：与 set_annual_review_lock 的读-改
    串行化，堵住「写入方读到 open → 锁定方提交 locked → 写入方提交」的
    交错（deviation 状态流转同模式）。行不存在时无行可锁，窗口收窄为
    「锁定行首次创建」的瞬间，内部系统可接受。
    """
    review = await repo.get_annual_review(db, product_id, year, for_update=True)
    if review is not None and review.status == "locked":
        raise AppException(
            status_code=422,
            message=f"{year} 年度已锁定（年终定稿），如需修改请先解锁。",
        )


def _validate_limit_pairs(
    *,
    spec_min: float | None,
    spec_max: float | None,
    oot_min: float | None,
    oot_max: float | None,
) -> None:
    """标准/预警区间下限不得大于上限（与 DB CheckConstraint 同口径）。"""
    if spec_min is not None and spec_max is not None and spec_min > spec_max:
        raise AppException(
            status_code=422, message="标准下限 spec_min 不能大于标准上限 spec_max。"
        )
    if oot_min is not None and oot_max is not None and oot_min > oot_max:
        raise AppException(
            status_code=422, message="预警下限 oot_min 不能大于预警上限 oot_max。"
        )


# ───────────────────────── 产品 ─────────────────────────


def _product_dict(
    row: AprProduct,
    *,
    section_count: int | None = None,
    item_count: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "name_en": row.name_en,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
        "remark": row.remark,
    }
    if section_count is not None:
        data["section_count"] = section_count
    if item_count is not None:
        data["item_count"] = item_count
    return data


def _constraint_name(exc: IntegrityError) -> str:
    """取撞到的唯一索引名；取不到时退回异常文本（asyncpg 文本里也带约束名）。"""
    orig = getattr(exc, "orig", None)
    return str(getattr(orig, "constraint_name", None) or orig or exc)


def _product_conflict_message(exc: IntegrityError, *, code: str, name: str) -> str:
    """把产品唯一索引冲突翻译成可读的 409 文案。

    短码与名称各有部分唯一索引，预检后并发仍可能撞索引；按撞到的约束名
    分流，识别不出时给通用提示（不吞掉异常，仍以 409 返回）。
    """
    constraint = _constraint_name(exc)
    if "apr_products_name" in constraint:
        return f"产品名称 {name} 已存在"
    if "apr_products_code" in constraint:
        return f"产品短码 {code} 已存在"
    return "产品短码或产品名称已存在"


async def _ensure_product_unique(
    db: AsyncSession,
    *,
    code: str | None = None,
    name: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """产品短码/名称预检；None 表示该字段不参与校验（编辑未改动的字段）。"""
    if code is not None:
        if await repo.find_product_by_code(db, code, exclude_id=exclude_id):
            raise AppException(status_code=409, message=f"产品短码 {code} 已存在")
    if name is not None:
        if await repo.find_product_by_name(db, name, exclude_id=exclude_id):
            raise AppException(status_code=409, message=f"产品名称 {name} 已存在")


async def list_products(
    db: AsyncSession, *, active_only: bool = False
) -> list[dict[str, Any]]:
    rows = await repo.list_products(db, active_only=active_only)
    counts = await repo.count_sections_and_items_by_product(db)
    return [
        _product_dict(
            r,
            section_count=counts.get(r.id, (0, 0))[0],
            item_count=counts.get(r.id, (0, 0))[1],
        )
        for r in rows
    ]


async def create_product(
    db: AsyncSession, payload: AprProductCreate, user: User | None
) -> dict[str, Any]:
    await _ensure_product_unique(db, code=payload.code, name=payload.name)
    row = AprProduct(
        code=payload.code,
        name=payload.name,
        name_en=payload.name_en,
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    try:
        # 预检后仍可能与他人并发撞 uq_qa_apr_products_code / _name，
        # 只回滚到 SAVEPOINT 转 409（deviation 同模式）。
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise AppException(
            status_code=409,
            message=_product_conflict_message(
                exc, code=payload.code, name=payload.name
            ),
        ) from None
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="apr_product",
        resource_id=row.id,
        new_value=_product_dict(row),
    )
    return _product_dict(row)


async def update_product(
    db: AsyncSession,
    product_id: uuid.UUID,
    payload: AprProductUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await _get_product_or_404(db, product_id)
    old = _product_dict(row)
    data = payload.model_dump(exclude_unset=True)
    await _ensure_product_unique(
        db,
        code=data["code"] if data.get("code") not in (None, row.code) else None,
        name=data["name"] if data.get("name") not in (None, row.name) else None,
        exclude_id=row.id,
    )
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = _actor_id(user)
    new_code = data.get("code") or row.code
    new_name = data.get("name") or row.name
    try:
        # 并发下仍可能撞唯一索引，只回滚到 SAVEPOINT 转 409。
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise AppException(
            status_code=409,
            message=_product_conflict_message(exc, code=new_code, name=new_name),
        ) from None
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="apr_product",
        resource_id=row.id,
        old_value=old,
        new_value=_product_dict(row),
    )
    return _product_dict(row)


async def delete_product(
    db: AsyncSession, product_id: uuid.UUID, user: User | None
) -> None:
    row = await _get_product_or_404(db, product_id)
    if await repo.count_sections_of_product(db, product_id) > 0:
        raise AppException(
            status_code=409,
            message="该产品已配置模板段，请先删除全部模板段后再删除产品。",
        )
    row.is_deleted = True
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="delete",
        user=user,
        resource_type="apr_product",
        resource_id=row.id,
        old_value=_product_dict(row),
    )


# ───────────────────────── 段 ─────────────────────────


def _section_conflict_message(exc: IntegrityError, *, name: str) -> str:
    """段名唯一索引冲突 → 409 文案（同产品下段名唯一）。"""
    if "apr_sections_product_name" in _constraint_name(exc):
        return f"段名 {name} 在该产品下已存在"
    return "段名在该产品下已存在"


async def _ensure_section_name_unique(
    db: AsyncSession,
    product_id: uuid.UUID,
    name: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if await repo.find_section_by_name(db, product_id, name, exclude_id=exclude_id):
        raise AppException(
            status_code=409, message=f"段名 {name} 在该产品下已存在"
        )


def _section_dict(
    row: AprSection, *, items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "name": row.name,
        "data_kind": row.data_kind,
        "market": row.market,
        "stage": row.stage,
        "multi_row": row.multi_row,
        "sort_order": row.sort_order,
        "remark": row.remark,
    }
    if items is not None:
        data["items"] = items
    return data


async def list_sections(
    db: AsyncSession, product_id: uuid.UUID, *, with_items: bool = True
) -> list[dict[str, Any]]:
    rows = await repo.list_sections(db, product_id)
    result = []
    for r in rows:
        items = None
        if with_items:
            items = [
                _item_dict(i)
                for i in await repo.list_items(db, r.id, active_only=False)
            ]
        result.append(_section_dict(r, items=items))
    return result


async def create_section(
    db: AsyncSession, payload: AprSectionCreate, user: User | None
) -> dict[str, Any]:
    await _get_product_or_404(db, payload.product_id)
    await _ensure_section_name_unique(db, payload.product_id, payload.name)
    row = AprSection(
        product_id=payload.product_id,
        name=payload.name,
        data_kind=payload.data_kind.value,
        market=payload.market,
        stage=payload.stage,
        multi_row=payload.multi_row,
        sort_order=payload.sort_order,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    try:
        # 预检后并发仍可能撞 uq_qa_apr_sections_product_name，转 409。
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError as exc:
        raise AppException(
            status_code=409,
            message=_section_conflict_message(exc, name=payload.name),
        ) from None
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="apr_section",
        resource_id=row.id,
        new_value=_section_dict(row),
    )
    return _section_dict(row)


async def update_section(
    db: AsyncSession,
    section_id: uuid.UUID,
    payload: AprSectionUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await _get_section_or_404(db, section_id)
    old = _section_dict(row)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") not in (None, row.name):
        await _ensure_section_name_unique(
            db, row.product_id, data["name"], exclude_id=row.id
        )
    # data_kind 序列化为枚举值落库
    if "data_kind" in data and data["data_kind"] is not None:
        data["data_kind"] = data["data_kind"].value
        # 数据类型决定列在汇总里的分组口径，段内已有列或批次后不允许再改，
        # 否则同一批数据会在「生产数据 / 检验结果」之间漂移。
        if data["data_kind"] != row.data_kind:
            item_count = len(await repo.list_items(db, section_id))
            batch_count = await repo.count_batches_of_section(db, section_id)
            if item_count or batch_count:
                existing: list[str] = []
                if item_count:
                    existing.append(f"{item_count} 个列定义")
                if batch_count:
                    existing.append(f"{batch_count} 条批次数据")
                raise AppException(
                    status_code=409,
                    message=(
                        f"该段已有 {'、'.join(existing)}，不能修改数据类型；"
                        "请新建模板段，或先清空列定义与批次。"
                    ),
                )
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = _actor_id(user)
    try:
        # 并发下仍可能撞段名唯一索引，只回滚到 SAVEPOINT 转 409。
        async with db.begin_nested():
            await db.flush()
    except IntegrityError as exc:
        raise AppException(
            status_code=409,
            message=_section_conflict_message(
                exc, name=data.get("name") or row.name
            ),
        ) from None
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="apr_section",
        resource_id=row.id,
        old_value=old,
        new_value=_section_dict(row),
    )
    return _section_dict(row)


async def delete_section(
    db: AsyncSession, section_id: uuid.UUID, user: User | None
) -> None:
    row = await _get_section_or_404(db, section_id)
    if await repo.count_batches_of_section(db, section_id) > 0:
        raise AppException(
            status_code=409,
            message="该段已登记批次数据，不能删除；可改为停用列定义保留历史。",
        )
    # 级联软删段下列定义（无批次即无值）。
    for item in await repo.list_items(db, section_id):
        item.is_deleted = True
        item.updated_by = _actor_id(user)
    row.is_deleted = True
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="delete",
        user=user,
        resource_type="apr_section",
        resource_id=row.id,
        old_value=_section_dict(row),
    )


# ───────────────────────── 列定义 ─────────────────────────


def _item_dict(row: AprItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "section_id": str(row.section_id),
        "code": row.code,
        "group_name": row.group_name,
        "category": row.category,
        "name_cn": row.name_cn,
        "name_en": row.name_en,
        "value_type": row.value_type,
        "unit": row.unit,
        "spec_text": row.spec_text,
        "spec_min": row.spec_min,
        "spec_max": row.spec_max,
        "oot_min": row.oot_min,
        "oot_max": row.oot_max,
        "nd_policy": row.nd_policy,
        "quick_values": list(row.quick_values or []),
        "trend_enabled": row.trend_enabled,
        "required": row.required,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
        "remark": row.remark,
    }


async def _generate_item_code(db: AsyncSession, section_id: uuid.UUID) -> str:
    """code 未传时生成段内唯一短码。"""
    while True:
        code = f"it_{uuid.uuid4().hex[:8]}"
        if await repo.find_item_by_code(db, section_id, code) is None:
            return code


def _item_columns(payload: AprItemBase, code: str, sort_order: int) -> dict[str, Any]:
    """把列定义入参摊平成 AprItem 字段（不含段与审计字段）。"""
    return {
        "code": code,
        "group_name": payload.group_name,
        "category": payload.category.value,
        "name_cn": payload.name_cn,
        "name_en": payload.name_en,
        "value_type": payload.value_type.value,
        "unit": payload.unit,
        "spec_text": payload.spec_text,
        "spec_min": payload.spec_min,
        "spec_max": payload.spec_max,
        "oot_min": payload.oot_min,
        "oot_max": payload.oot_max,
        "nd_policy": payload.nd_policy.value,
        "quick_values": list(payload.quick_values or []),
        "trend_enabled": payload.trend_enabled,
        "required": payload.required,
        "sort_order": sort_order,
        "remark": payload.remark,
    }


async def create_item(
    db: AsyncSession, payload: AprItemCreate, user: User | None
) -> dict[str, Any]:
    await _get_section_or_404(db, payload.section_id)
    code = payload.code
    if code:
        if await repo.find_item_by_code(db, payload.section_id, code) is not None:
            raise AppException(status_code=409, message=f"列编码 {code} 在该段内已存在")
    else:
        code = await _generate_item_code(db, payload.section_id)
    # 未显式给顺序时追加到段尾，避免新建列全部挤在 sort_order=0/10
    sort_order = (
        payload.sort_order
        if payload.sort_order is not None
        else await repo.max_sort_order(db, payload.section_id) + 10
    )
    row = AprItem(
        section_id=payload.section_id,
        **_item_columns(payload, code, sort_order),
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(row)
    await db.flush()
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="apr_item",
        resource_id=row.id,
        new_value=_item_dict(row),
    )
    return _item_dict(row)


async def bulk_create_items(
    db: AsyncSession,
    section_id: uuid.UUID,
    payload: AprItemsBulkCreate,
    user: User | None,
) -> dict[str, Any]:
    """从 Excel 粘贴的列定义一次性建好：段内编码查重、顺序依次追加到段尾。

    任何一行的编码重复都会整体拒绝（不半截成功），便于用户改完再提交。
    """
    await _get_section_or_404(db, section_id)
    taken = await repo.list_item_codes(db, section_id)
    sort_order = await repo.max_sort_order(db, section_id)

    seen: set[str] = set()
    for index, draft in enumerate(payload.items, start=1):
        code = draft.code
        if not code:
            continue
        if code in taken or code in seen:
            raise AppException(
                status_code=409,
                message=f"第 {index} 行（{draft.name_cn}）列编码 {code} 在该段内已存在",
            )
        seen.add(code)

    rows: list[AprItem] = []
    for draft in payload.items:
        code = draft.code or await _generate_item_code(db, section_id)
        while code in taken:
            code = await _generate_item_code(db, section_id)
        taken.add(code)
        sort_order += 10
        row = AprItem(
            section_id=section_id,
            **_item_columns(draft, code, sort_order),
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(row)
        rows.append(row)

    await db.flush()
    await _audit(
        db,
        action="bulk_create",
        user=user,
        resource_type="apr_item",
        resource_id=section_id,
        new_value={
            "section_id": str(section_id),
            "count": len(rows),
            "codes": [row.code for row in rows],
        },
    )
    return {"section_id": str(section_id), "count": len(rows), "items": [_item_dict(row) for row in rows]}


async def update_item(
    db: AsyncSession,
    item_id: uuid.UUID,
    payload: AprItemUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await _get_item_or_404(db, item_id)
    old = _item_dict(row)
    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"] and data["code"] != row.code:
        existing = await repo.find_item_by_code(db, row.section_id, data["code"])
        if existing is not None and existing.id != row.id:
            raise AppException(
                status_code=409, message=f"列编码 {data['code']} 在该段内已存在"
            )
    if "category" in data and data["category"] is not None:
        data["category"] = data["category"].value
    if "nd_policy" in data and data["nd_policy"] is not None:
        data["nd_policy"] = data["nd_policy"].value
    if "value_type" in data and data["value_type"] is not None:
        new_type = data["value_type"]
        if new_type != row.value_type and await repo.has_numeric_values(db, item_id):
            raise AppException(
                status_code=422,
                message="该项已录入数值，不能改为文字型；请新建列定义。",
            )
        data["value_type"] = (
            new_type.value if isinstance(new_type, AprValueType) else new_type
        )
    # 限度（spec/oot）改写历史值的 OOS/OOT 判定：该列在已锁定年度已有
    # 录入值时冻结限度，改名/单位/排序等其余字段不受影响。
    touched_limits = {
        field for field in _LIMIT_FIELDS
        if field in data and data[field] != getattr(row, field)
    }
    if touched_limits and await repo.count_values_in_locked_years(db, item_id):
        raise AppException(
            status_code=422,
            message=(
                "该列在已锁定年度有录入值，不能修改标准/预警限度"
                "（会改写历史 OOS/OOT 判定）；请先解锁相关年度。"
            ),
        )
    # PATCH 只带单边限度时 schema 层校验不到，合并现值后兜底一次，
    # 避免落库时撞 CheckConstraint 变 500。
    _validate_limit_pairs(
        spec_min=data.get("spec_min", row.spec_min),
        spec_max=data.get("spec_max", row.spec_max),
        oot_min=data.get("oot_min", row.oot_min),
        oot_max=data.get("oot_max", row.oot_max),
    )
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="apr_item",
        resource_id=row.id,
        old_value=old,
        new_value=_item_dict(row),
    )
    return _item_dict(row)


async def delete_item(
    db: AsyncSession, item_id: uuid.UUID, user: User | None
) -> dict[str, Any]:
    """有历史值时转为停用（保历史可解释），无值时软删。"""
    row = await _get_item_or_404(db, item_id)
    if await repo.count_values_of_item(db, item_id) > 0:
        row.is_active = False
        row.updated_by = _actor_id(user)
        await db.flush()
        await _audit(
            db,
            action="deactivate",
            user=user,
            resource_type="apr_item",
            resource_id=row.id,
            old_value={"is_active": True},
            new_value={"is_active": False},
        )
        return _item_dict(row)
    row.is_deleted = True
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="delete",
        user=user,
        resource_type="apr_item",
        resource_id=row.id,
        old_value=_item_dict(row),
    )
    return _item_dict(row)


# ───────────────────────── 模板复制 ─────────────────────────


async def copy_template(
    db: AsyncSession,
    product_id: uuid.UUID,
    source_product_id: uuid.UUID,
    user: User | None,
) -> dict[str, Any]:
    """把源产品的段+列定义整树复制到目标产品（同产品线快速建模板）。"""
    await _get_product_or_404(db, product_id)
    if product_id == source_product_id:
        raise AppException(status_code=422, message="源产品与目标产品不能相同")
    if await repo.count_sections_of_product(db, product_id) > 0:
        raise AppException(
            status_code=409, message="目标产品已有模板段，不能覆盖式复制。"
        )
    source = await _get_product_or_404(db, source_product_id)
    source_sections = await repo.list_sections(db, source_product_id)
    if not source_sections:
        raise AppException(
            status_code=422, message=f"源产品 {source.name} 没有可复制的模板段。"
        )
    actor = _actor_id(user)
    copied_sections = 0
    copied_items = 0
    for s in source_sections:
        new_section = AprSection(
            product_id=product_id,
            name=s.name,
            data_kind=s.data_kind,
            market=s.market,
            stage=s.stage,
            multi_row=s.multi_row,
            sort_order=s.sort_order,
            remark=s.remark,
            created_by=actor,
            updated_by=actor,
        )
        db.add(new_section)
        await db.flush()
        copied_sections += 1
        for i in await repo.list_items(db, s.id):
            db.add(
                AprItem(
                    section_id=new_section.id,
                    code=i.code,
                    group_name=i.group_name,
                    category=i.category,
                    name_cn=i.name_cn,
                    name_en=i.name_en,
                    value_type=i.value_type,
                    unit=i.unit,
                    spec_text=i.spec_text,
                    spec_min=i.spec_min,
                    spec_max=i.spec_max,
                    oot_min=i.oot_min,
                    oot_max=i.oot_max,
                    nd_policy=i.nd_policy,
                    quick_values=list(i.quick_values or []),
                    trend_enabled=i.trend_enabled,
                    required=i.required,
                    is_active=i.is_active,
                    sort_order=i.sort_order,
                    remark=i.remark,
                    created_by=actor,
                    updated_by=actor,
                )
            )
            copied_items += 1
    await db.flush()
    await _audit(
        db,
        action="copy_template",
        user=user,
        resource_type="apr_product",
        resource_id=product_id,
        extra={
            "source_product_id": str(source_product_id),
            "sections": copied_sections,
            "items": copied_items,
        },
    )
    return {
        "product_id": str(product_id),
        "source_product_id": str(source_product_id),
        "sections": copied_sections,
        "items": copied_items,
    }


# ───────────────────────── 批次 ─────────────────────────


def _batch_dict(row: AprBatch) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "section_id": str(row.section_id),
        "year": row.year,
        "batch_no": row.batch_no,
        "seq": row.seq,
        "parent_batch_id": (
            str(row.parent_batch_id) if row.parent_batch_id is not None else None
        ),
        "remark": row.remark,
    }


async def list_batches(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    year: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await repo.list_batches(
        db,
        section_id=section_id,
        year=year,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return [_batch_dict(r) for r in rows], total


async def create_batch(
    db: AsyncSession, payload: AprBatchCreate, user: User | None
) -> dict[str, Any]:
    section = await _get_section_or_404(db, payload.section_id)
    await _ensure_year_open(db, section.product_id, payload.year)
    if (
        await repo.find_batch(db, payload.section_id, payload.year, payload.batch_no)
        is not None
    ):
        raise AppException(
            status_code=409,
            message=f"批号 {payload.batch_no} 在该段 {payload.year} 年度已登记",
        )
    row = AprBatch(
        product_id=section.product_id,
        section_id=payload.section_id,
        year=payload.year,
        batch_no=payload.batch_no,
        seq=payload.seq,
        parent_batch_id=payload.parent_batch_id,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    try:
        # 预检后仍可能与他人并发撞唯一索引（uq_qa_apr_batches_section_year_no），
        # 只回滚到 SAVEPOINT 转 409，不冒泡成 500（deviation 同模式）。
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise AppException(
            status_code=409,
            message=f"批号 {payload.batch_no} 在该段 {payload.year} 年度已登记",
        ) from None
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="apr_batch",
        resource_id=row.id,
        new_value=_batch_dict(row),
    )
    return _batch_dict(row)


async def update_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    payload: AprBatchUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await _get_batch_or_404(db, batch_id)
    await _ensure_year_open(db, row.product_id, row.year)
    old = _batch_dict(row)
    data = payload.model_dump(exclude_unset=True)
    new_year = data.get("year", row.year)
    new_no = data.get("batch_no", row.batch_no)
    # 改年度即迁移批次（连带其值）：旧年度开放不代表目标年度开放，
    # 必须按目标年度再校验锁定，否则批次可整体迁入已冻结年度。
    if new_year != row.year:
        await _ensure_year_open(db, row.product_id, new_year)
    if (new_year != row.year or new_no != row.batch_no) and (
        await repo.find_batch(db, row.section_id, new_year, new_no) is not None
    ):
        raise AppException(
            status_code=409, message=f"批号 {new_no} 在该段 {new_year} 年度已登记"
        )
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="apr_batch",
        resource_id=row.id,
        old_value=old,
        new_value=_batch_dict(row),
    )
    return _batch_dict(row)


async def delete_batch(
    db: AsyncSession, batch_id: uuid.UUID, user: User | None
) -> None:
    row = await _get_batch_or_404(db, batch_id)
    await _ensure_year_open(db, row.product_id, row.year)
    await repo.delete_values_of_batch(db, batch_id)
    row.is_deleted = True
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="delete",
        user=user,
        resource_type="apr_batch",
        resource_id=row.id,
        old_value=_batch_dict(row),
    )


# ───────────────────────── 值 ─────────────────────────


async def batch_values(db: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any]:
    """录入表单渲染数据：批次 + 段内列定义 + 现有值 + 锁定状态。"""
    batch = await _get_batch_or_404(db, batch_id)
    section = await _get_section_or_404(db, batch.section_id)
    product = await _get_product_or_404(db, batch.product_id)
    items = [
        _item_dict(i)
        for i in await repo.list_items(db, batch.section_id, active_only=True)
    ]
    values = await repo.list_values_of_batch(db, batch_id)
    review = await repo.get_annual_review(db, batch.product_id, batch.year)
    return {
        "batch": _batch_dict(batch),
        "section": _section_dict(section),
        "product": _product_dict(product),
        "items": items,
        "values": [
            {
                "item_id": str(v.item_id),
                "row_seq": v.row_seq,
                "row_label": v.row_label,
                "value_num": v.value_num,
                "value_text": v.value_text,
                "remark": v.remark,
            }
            for v in values
        ],
        "locked": review is not None and review.status == "locked",
    }


async def save_batch_values(
    db: AsyncSession,
    batch_id: uuid.UUID,
    payload: AprBatchValuesIn,
    user: User | None,
) -> dict[str, Any]:
    """整批全量替换保存：锁拦截 + 列归属校验 + 值类型匹配 + (item,row) 去重。"""
    batch = await _get_batch_or_404(db, batch_id)
    await _ensure_year_open(db, batch.product_id, batch.year)
    section = await _get_section_or_404(db, batch.section_id)
    if not section.multi_row:
        # 单行段只认第 1 行：放任 row_seq>1 落库会在汇总里展开出幻影行。
        bad_rows = sorted({v.row_seq for v in payload.values if v.row_seq != 1})
        if bad_rows:
            raise AppException(
                status_code=422,
                message=f"该段为单行段，不支持第 {bad_rows[0]} 行等多行数据。",
            )
    items = {
        i.id: i for i in await repo.list_items(db, batch.section_id, active_only=True)
    }
    seen: set[tuple[uuid.UUID, int]] = set()
    rows: list[dict[str, Any]] = []
    for v in payload.values:
        item = items.get(v.item_id)
        if item is None:
            raise AppException(
                status_code=422,
                message="存在不属于该批次所在段（或已停用）的列定义。",
            )
        key = (v.item_id, v.row_seq)
        if key in seen:
            raise AppException(
                status_code=422,
                message=f"列「{item.name_cn}」第 {v.row_seq} 行重复提交。",
            )
        seen.add(key)
        if v.value_num is None and v.value_text is None and not v.remark:
            # 空值占位不落库。
            continue
        if item.value_type == AprValueType.NUMBER.value:
            # 数值列允许只填文字结果，但必须是列定义 quick_values 白名单里的
            # 值（如 未检出/<0.01）；NFKC 顺带修正全角数字与 ＜ 等兼容字符。
            if v.value_num is None and v.value_text is None:
                raise AppException(
                    status_code=422,
                    message=(
                        f"列「{item.name_cn}」为数值型，"
                        "须填写数值或文字结果（如 未检出）。"
                    ),
                )
            if v.value_text is not None:
                text = _nfkc("NFKC", v.value_text).strip()
                allowed = [_nfkc("NFKC", q).strip() for q in (item.quick_values or [])]
                if text not in allowed:
                    hint = (
                        f"文字结果只能填：{'、'.join(allowed)}。"
                        if allowed
                        else "未配置文字结果，请填数字。"
                    )
                    raise AppException(
                        status_code=422,
                        message=f"列「{item.name_cn}」为数值型，{hint}",
                    )
                v.value_text = text
            rows.append(
                {
                    "item_id": v.item_id,
                    "row_seq": v.row_seq,
                    "row_label": v.row_label,
                    "value_num": v.value_num,
                    "value_text": v.value_text,
                    "remark": v.remark,
                }
            )
        else:
            if v.value_text is None:
                raise AppException(
                    status_code=422,
                    message=f"列「{item.name_cn}」为文字型，必须填写文字结果。",
                )
            rows.append(
                {
                    "item_id": v.item_id,
                    "row_seq": v.row_seq,
                    "row_label": v.row_label,
                    "value_num": None,
                    "value_text": v.value_text,
                    "remark": v.remark,
                }
            )
    # 必填校验：整批替换语义下，漏填的必填项会被静默清掉，这里显式拦下来。
    required_items = [item for item in items.values() if item.required]
    if required_items:
        filled = {(row["item_id"], row["row_seq"]) for row in rows}
        if section.multi_row:
            # 多行段只校验「有内容的行」；全空时回退到第 1 行，避免空批次整批清空。
            row_scope = sorted({row["row_seq"] for row in rows}) or [1]
        else:
            row_scope = [1]
        missing: list[str] = []
        for row_seq in row_scope:
            for item in required_items:
                if (item.id, row_seq) in filled:
                    continue
                missing.append(
                    f"第 {row_seq} 行「{item.name_cn}」"
                    if section.multi_row
                    else f"「{item.name_cn}」"
                )
        if missing:
            raise AppException(
                status_code=422,
                message="以下必填项未填写：" + "、".join(missing),
            )
    count = await repo.replace_batch_values(
        db, batch_id, rows, actor_id=_actor_id(user)
    )
    await _audit(
        db,
        action="save_values",
        user=user,
        resource_type="apr_batch",
        resource_id=batch_id,
        extra={"year": batch.year, "batch_no": batch.batch_no, "values": count},
    )
    return {"batch_id": str(batch_id), "saved": count}


# ───────────────────────── 趋势 ─────────────────────────


def classify_point(
    value: float,
    *,
    spec_min: float | None,
    spec_max: float | None,
    oot_min: float | None,
    oot_max: float | None,
) -> str:
    """OOS=超标准限；OOT=超预警线但在标准内；其余 normal。"""
    if (spec_min is not None and value < spec_min) or (
        spec_max is not None and value > spec_max
    ):
        return "oos"
    if (oot_min is not None and value < oot_min) or (
        oot_max is not None and value > oot_max
    ):
        return "oot"
    return "normal"


async def trend(
    db: AsyncSession, item_id: uuid.UUID, *, year: int | None = None
) -> dict[str, Any]:
    item = await _get_item_or_404(db, item_id)
    if not item.trend_enabled:
        raise AppException(status_code=422, message="该列未启用趋势分析。")
    if item.value_type != AprValueType.NUMBER.value:
        raise AppException(status_code=422, message="文字型列不支持趋势分析。")
    section = await _get_section_or_404(db, item.section_id)
    product = await _get_product_or_404(db, section.product_id)
    series = await repo.load_numeric_series(db, item_id, year=year)
    points = []
    values: list[float] = []
    nd_count = 0
    for batch_id, batch_no, seq, batch_year, row_seq, value, text in series:
        is_nd = value is None
        if is_nd:
            # 文字结果行（未检出等）：exclude 口径不进样本，zero 口径按 0
            # 计入；OOS/OOT 判定一律不参与（按 0 判会在设预警下限的列误报）。
            nd_count += 1
            if item.nd_policy == AprNdPolicy.EXCLUDE.value:
                continue
            value = 0.0
            status = "normal"
        else:
            status = classify_point(
                value,
                spec_min=item.spec_min,
                spec_max=item.spec_max,
                oot_min=item.oot_min,
                oot_max=item.oot_max,
            )
        values.append(value)
        points.append(
            {
                "batch_id": str(batch_id),
                "batch_no": batch_no,
                "seq": seq,
                "year": batch_year,
                "row_seq": row_seq,
                "value": value,
                "nd": is_nd,
                "text": text,
                "status": status,
            }
        )
    stats: dict[str, Any] = {"count": len(values)}
    if nd_count:
        stats["nd_count"] = nd_count
    if len(values) >= MIN_STATS_SAMPLES:
        mean = statistics.fmean(values)
        stdev = statistics.stdev(values)
        stats.update(
            {
                "mean": mean,
                "stdev": stdev,
                "plus3s": mean + 3 * stdev,
                "minus3s": mean - 3 * stdev,
                "max": max(values),
                "min": min(values),
            }
        )
    return {
        "item": _item_dict(item),
        "section": _section_dict(section),
        "product": _product_dict(product),
        "year": year,
        "points": points,
        "stats": stats,
    }


# ───────────────────────── 汇总 ─────────────────────────


def _numeric_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    stats: dict[str, Any] = {
        "count": len(values),
        "mean": statistics.fmean(values),
        "max": max(values),
        "min": min(values),
    }
    if len(values) >= MIN_STATS_SAMPLES:
        stats["stdev"] = statistics.stdev(values)
    return stats


async def summary(
    db: AsyncSession,
    product_id: uuid.UUID,
    *,
    year: int,
    data_kind: str | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    """年终汇总矩阵：每段 = 动态列定义 + 批次行 + 单元格值 + 数值列统计。"""
    product = await _get_product_or_404(db, product_id)
    review = await repo.get_annual_review(db, product_id, year)
    sections = await repo.list_sections(db, product_id)
    section_payloads: list[dict[str, Any]] = []
    for s in sections:
        if data_kind and s.data_kind != data_kind:
            continue
        if market and (s.market or "") != market:
            continue
        batches = await repo.list_batches_of_section(db, s.id, year=year)
        if not batches:
            continue
        items = [i for i in await repo.list_items(db, s.id, active_only=True)]
        item_ids = [i.id for i in items]
        raw_values = (
            await repo.load_section_values(db, s.id, year=year, item_ids=item_ids)
            if item_ids
            else []
        )
        # (batch_id, row_seq) -> {item_id: (num, text)}；行标签取首个非空。
        cells: dict[tuple[uuid.UUID, int], dict[uuid.UUID, Any]] = {}
        label_lookup: dict[tuple[uuid.UUID, int], str | None] = {}
        for batch_id, item_id, row_seq, value_num, value_text, row_label in raw_values:
            cells.setdefault((batch_id, row_seq), {})[item_id] = (
                value_num,
                value_text,
            )
            if row_label and (batch_id, row_seq) not in label_lookup:
                label_lookup[(batch_id, row_seq)] = row_label
        # 行结构：普通段一批一行；multi_row 段按已录行号展开。
        rows: list[dict[str, Any]] = []
        row_meta: dict[uuid.UUID, list[int]] = {}
        for b in batches:
            row_seqs = sorted(
                {row_seq for (bid, row_seq) in cells if bid == b.id} or {1}
            )
            row_meta[b.id] = row_seqs
        for b in batches:
            for row_seq in row_meta[b.id]:
                row_cells: dict[str, dict[str, Any]] = {}
                for i in items:
                    num, text = cells.get((b.id, row_seq), {}).get(i.id, (None, None))
                    status = None
                    if num is not None:
                        status = classify_point(
                            num,
                            spec_min=i.spec_min,
                            spec_max=i.spec_max,
                            oot_min=i.oot_min,
                            oot_max=i.oot_max,
                        )
                    row_cells[str(i.id)] = {
                        "num": num,
                        "text": text,
                        "status": status,
                    }
                rows.append(
                    {
                        "batch_id": str(b.id),
                        "seq": b.seq,
                        "batch_no": b.batch_no,
                        "row_seq": row_seq,
                        "row_label": label_lookup.get((b.id, row_seq)),
                        "cells": row_cells,
                    }
                )
        # 数值列统计：文字结果行（未检出等）按列口径映射，exclude 不进样本。
        column_stats: dict[str, Any] = {}
        for i in items:
            if i.value_type != AprValueType.NUMBER.value:
                continue
            nums: list[float] = []
            nd_count = 0
            for per in cells.values():
                num, text = per.get(i.id, (None, None))
                if num is not None:
                    nums.append(num)
                elif text is not None:
                    nd_count += 1
                    if i.nd_policy == AprNdPolicy.ZERO.value:
                        nums.append(0.0)
            if nums or nd_count:
                stats = _numeric_stats(nums)
                if nd_count:
                    stats["nd_count"] = nd_count
                column_stats[str(i.id)] = stats
        section_payloads.append(
            {
                **_section_dict(s),
                "items": [_item_dict(i) for i in items],
                "rows": rows,
                "column_stats": column_stats,
            }
        )
    return {
        "product": _product_dict(product),
        "year": year,
        "locked": review is not None and review.status == "locked",
        "batch_years": await repo.distinct_batch_years(db, product_id),
        "sections": section_payloads,
    }


# ───────────────────────── 年度汇总导出 ─────────────────────────


def _excel_sheet_name(section_name: str, market: str | None, used: set[str]) -> str:
    """Excel sheet 名 ≤31 字符且工作簿内唯一。"""
    base = section_name if not market else f"{section_name}-{market}"
    name = base[:31] or "sheet"
    candidate = name
    suffix = 2
    while candidate in used:
        tail = f"({suffix})"
        candidate = f"{name[: 31 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def _item_display_name(item: dict[str, Any]) -> str:
    """#min/#max 成对列在导出时带 MIN/MAX 后缀。"""
    name = str(item["name_cn"])
    if item["code"].endswith("#min"):
        name = f"{name} MIN"
    elif item["code"].endswith("#max"):
        name = f"{name} MAX"
    return name


def build_export_workbook(
    summary_data: dict[str, Any],
) -> Any:
    """把 summary 结果渲染成 xlsx 工作簿（openpyxl，多级表头+表尾统计行）。

    同步渲染会短暂占用事件循环：当前量级（单产品单年几十批 × 百来列）
    毫秒级可接受；若矩阵显著增长再考虑挪 run_in_executor/后台任务。
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    product = summary_data["product"]
    year = summary_data["year"]
    wb = openpyxl.Workbook()
    default_sheet = wb.active
    if default_sheet is not None:
        wb.remove(default_sheet)
    used_names: set[str] = set()
    bold = Font(bold=True)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for section in summary_data["sections"]:
        ws = wb.create_sheet(
            title=_excel_sheet_name(section["name"], section["market"], used_names)
        )
        items = section["items"]
        # 列布局：序号 | 批号 | [行标签] | 数据列…
        data_col_offset = 3 if section["multi_row"] else 2
        n_cols = data_col_offset + len(items)

        # r1 标题
        title = (
            f"年度产品审核/ANNUAL PRODUCT REVIEW——{product['name']}"
            f"（{product['code']}）{year} · {section['name']}"
        )
        ws.cell(row=1, column=1, value=title).font = Font(bold=True, size=13)
        ws.merge_cells(
            start_row=1, start_column=1, end_row=1, end_column=max(n_cols, 2)
        )
        # r2 分组（相邻同组合并）
        group_row = 2
        col = data_col_offset + 1
        while col <= n_cols:
            group = items[col - data_col_offset - 1]["group_name"]
            end = col
            while (
                end + 1 <= n_cols
                and items[end - data_col_offset]["group_name"] == group
            ):
                end += 1
            cell = ws.cell(row=group_row, column=col, value=group or "")
            cell.font = bold
            cell.alignment = center
            if end > col:
                ws.merge_cells(
                    start_row=group_row,
                    start_column=col,
                    end_row=group_row,
                    end_column=end,
                )
            col = end + 1
        # r3 列名 / r4 标准
        ws.cell(row=3, column=1, value="序号").font = bold
        ws.cell(row=3, column=2, value="批号").font = bold
        if section["multi_row"]:
            ws.cell(row=3, column=3, value="行标签").font = bold
        for idx, item in enumerate(items):
            name_cell = ws.cell(
                row=3, column=data_col_offset + 1 + idx, value=_item_display_name(item)
            )
            name_cell.font = bold
            name_cell.alignment = center
            ws.cell(
                row=4,
                column=data_col_offset + 1 + idx,
                value=item["spec_text"] or "",
            ).alignment = center
        # 数据行
        for ridx, row in enumerate(section["rows"], start=1):
            excel_row = 4 + ridx
            ws.cell(row=excel_row, column=1, value=ridx)
            ws.cell(row=excel_row, column=2, value=row["batch_no"])
            col_cursor = data_col_offset + 1
            if section["multi_row"]:
                ws.cell(row=excel_row, column=3, value=row["row_label"] or "")
            for item in items:
                cell_data = row["cells"].get(item["id"])
                value = None
                if cell_data is not None:
                    value = (
                        cell_data["num"]
                        if cell_data["num"] is not None
                        else cell_data["text"]
                    )
                ws.cell(row=excel_row, column=col_cursor, value=value)
                col_cursor += 1
        # 表尾统计（仅数值列）
        stats_by_id = section["column_stats"]
        stat_rows = [
            ("平均值", "mean"),
            ("最大值", "max"),
            ("最小值", "min"),
            ("STDEV", "stdev"),
        ]
        base_row = 4 + len(section["rows"]) + 1
        for offset, (label, key) in enumerate(stat_rows):
            row_idx = base_row + offset
            ws.cell(row=row_idx, column=1, value=label).font = bold
            for idx, item in enumerate(items):
                stats = stats_by_id.get(item["id"])
                if stats:
                    ws.cell(
                        row=row_idx,
                        column=data_col_offset + 1 + idx,
                        value=round(stats[key], 6)
                        if stats.get(key) is not None
                        else "",
                    )
        # 列宽
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 20
        for idx in range(len(items)):
            ws.column_dimensions[
                get_column_letter(data_col_offset + 1 + idx)
            ].width = 14
    if not wb.sheetnames:
        ws = wb.create_sheet(title="无数据")
        ws.cell(row=1, column=1, value="该年度没有可导出的段数据。")
    return wb


# ───────────────────────── 年度锁定 ─────────────────────────


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
            review = await repo.get_annual_review(
                db, product_id, year, for_update=True
            )
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
