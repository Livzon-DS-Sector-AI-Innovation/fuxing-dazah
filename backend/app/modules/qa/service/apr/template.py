"""PQR 模板配置域：产品 / 段 / 列定义（含批量粘贴）/ 跨产品模板复制。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import AprItem, AprProduct, AprSection, AprValueType
from app.modules.qa.repository import apr as repo
from app.modules.qa.schemas.apr import (
    AprItemBase,
    AprItemCreate,
    AprItemsBulkCreate,
    AprItemUpdate,
    AprProductCreate,
    AprProductUpdate,
    AprSectionCreate,
    AprSectionUpdate,
)
from app.modules.qa.service.apr.common import (
    _actor_id,
    _audit,
    _get_item_or_404,
    _get_product_or_404,
    _get_section_or_404,
    _item_dict,
    _product_dict,
    _section_dict,
)
from app.platform.identity.models import User

# 列定义的限度字段：改写历史 OOS/OOT 判定，锁定年度有值时冻结。
_LIMIT_FIELDS = ("spec_min", "spec_max", "oot_min", "oot_max")


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
        raise AppException(status_code=409, message=f"段名 {name} 在该产品下已存在")


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
            message=_section_conflict_message(exc, name=data.get("name") or row.name),
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
        "stat_precision": payload.stat_precision,
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
    return {
        "section_id": str(section_id),
        "count": len(rows),
        "items": [_item_dict(row) for row in rows],
    }


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
        field
        for field in _LIMIT_FIELDS
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
                    stat_precision=i.stat_precision,
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
