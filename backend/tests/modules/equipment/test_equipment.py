"""设备台账域（分类 / 位置 / 设备）业务规则测试.

覆盖分类、位置、设备的 CRUD、级联删除守卫、统计、筛选，以及软删除安全的
部分唯一约束（同 code 软删后可重建；部门内唯一）。

断言以业务规则为准，而非照抄现有实现。多数用例走 service 层（真实 DB
会话，测后回滚）；404 / 409 的 HTTP 语义走 API 层。共享 Postgres，故所有
code / equipment_no 均带随机后缀避免撞键。
"""

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.equipment import service
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, EquipmentCategory, Location
from app.modules.equipment.schemas import (
    EquipmentCategoryCreate,
    EquipmentCategoryUpdate,
    EquipmentCreate,
    EquipmentUpdate,
    LocationCreate,
    LocationUpdate,
)
from app.modules.equipment.schemas.equipment import EquipmentStatus
from app.platform.identity.models import User


def _rand(prefix: str) -> str:
    """生成带随机后缀的唯一编码，避免共享测试库撞键。"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def ctx(
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> EquipmentAccessContext:
    """无数据范围限制的访问上下文（data_scope="all"，超管视角）。"""
    return make_access_ctx(User(name="设备测试员"))


def _dept_ctx(dept_id: uuid.UUID) -> EquipmentAccessContext:
    """构造受限于单个部门的访问上下文，用于验证部门绑定与部门范围隔离。"""
    return EquipmentAccessContext(
        user=User(name="部门设备员"),
        data_scope="department",
        visible_department_ids=[dept_id],
    )


# ==================== service 层建对象辅助 ====================
async def _make_category(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    *,
    code: str | None = None,
    name: str = "反应釜",
    parent_id: uuid.UUID | None = None,
) -> EquipmentCategory:
    """经 service 创建一个设备分类并返回。"""
    data = EquipmentCategoryCreate(
        name=name, code=code or _rand("RF"), parent_id=parent_id
    )
    return await service.create_equipment_category(db, data, ctx)


async def _make_location(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    *,
    code: str | None = None,
    name: str = "一车间",
    parent_id: uuid.UUID | None = None,
) -> Location:
    """经 service 创建一个位置并返回。"""
    data = LocationCreate(
        name=name, code=code or _rand("WS"), parent_id=parent_id
    )
    return await service.create_location(db, data, ctx)


async def _make_equipment(
    db: AsyncSession,
    *,
    category_ids: list[uuid.UUID],
    location_id: uuid.UUID,
    equipment_no: str | None = None,
    name: str = "R-101反应釜",
    status: EquipmentStatus = "完好",
    department_id: uuid.UUID | None = None,
) -> Equipment:
    """经 service 创建一台设备并返回。"""
    data = EquipmentCreate(
        name=name,
        equipment_no=equipment_no or _rand("EQ"),
        category_ids=category_ids,
        location_id=location_id,
        status=status,
        department_id=department_id,
    )
    return await service.create_equipment(db, data)


# ==================== 分类 CRUD ====================
async def test_create_category_success(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建分类：返回持久化对象，超管无部门时 department_id 为空。"""
    code = _rand("RF")
    category = await _make_category(db_session, ctx, code=code, name="反应釜")
    assert category.id is not None
    assert category.name == "反应釜"
    assert category.code == code
    assert category.department_id is None


async def test_create_category_binds_current_department(
    db_session: AsyncSession,
) -> None:
    """创建分类：自动绑定 ctx.visible_department_ids[0] 作为归属部门。"""
    dept_id = uuid.uuid4()
    category = await _make_category(db_session, _dept_ctx(dept_id))
    assert category.department_id == dept_id


async def test_create_category_duplicate_code_same_department(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建分类：同部门内 code 重复应抛 DuplicateException。"""
    code = _rand("RF")
    await _make_category(db_session, ctx, code=code)
    with pytest.raises(DuplicateException):
        await _make_category(db_session, ctx, code=code)


async def test_create_category_same_code_different_department_allowed(
    db_session: AsyncSession,
) -> None:
    """创建分类：唯一性限定在部门内，不同部门可用相同 code。"""
    code = _rand("RF")
    cat_a = await _make_category(db_session, _dept_ctx(uuid.uuid4()), code=code)
    cat_b = await _make_category(db_session, _dept_ctx(uuid.uuid4()), code=code)
    assert cat_a.code == cat_b.code == code
    assert cat_a.department_id != cat_b.department_id


async def test_get_category_by_id(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """按 ID 获取分类返回对应对象。"""
    category = await _make_category(db_session, ctx)
    fetched = await service.get_equipment_category_by_id(db_session, category.id)
    assert fetched.id == category.id


async def test_get_category_by_id_not_found(db_session: AsyncSession) -> None:
    """获取不存在分类抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await service.get_equipment_category_by_id(db_session, uuid.uuid4())


async def test_get_categories_scoped_to_department(db_session: AsyncSession) -> None:
    """获取分类列表：按部门范围过滤，只返回本部门根分类。"""
    dept_ctx = _dept_ctx(uuid.uuid4())
    await _make_category(db_session, dept_ctx)
    await _make_category(db_session, dept_ctx)
    roots = await service.get_equipment_categories(db_session, None, dept_ctx)
    assert len(roots) == 2


async def test_get_category_tree(db_session: AsyncSession) -> None:
    """获取分类树：根分类挂载其子分类。"""
    dept_ctx = _dept_ctx(uuid.uuid4())
    parent = await _make_category(db_session, dept_ctx, name="通用设备")
    child = await _make_category(
        db_session, dept_ctx, name="反应釜", parent_id=parent.id
    )
    tree = await service.get_equipment_category_tree(db_session, dept_ctx)
    assert len(tree) == 1
    assert tree[0].id == parent.id
    assert [c.id for c in tree[0].children] == [child.id]


async def test_update_category_name(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新分类名称。"""
    category = await _make_category(db_session, ctx, name="反应釜")
    updated = await service.update_equipment_category(
        db_session, category.id, EquipmentCategoryUpdate(name="大型反应釜"), ctx
    )
    assert updated.name == "大型反应釜"


async def test_update_category_duplicate_code_rejected(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新分类 code 撞同部门内其他分类应抛 DuplicateException。"""
    code_a = _rand("RF")
    await _make_category(db_session, ctx, code=code_a)
    cat_b = await _make_category(db_session, ctx, code=_rand("RF"))
    with pytest.raises(DuplicateException):
        await service.update_equipment_category(
            db_session, cat_b.id, EquipmentCategoryUpdate(code=code_a), ctx
        )


async def test_update_category_not_found(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新不存在分类抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await service.update_equipment_category(
            db_session, uuid.uuid4(), EquipmentCategoryUpdate(name="x"), ctx
        )


async def test_delete_category_soft(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """删除分类为软删除：返回 True 且再次获取抛 NotFoundException。"""
    category = await _make_category(db_session, ctx)
    assert await service.delete_equipment_category(db_session, category.id, ctx) is True
    with pytest.raises(NotFoundException):
        await service.get_equipment_category_by_id(db_session, category.id)


async def test_category_soft_delete_then_recreate_same_code(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """软删除后可用同 code 重建（部分唯一索引排除已删记录）。"""
    code = _rand("RF")
    first = await _make_category(db_session, ctx, code=code)
    await service.delete_equipment_category(db_session, first.id, ctx)
    second = await _make_category(db_session, ctx, code=code)
    assert second.id != first.id
    assert second.code == code


# ==================== 位置 CRUD ====================
async def test_create_location_success(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建位置：返回持久化对象，超管无部门时 department_id 为空。"""
    code = _rand("WS")
    location = await _make_location(db_session, ctx, code=code, name="一车间")
    assert location.id is not None
    assert location.code == code
    assert location.department_id is None


async def test_create_location_binds_current_department(
    db_session: AsyncSession,
) -> None:
    """创建位置：自动绑定 ctx.visible_department_ids[0] 作为归属部门。"""
    dept_id = uuid.uuid4()
    location = await _make_location(db_session, _dept_ctx(dept_id))
    assert location.department_id == dept_id


async def test_create_location_duplicate_code_same_department(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建位置：同部门内 code 重复应抛 DuplicateException。"""
    code = _rand("WS")
    await _make_location(db_session, ctx, code=code)
    with pytest.raises(DuplicateException):
        await _make_location(db_session, ctx, code=code)


async def test_get_location_by_id_not_found(db_session: AsyncSession) -> None:
    """获取不存在位置抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await service.get_location_by_id(db_session, uuid.uuid4())


async def test_get_locations_scoped_to_department(db_session: AsyncSession) -> None:
    """获取位置列表：按部门范围过滤，只返回本部门根位置。"""
    dept_ctx = _dept_ctx(uuid.uuid4())
    await _make_location(db_session, dept_ctx)
    await _make_location(db_session, dept_ctx)
    roots = await service.get_locations(db_session, None, dept_ctx)
    assert len(roots) == 2


async def test_get_location_tree(db_session: AsyncSession) -> None:
    """获取位置树：根位置挂载其子位置。"""
    dept_ctx = _dept_ctx(uuid.uuid4())
    parent = await _make_location(db_session, dept_ctx, name="工厂")
    child = await _make_location(
        db_session, dept_ctx, name="一车间", parent_id=parent.id
    )
    tree = await service.get_location_tree(db_session, dept_ctx)
    assert len(tree) == 1
    assert tree[0].id == parent.id
    assert [c.id for c in tree[0].children] == [child.id]


async def test_update_location_name(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新位置名称。"""
    location = await _make_location(db_session, ctx, name="一车间")
    updated = await service.update_location(
        db_session, location.id, LocationUpdate(name="二车间"), ctx
    )
    assert updated.name == "二车间"


async def test_delete_location_soft(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """删除位置为软删除：返回 True 且再次获取抛 NotFoundException。"""
    location = await _make_location(db_session, ctx)
    assert await service.delete_location(db_session, location.id, ctx) is True
    with pytest.raises(NotFoundException):
        await service.get_location_by_id(db_session, location.id)


async def test_location_soft_delete_then_recreate_same_code(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """软删除后可用同 code 重建位置（部分唯一索引排除已删记录）。"""
    code = _rand("WS")
    first = await _make_location(db_session, ctx, code=code)
    await service.delete_location(db_session, first.id, ctx)
    second = await _make_location(db_session, ctx, code=code)
    assert second.id != first.id


# ==================== 设备 CRUD ====================
async def test_generate_equipment_no_format(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """生成设备编号：无同类设备时为 EQ-{code}-0001，已有则序号递增。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)

    first_no = await service.generate_equipment_no(db_session, category.code)
    assert first_no == f"EQ-{category.code}-0001"

    await _make_equipment(
        db_session,
        category_ids=[category.id],
        location_id=location.id,
        equipment_no=first_no,
    )
    next_no = await service.generate_equipment_no(db_session, category.code)
    assert next_no == f"EQ-{category.code}-0002"


async def test_create_equipment_success(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建设备：编号保存正确，且用 category_ids 建立分类关联。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    eq_no = _rand("EQ")
    equipment = await _make_equipment(
        db_session,
        category_ids=[category.id],
        location_id=location.id,
        equipment_no=eq_no,
    )
    assert equipment.equipment_no == eq_no
    linked = [link.category_id for link in equipment.category_links if not link.is_deleted]
    assert linked == [category.id]


async def test_create_equipment_multiple_categories(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建设备：category_ids 支持多分类，逐个建立关联。"""
    cat_a = await _make_category(db_session, ctx)
    cat_b = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    equipment = await _make_equipment(
        db_session,
        category_ids=[cat_a.id, cat_b.id],
        location_id=location.id,
    )
    linked = {link.category_id for link in equipment.category_links if not link.is_deleted}
    assert linked == {cat_a.id, cat_b.id}


async def test_create_equipment_duplicate_no(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建设备：编号重复应抛 DuplicateException。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    eq_no = _rand("EQ")
    await _make_equipment(
        db_session,
        category_ids=[category.id],
        location_id=location.id,
        equipment_no=eq_no,
    )
    with pytest.raises(DuplicateException):
        await _make_equipment(
            db_session,
            category_ids=[category.id],
            location_id=location.id,
            equipment_no=eq_no,
        )


async def test_create_equipment_invalid_category(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建设备：任一分类不存在应抛 NotFoundException。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    with pytest.raises(NotFoundException):
        await _make_equipment(
            db_session,
            category_ids=[category.id, uuid.uuid4()],
            location_id=location.id,
        )


async def test_create_equipment_invalid_location(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """创建设备：位置不存在应抛 NotFoundException。"""
    category = await _make_category(db_session, ctx)
    with pytest.raises(NotFoundException):
        await _make_equipment(
            db_session,
            category_ids=[category.id],
            location_id=uuid.uuid4(),
        )


async def test_get_equipment_by_id_not_found(db_session: AsyncSession) -> None:
    """获取不存在设备抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await service.get_equipment_by_id(db_session, uuid.uuid4())


async def test_update_equipment_status(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新设备状态。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    equipment = await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    updated = await service.update_equipment(
        db_session, equipment.id, EquipmentUpdate(status="维修中"), ctx
    )
    assert updated.status == "维修中"


async def test_update_running_status_records_running_log(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新运行状态：字段生效且落一条 log_type=running 的日志（含创建基线共两条）。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    equipment = await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    assert equipment.running_status == "开机"

    updated = await service.update_equipment(
        db_session, equipment.id, EquipmentUpdate(running_status="停机"), ctx
    )
    assert updated.running_status == "停机"

    logs = await service.get_status_logs(db_session, equipment.id)
    running_logs = [log for log in logs if log.log_type == "running"]
    # 倒序：手动停机 → 创建基线开机
    assert [log.new_status for log in running_logs] == ["停机", "开机"]
    assert running_logs[0].source == "manual"


async def test_update_equipment_invalid_category(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """更新设备指定不存在分类应抛 NotFoundException。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    equipment = await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    with pytest.raises(NotFoundException):
        await service.update_equipment(
            db_session,
            equipment.id,
            EquipmentUpdate(category_ids=[uuid.uuid4()]),
            ctx,
        )


async def test_delete_equipment_soft(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """删除设备为软删除：返回 True 且再次获取抛 NotFoundException。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    equipment = await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    assert await service.delete_equipment(db_session, equipment.id, ctx) is True
    with pytest.raises(NotFoundException):
        await service.get_equipment_by_id(db_session, equipment.id)


async def test_equipment_soft_delete_then_recreate_same_no(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """软删除后可用同编号重建设备（部分唯一索引排除已删记录）。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    eq_no = _rand("EQ")
    first = await _make_equipment(
        db_session,
        category_ids=[category.id],
        location_id=location.id,
        equipment_no=eq_no,
    )
    await service.delete_equipment(db_session, first.id, ctx)
    second = await _make_equipment(
        db_session,
        category_ids=[category.id],
        location_id=location.id,
        equipment_no=eq_no,
    )
    assert second.id != first.id
    assert second.equipment_no == eq_no


# ==================== 级联删除守卫 ====================
async def test_delete_category_blocked_by_linked_equipment(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """分类下存在关联设备时不可删除。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    with pytest.raises(AppException):
        await service.delete_equipment_category(db_session, category.id, ctx)


async def test_delete_category_blocked_by_children(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """分类下存在子分类时不可删除。"""
    parent = await _make_category(db_session, ctx)
    await _make_category(db_session, ctx, parent_id=parent.id)
    with pytest.raises(AppException):
        await service.delete_equipment_category(db_session, parent.id, ctx)


async def test_delete_location_blocked_by_linked_equipment(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """位置下存在关联设备时不可删除。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    with pytest.raises(AppException):
        await service.delete_location(db_session, location.id, ctx)


async def test_delete_location_blocked_by_children(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """位置下存在子位置时不可删除。"""
    parent = await _make_location(db_session, ctx)
    await _make_location(db_session, ctx, parent_id=parent.id)
    with pytest.raises(AppException):
        await service.delete_location(db_session, parent.id, ctx)


async def test_delete_category_allowed_after_equipment_removed(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """设备软删除后其分类关联同步失效，分类可正常删除。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    equipment = await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id
    )
    await service.delete_equipment(db_session, equipment.id, ctx)
    assert await service.delete_equipment_category(db_session, category.id, ctx) is True


# ==================== 统计 ====================
async def test_equipment_statistics_structure(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """统计结果包含 total / by_status / by_category / by_location 四个键。"""
    stats = await service.get_equipment_statistics(db_session, ctx)
    assert set(stats.keys()) == {"total", "by_status", "by_category", "by_location"}
    assert isinstance(stats["total"], int)
    assert isinstance(stats["by_status"], dict)
    assert isinstance(stats["by_category"], dict)
    assert isinstance(stats["by_location"], dict)


async def test_equipment_statistics_counts_scoped_department(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """统计按数据范围过滤：仅统计本部门设备。"""
    dept_id = uuid.uuid4()
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    for _ in range(2):
        await _make_equipment(
            db_session,
            category_ids=[category.id],
            location_id=location.id,
            department_id=dept_id,
        )
    stats = await service.get_equipment_statistics(db_session, _dept_ctx(dept_id))
    assert stats["total"] == 2
    assert stats["by_status"].get("完好") == 2


# ==================== 筛选 ====================
async def test_filter_equipments_by_status(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """按状态筛选设备（用分类限定范围以精确断言）。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id, status="完好"
    )
    await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id, status="备用"
    )
    items, total = await service.get_equipments(
        db_session, ctx, category_id=category.id, status="完好"
    )
    assert total == 1
    assert [e.status for e in items] == ["完好"]


async def test_filter_equipments_by_category(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """按分类筛选设备，只返回该分类下的设备。"""
    cat_a = await _make_category(db_session, ctx)
    cat_b = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    target = await _make_equipment(
        db_session, category_ids=[cat_a.id], location_id=location.id
    )
    await _make_equipment(
        db_session, category_ids=[cat_b.id], location_id=location.id
    )
    items, total = await service.get_equipments(db_session, ctx, category_id=cat_a.id)
    assert total == 1
    assert items[0].id == target.id


async def test_filter_equipments_by_keyword(
    db_session: AsyncSession, ctx: EquipmentAccessContext
) -> None:
    """按关键字（名称/编号）筛选设备。"""
    category = await _make_category(db_session, ctx)
    location = await _make_location(db_session, ctx)
    keyword = uuid.uuid4().hex[:8].upper()
    target = await _make_equipment(
        db_session,
        category_ids=[category.id],
        location_id=location.id,
        name=f"离心机-{keyword}",
    )
    await _make_equipment(
        db_session, category_ids=[category.id], location_id=location.id, name="反应釜"
    )
    items, total = await service.get_equipments(
        db_session, ctx, category_id=category.id, keyword=keyword
    )
    assert total == 1
    assert items[0].id == target.id


# ==================== API 层 HTTP 语义 ====================
async def test_api_get_nonexistent_equipment_returns_404(client: AsyncClient) -> None:
    """获取不存在设备返回 404。"""
    response = await client.get(
        f"/api/v1/equipment/equipments/{uuid.uuid4()}"
    )
    assert response.status_code == 404


async def test_api_create_duplicate_category_code_returns_409(
    client: AsyncClient,
) -> None:
    """创建重复分类代码返回 409。"""
    code = _rand("DUP")
    first = await client.post(
        "/api/v1/equipment/categories", json={"name": "分类A", "code": code}
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/equipment/categories", json={"name": "分类B", "code": code}
    )
    assert second.status_code == 409


async def test_api_create_equipment_with_nonexistent_category_returns_404(
    client: AsyncClient,
) -> None:
    """用不存在的分类建设备返回 404。"""
    loc_resp = await client.post(
        "/api/v1/equipment/locations", json={"name": "测试车间", "code": _rand("WS")}
    )
    location_id = loc_resp.json()["data"]["id"]
    response = await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": "测试设备",
            "equipment_no": _rand("EQ"),
            "category_ids": [str(uuid.uuid4())],
            "location_id": location_id,
        },
    )
    assert response.status_code == 404
