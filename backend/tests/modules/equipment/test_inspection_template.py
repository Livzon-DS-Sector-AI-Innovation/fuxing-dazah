"""巡检模板域业务逻辑测试（模板 CRUD、检查项）。

断言以业务规则为准，而非照抄 app 实现。
"""

import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.inspection_template import InspectionTemplateItem
from app.modules.equipment.repository.inspection_template import (
    get_template_item_by_id,
)
from app.modules.equipment.schemas.inspection_template import (
    InspectionTemplateCreate,
    InspectionTemplateItemCreate,
    InspectionTemplateItemUpdate,
    InspectionTemplateUpdate,
)
from app.modules.equipment.service.inspection_template import (
    add_template_item,
    create_inspection_template,
    delete_inspection_template,
    delete_template_item,
    get_inspection_template_by_id,
    get_inspection_templates,
    update_inspection_template,
    update_template_item,
)
from app.platform.identity.models import User

# ═══════════ Fixtures ═══════════════════════════════════════


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    """模板创建者用户。"""
    user = User(name="模板负责人", employee_no=f"EMP-T-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def ctx(
    owner: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> EquipmentAccessContext:
    """无数据范围限制的访问上下文（data_scope="all"）。"""
    return make_access_ctx(owner)


def _template_data(name: str | None = None) -> InspectionTemplateCreate:
    """构造带唯一名称的模板创建请求。"""
    return InspectionTemplateCreate(
        name=name or f"巡检模板-{uuid.uuid4().hex[:8]}",
        description="测试模板",
    )


async def _fetch_items(
    db: AsyncSession, template_id: uuid.UUID
) -> list[InspectionTemplateItem]:
    """直接查库读取模板未删除的检查项（绕开会话内缓存的关系集合）。"""
    result = await db.execute(
        select(InspectionTemplateItem)
        .where(
            InspectionTemplateItem.template_id == template_id,
            InspectionTemplateItem.is_deleted == False,  # noqa: E712
        )
        .order_by(InspectionTemplateItem.sort_order)
    )
    return list(result.scalars().all())


# ═══════════ 模板 CRUD ═══════════════════════════════════════


async def test_create_template_sets_created_by(
    db_session: AsyncSession, ctx: EquipmentAccessContext, owner: User
) -> None:
    """有 ctx 时创建模板应写入 created_by / updated_by 为当前用户。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)
    assert tpl.created_by == owner.id
    assert tpl.updated_by == owner.id
    assert tpl.is_active is True


async def test_create_template_without_ctx_no_owner(
    db_session: AsyncSession,
) -> None:
    """无 ctx 时创建模板不写归属字段（created_by 为空）。"""
    tpl = await create_inspection_template(db_session, _template_data())
    assert tpl.created_by is None


async def test_create_template_with_items(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建模板可同时带检查项，含 numeric 类型与单位。"""
    data = InspectionTemplateCreate(
        name=f"带项模板-{uuid.uuid4().hex[:8]}",
        items=[
            InspectionTemplateItemCreate(item_name="外观检查", sort_order=1),
            InspectionTemplateItemCreate(
                item_name="温度",
                data_type="numeric",
                unit="℃",
                expected_result="25±2",
                sort_order=2,
            ),
        ],
    )
    tpl = await create_inspection_template(db_session, data, ctx=ctx)
    items = sorted(tpl.items, key=lambda i: i.sort_order)
    assert len(items) == 2
    assert items[0].item_name == "外观检查"
    assert items[0].data_type == "text"  # 默认
    assert items[1].data_type == "numeric"
    assert items[1].unit == "℃"


async def test_get_template_by_id_success(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """按 ID 获取已创建的模板。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)
    fetched = await get_inspection_template_by_id(db_session, tpl.id, ctx=ctx)
    assert fetched.id == tpl.id


async def test_get_template_by_id_not_found(db_session: AsyncSession) -> None:
    """获取不存在的模板抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await get_inspection_template_by_id(db_session, uuid.uuid4())


async def test_get_templates_list_keyword_and_active(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """列表支持关键词与 is_active 过滤，且返回总数。"""
    unique = uuid.uuid4().hex[:8]
    active = await create_inspection_template(
        db_session, _template_data(f"关键词A-{unique}"), ctx=ctx
    )
    await update_inspection_template(
        db_session,
        (
            await create_inspection_template(
                db_session, _template_data(f"关键词B-{unique}"), ctx=ctx
            )
        ).id,
        InspectionTemplateUpdate(is_active=False),
        ctx=ctx,
    )

    templates, total = await get_inspection_templates(
        db_session, keyword=unique, is_active=True, ctx=ctx
    )
    assert total == 1
    assert [t.id for t in templates] == [active.id]


async def test_update_template_changes_fields(
    db_session: AsyncSession, ctx: EquipmentAccessContext, owner: User
) -> None:
    """更新模板改名并写入 updated_by。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)
    updated = await update_inspection_template(
        db_session,
        tpl.id,
        InspectionTemplateUpdate(name="新模板名", is_active=False),
        ctx=ctx,
    )
    assert updated.name == "新模板名"
    assert updated.is_active is False
    assert updated.updated_by == owner.id


async def test_update_template_not_found(db_session: AsyncSession) -> None:
    """更新不存在的模板抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await update_inspection_template(
            db_session, uuid.uuid4(), InspectionTemplateUpdate(name="x")
        )


async def test_delete_template_soft_delete(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """删除模板为软删除，删除后再查抛 NotFoundException。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)
    assert await delete_inspection_template(db_session, tpl.id, ctx=ctx) is True
    with pytest.raises(NotFoundException):
        await get_inspection_template_by_id(db_session, tpl.id, ctx=ctx)


async def test_delete_template_not_found(db_session: AsyncSession) -> None:
    """删除不存在的模板抛 NotFoundException（先 get 再删）。"""
    with pytest.raises(NotFoundException):
        await delete_inspection_template(db_session, uuid.uuid4())


async def test_restricted_non_owner_cannot_update(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """受限用户看不到他人模板，更新时因数据范围隔离抛 NotFoundException。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)

    other = User(name="外部用户", employee_no=f"EMP-O-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    restricted = EquipmentAccessContext(
        user=other, data_scope="self_only", department_user_ids=[]
    )

    with pytest.raises(NotFoundException):
        await update_inspection_template(
            db_session, tpl.id, InspectionTemplateUpdate(name="越权改名"), ctx=restricted
        )


# ═══════════ 检查项 ═══════════════════════════════════════════


async def test_add_template_item(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """向模板添加检查项后能在模板 items 中查到。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)
    await add_template_item(
        db_session,
        tpl.id,
        InspectionTemplateItemCreate(item_name="压力检查", sort_order=1),
        ctx=ctx,
    )
    items = await _fetch_items(db_session, tpl.id)
    assert [i.item_name for i in items] == ["压力检查"]


async def test_add_template_item_numeric(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """添加 numeric 型检查项应保留 data_type 与 unit。"""
    tpl = await create_inspection_template(db_session, _template_data(), ctx=ctx)
    await add_template_item(
        db_session,
        tpl.id,
        InspectionTemplateItemCreate(
            item_name="电流", data_type="numeric", unit="A"
        ),
        ctx=ctx,
    )
    items = await _fetch_items(db_session, tpl.id)
    item = items[0]
    assert item.data_type == "numeric"
    assert item.unit == "A"


async def test_add_item_to_nonexistent_template(
    db_session: AsyncSession,
) -> None:
    """向不存在的模板添加检查项抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await add_template_item(
            db_session,
            uuid.uuid4(),
            InspectionTemplateItemCreate(item_name="x"),
        )


async def test_update_template_item(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新检查项名称成功。"""
    data = InspectionTemplateCreate(
        name=f"模板-{uuid.uuid4().hex[:8]}",
        items=[InspectionTemplateItemCreate(item_name="旧名")],
    )
    tpl = await create_inspection_template(db_session, data, ctx=ctx)
    item_id = tpl.items[0].id

    await update_template_item(
        db_session, item_id, InspectionTemplateItemUpdate(item_name="新名"), ctx=ctx
    )
    reloaded = await get_template_item_by_id(db_session, item_id)
    assert reloaded is not None
    assert reloaded.item_name == "新名"


async def test_update_template_item_not_found(db_session: AsyncSession) -> None:
    """更新不存在的检查项抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await update_template_item(
            db_session, uuid.uuid4(), InspectionTemplateItemUpdate(item_name="x")
        )


async def test_delete_template_item(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """删除检查项返回 True，软删除后再查为空。"""
    data = InspectionTemplateCreate(
        name=f"模板-{uuid.uuid4().hex[:8]}",
        items=[InspectionTemplateItemCreate(item_name="待删项")],
    )
    tpl = await create_inspection_template(db_session, data, ctx=ctx)
    item_id = tpl.items[0].id

    assert await delete_template_item(db_session, item_id, ctx=ctx) is True
    assert await get_template_item_by_id(db_session, item_id) is None


async def test_delete_template_item_not_found(db_session: AsyncSession) -> None:
    """删除不存在的检查项返回 False（非异常）。"""
    assert await delete_template_item(db_session, uuid.uuid4()) is False

