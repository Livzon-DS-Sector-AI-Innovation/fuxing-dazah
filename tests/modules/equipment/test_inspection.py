"""巡检核心域测试：路线 CRUD、任务状态机、检查提交、跳过、异常建单、照片校验。

断言以业务规则为准（而非照抄实现）。疑似 app bug 的用例用 xfail 标注保留。
"""

import base64
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, Location, WorkOrder
from app.modules.equipment.models.inspection import InspectionTask
from app.modules.equipment.models.inspection_template import (
    InspectionRecord,
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.modules.equipment.repository.work_order import (
    get_pending_work_orders_by_inspection_task,
)
from app.modules.equipment.service import inspection as svc
from app.modules.equipment.service.inspection import (
    close_task,
    complete_task,
    create_route,
    create_task,
    delete_route,
    get_route_by_id,
    save_photo_from_base64,
    set_route_locations,
    skip_equipment_check,
    start_task,
    submit_equipment_check,
    submit_route_check,
    update_route,
)
from app.platform.identity.models import Department, User

# ═══════════ Fixtures ═══════════════════════════════════════


@pytest.fixture
async def inspector(db_session: AsyncSession) -> User:
    """巡检执行人。"""
    user = User(name="巡检员", employee_no=f"EMP-INS-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def leader(db_session: AsyncSession) -> User:
    """部门负责人（有 feishu_open_id，供部门 leader 推导责任人）。"""
    user = User(
        name="部门负责人",
        employee_no=f"EMP-LDR-{uuid.uuid4().hex[:8]}",
        feishu_open_id=f"ou_test_leader_{uuid.uuid4().hex[:6]}",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def department(db_session: AsyncSession, leader: User) -> Department:
    """挂载了 leader 的部门。"""
    dept = Department(
        name="生产一部",
        feishu_department_id=f"od_test_dept_{uuid.uuid4().hex[:6]}",
        leader_user_id=leader.feishu_open_id,
    )
    db_session.add(dept)
    await db_session.flush()
    return dept


@pytest.fixture
async def location(db_session: AsyncSession) -> Location:
    """巡检地点。"""
    loc = Location(name="一车间", code=f"WS-{uuid.uuid4().hex[:6]}")
    db_session.add(loc)
    await db_session.flush()
    return loc


@pytest.fixture
async def equipment_with_dept(
    db_session: AsyncSession, department: Department, location: Location
) -> Equipment:
    """归属部门、重要性=高的设备。"""
    eq = Equipment(
        equipment_no=f"EQ-{uuid.uuid4().hex[:8]}",
        name="R-101反应釜",
        location_id=location.id,
        status="在用",
        importance="高",
        department_id=department.id,
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest.fixture
async def other_equipment(
    db_session: AsyncSession, location: Location
) -> Equipment:
    """另一台存在但不属于任务的设备（用于归属校验）。"""
    eq = Equipment(
        equipment_no=f"EQ-{uuid.uuid4().hex[:8]}",
        name="R-999旁站设备",
        location_id=location.id,
        status="在用",
        importance="低",
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest.fixture
async def template_with_items(db_session: AsyncSession) -> InspectionTemplate:
    """含两个文本型检查项的模板。"""
    tpl = InspectionTemplate(name=f"文本模板-{uuid.uuid4().hex[:6]}")
    db_session.add(tpl)
    await db_session.flush()
    db_session.add_all(
        [
            InspectionTemplateItem(
                template_id=tpl.id,
                item_name="温度检查",
                expected_result="正常范围",
                sort_order=1,
            ),
            InspectionTemplateItem(
                template_id=tpl.id,
                item_name="密封性",
                expected_result="无渗漏",
                sort_order=2,
            ),
        ]
    )
    await db_session.flush()
    return tpl


@pytest.fixture
async def numeric_template(db_session: AsyncSession) -> InspectionTemplate:
    """含一个数值型检查项（单位 ℃）的模板。"""
    tpl = InspectionTemplate(name=f"数值模板-{uuid.uuid4().hex[:6]}")
    db_session.add(tpl)
    await db_session.flush()
    db_session.add(
        InspectionTemplateItem(
            template_id=tpl.id,
            item_name="出口温度",
            expected_result="25±2",
            data_type="numeric",
            unit="℃",
            sort_order=1,
        )
    )
    await db_session.flush()
    return tpl


@pytest.fixture
async def empty_template(db_session: AsyncSession) -> InspectionTemplate:
    """无检查项的模板（用于验证"无检查项"分支）。"""
    tpl = InspectionTemplate(name=f"空模板-{uuid.uuid4().hex[:6]}")
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _get_template_items(
    db: AsyncSession, template_id: uuid.UUID
) -> list[InspectionTemplateItem]:
    """辅助：取出模板检查项，用于构造记录 dict。"""
    result = await db.execute(
        select(InspectionTemplateItem)
        .where(InspectionTemplateItem.template_id == template_id)
        .order_by(InspectionTemplateItem.sort_order)
    )
    return list(result.scalars().all())


@pytest.fixture
async def inspection_task(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> InspectionTask:
    """已启动（执行中）的单设备巡检任务。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    return await start_task(db_session, task.id, ctx)


# ═══════════ 路线 CRUD + 三级链绑定 ═══════════════════════════


async def test_create_and_get_route(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建路线后应可按 ID 查回，且创建人为当前用户。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"东区路线-{uuid.uuid4().hex[:6]}"}, ctx
    )
    assert route.id is not None
    assert route.created_by == inspector.id
    assert route.is_active is True

    fetched = await get_route_by_id(db_session, route.id)
    assert fetched.id == route.id


async def test_get_route_not_found(db_session: AsyncSession) -> None:
    """查询不存在的路线应抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await get_route_by_id(db_session, uuid.uuid4())


async def test_update_route(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """更新路线名称应生效。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"旧名-{uuid.uuid4().hex[:6]}"}, ctx
    )
    new_name = f"新名-{uuid.uuid4().hex[:6]}"
    updated = await update_route(db_session, route.id, {"name": new_name}, ctx)
    assert updated.name == new_name


async def test_delete_route(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """删除路线后应软删除，再查抛 NotFoundException。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"待删-{uuid.uuid4().hex[:6]}"}, ctx
    )
    assert await delete_route(db_session, route.id, ctx) is True
    with pytest.raises(NotFoundException):
        await get_route_by_id(db_session, route.id)


async def test_set_route_locations_three_level_chain(
    db_session: AsyncSession,
    inspector: User,
    location: Location,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """set_route_locations 应建立 路线→地点→设备→模板 三级绑定链。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"链路-{uuid.uuid4().hex[:6]}"}, ctx
    )
    result = await set_route_locations(
        db_session,
        route.id,
        [
            {
                "location_id": location.id,
                "sort_order": 1,
                "equipments": [
                    {
                        "equipment_id": equipment_with_dept.id,
                        "sort_order": 1,
                        "template_ids": [template_with_items.id],
                    }
                ],
            }
        ],
        ctx,
    )
    assert len(result) == 1
    loc = result[0]
    assert loc.location_id == location.id
    assert len(loc.equipments) == 1
    assert loc.equipments[0].equipment_id == equipment_with_dept.id
    assert len(loc.equipments[0].templates_rel) == 1
    assert loc.equipments[0].templates_rel[0].template_id == template_with_items.id


# ═══════════ create_task 校验矩阵 ═══════════════════════════


async def test_create_route_task_requires_route(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """线路巡检未提供 route_id 应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    with pytest.raises(AppException, match="线路巡检必须选择巡检路线"):
        await create_task(
            db_session,
            {
                "plan_type": "线路巡检",
                "assigned_to": inspector.id,
                "planned_time": datetime.now(UTC),
            },
            ctx,
        )


async def test_create_route_task_ok(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """线路巡检提供 route_id 应成功创建，任务号形如 IT-yyyymmdd-seq，状态待执行。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"L-{uuid.uuid4().hex[:6]}"}, ctx
    )
    task = await create_task(
        db_session,
        {
            "plan_type": "线路巡检",
            "route_id": route.id,
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    assert task.status == "待执行"
    assert task.task_no.startswith(f"IT-{datetime.now(UTC):%Y%m%d}-")
    assert len(task.task_no.split("-")[-1]) == 4  # 4 位序号


async def test_create_equipment_task_requires_equipment(
    db_session: AsyncSession,
    inspector: User,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备巡检未选设备应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    with pytest.raises(AppException, match="设备巡检至少需要选择一台设备"):
        await create_task(
            db_session,
            {
                "plan_type": "设备巡检",
                "template_ids": [template_with_items.id],
                "assigned_to": inspector.id,
                "planned_time": datetime.now(UTC),
            },
            ctx,
        )


async def test_create_equipment_task_requires_template(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备巡检既无 equipment_templates 又无 template_ids 应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    with pytest.raises(AppException, match="设备巡检必须选择检查模板"):
        await create_task(
            db_session,
            {
                "plan_type": "设备巡检",
                "equipment_id": equipment_with_dept.id,
                "assigned_to": inspector.id,
                "planned_time": datetime.now(UTC),
            },
            ctx,
        )


async def test_create_equipment_templates_key_not_in_equipment_ids(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    other_equipment: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """equipment_templates 的 key 不在 equipment_ids 中应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    with pytest.raises(AppException, match="不在已选择的设备列表中"):
        await create_task(
            db_session,
            {
                "plan_type": "设备巡检",
                "equipment_ids": [equipment_with_dept.id],
                "equipment_templates": {
                    str(other_equipment.id): [str(template_with_items.id)]
                },
                "assigned_to": inspector.id,
                "planned_time": datetime.now(UTC),
            },
            ctx,
        )


async def test_create_equipment_templates_each_device_needs_template(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """equipment_templates 中某设备绑定空模板列表应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    with pytest.raises(AppException, match="每台已选设备必须绑定至少一个检查模板"):
        await create_task(
            db_session,
            {
                "plan_type": "设备巡检",
                "equipment_ids": [equipment_with_dept.id],
                "equipment_templates": {str(equipment_with_dept.id): []},
                "assigned_to": inspector.id,
                "planned_time": datetime.now(UTC),
            },
            ctx,
        )


async def test_create_equipment_templates_ok(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """equipment_templates 合法时应创建成功，并以字符串形式存储绑定。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_ids": [equipment_with_dept.id],
            "equipment_templates": {
                str(equipment_with_dept.id): [str(template_with_items.id)]
            },
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    assert task.status == "待执行"
    assert task.equipment_templates == {
        str(equipment_with_dept.id): [str(template_with_items.id)]
    }


async def test_create_equipment_task_flat_template_ids_ok(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """旧扁平 template_ids 方式应放行创建。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    assert task.status == "待执行"
    assert task.template_ids == [str(template_with_items.id)]


# ═══════════ 状态机：start / complete / close ═══════════════


async def test_start_task_transitions_to_running(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """启动任务应从待执行转为执行中并记录 started_at。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    assert task.status == "待执行"
    started = await start_task(db_session, task.id, ctx)
    assert started.status == "执行中"
    assert started.started_at is not None


async def test_complete_task_all_normal(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """全部正常提交后完成任务，总体结果应为正常。"""
    ctx = make_access_ctx(inspector)
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [
            {"template_item_id": items[0].id, "result": "正常"},
            {"template_item_id": items[1].id, "result": "正常"},
        ],
    )
    completed = await complete_task(db_session, inspection_task.id, ctx)
    assert completed.status == "已完成"
    assert completed.overall_result == "正常"
    assert completed.completed_at is not None


async def test_complete_task_with_abnormal(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """存在异常记录时完成任务，总体结果应为异常。"""
    ctx = make_access_ctx(inspector)
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [
            {"template_item_id": items[0].id, "result": "异常", "remark": "超标"},
            {"template_item_id": items[1].id, "result": "正常"},
        ],
    )
    completed = await complete_task(db_session, inspection_task.id, ctx)
    assert completed.overall_result == "异常"


async def test_complete_task_invalid_transition(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """待执行任务直接完成应抛状态机 AppException（须先执行中）。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    with pytest.raises(AppException, match="状态不允许"):
        await complete_task(db_session, task.id, ctx)


async def test_close_running_task_without_work_order(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """无关联工单时可直接关闭执行中的任务。"""
    ctx = make_access_ctx(inspector)
    closed = await close_task(db_session, inspection_task.id, remark="无需处理", ctx=ctx)
    assert closed.status == "已关闭"
    assert closed.closed_at is not None
    assert closed.closure_remark == "无需处理"


# ═══════════ submit_equipment_check 校验 ═══════════════════════


async def test_submit_requires_running_task(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """任务未在执行中时提交检查应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(AppException, match="执行中"):
        await submit_equipment_check(
            db_session,
            task.id,
            equipment_with_dept.id,
            [{"template_item_id": items[0].id, "result": "正常"}],
        )


async def test_submit_unknown_equipment_not_found(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    template_with_items: InspectionTemplate,
) -> None:
    """提交时设备不存在应抛 NotFoundException。"""
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(NotFoundException):
        await submit_equipment_check(
            db_session,
            inspection_task.id,
            uuid.uuid4(),
            [{"template_item_id": items[0].id, "result": "正常"}],
        )


async def test_submit_soft_deleted_equipment_not_found(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """提交时设备已软删除应抛 NotFoundException。"""
    equipment_with_dept.is_deleted = True
    await db_session.flush()
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(NotFoundException):
        await submit_equipment_check(
            db_session,
            inspection_task.id,
            equipment_with_dept.id,
            [{"template_item_id": items[0].id, "result": "正常"}],
        )


async def test_submit_single_device_mismatch(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    other_equipment: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """单设备任务提交不匹配的设备应抛 AppException。"""
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(AppException, match="不匹配此巡检任务的设备"):
        await submit_equipment_check(
            db_session,
            inspection_task.id,
            other_equipment.id,
            [{"template_item_id": items[0].id, "result": "正常"}],
        )


async def test_submit_multi_device_not_in_task(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    other_equipment: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """多设备任务提交不在 equipment_ids 中的设备应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_ids": [equipment_with_dept.id],
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(AppException, match="不在此巡检任务中"):
        await submit_equipment_check(
            db_session,
            task.id,
            other_equipment.id,
            [{"template_item_id": items[0].id, "result": "正常"}],
        )


async def test_submit_route_device_not_on_route(
    db_session: AsyncSession,
    inspector: User,
    location: Location,
    equipment_with_dept: Equipment,
    other_equipment: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """线路巡检提交不在路线上的设备应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"R-{uuid.uuid4().hex[:6]}"}, ctx
    )
    await set_route_locations(
        db_session,
        route.id,
        [
            {
                "location_id": location.id,
                "sort_order": 1,
                "equipments": [
                    {
                        "equipment_id": equipment_with_dept.id,
                        "sort_order": 1,
                        "template_ids": [template_with_items.id],
                    }
                ],
            }
        ],
        ctx,
    )
    task = await create_task(
        db_session,
        {
            "plan_type": "线路巡检",
            "route_id": route.id,
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(AppException, match="不属于此巡检路线"):
        await submit_equipment_check(
            db_session,
            task.id,
            other_equipment.id,
            [{"template_item_id": items[0].id, "result": "正常"}],
        )


async def test_submit_route_device_on_route_ok(
    db_session: AsyncSession,
    inspector: User,
    location: Location,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """线路巡检提交路线上的设备应成功，检查项来自路线三级链绑定。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"R-{uuid.uuid4().hex[:6]}"}, ctx
    )
    await set_route_locations(
        db_session,
        route.id,
        [
            {
                "location_id": location.id,
                "sort_order": 1,
                "equipments": [
                    {
                        "equipment_id": equipment_with_dept.id,
                        "sort_order": 1,
                        "template_ids": [template_with_items.id],
                    }
                ],
            }
        ],
        ctx,
    )
    task = await create_task(
        db_session,
        {
            "plan_type": "线路巡检",
            "route_id": route.id,
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    items = await _get_template_items(db_session, template_with_items.id)
    created = await submit_equipment_check(
        db_session,
        task.id,
        equipment_with_dept.id,
        [{"template_item_id": items[0].id, "result": "正常"}],
    )
    assert len(created) == 1


async def test_submit_abnormal_requires_value_or_remark(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """异常项既无实际值又无备注应抛 AppException。"""
    items = await _get_template_items(db_session, template_with_items.id)
    with pytest.raises(AppException, match="检查项异常时必须填写实际值或备注"):
        await submit_equipment_check(
            db_session,
            inspection_task.id,
            equipment_with_dept.id,
            [{"template_item_id": items[0].id, "result": "异常"}],
        )


async def test_submit_replaces_old_records(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """重复提交同设备应替换旧记录（先软删后建），仅保留最新一批。"""
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [
            {"template_item_id": items[0].id, "result": "正常"},
            {"template_item_id": items[1].id, "result": "正常"},
        ],
    )
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [{"template_item_id": items[0].id, "result": "正常"}],
    )
    result = await db_session.execute(
        select(InspectionRecord).where(
            InspectionRecord.task_id == inspection_task.id,
            InspectionRecord.equipment_id == equipment_with_dept.id,
            InspectionRecord.is_deleted == False,  # noqa: E712
        )
    )
    alive = list(result.scalars().all())
    assert len(alive) == 1


# ═══════════ 数值型检查项 ═══════════════════════════════════


async def test_submit_numeric_value_parsed(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    numeric_template: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """数值型检查项的合法实测值应被解析写入 numeric_value。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [numeric_template.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    items = await _get_template_items(db_session, numeric_template.id)
    created = await submit_equipment_check(
        db_session,
        task.id,
        equipment_with_dept.id,
        [{"template_item_id": items[0].id, "result": "正常", "actual_value": "25.3"}],
    )
    assert created[0].numeric_value == Decimal("25.3")


async def test_submit_numeric_value_dirty_rejected(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    numeric_template: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """数值型检查项混入单位/文字的脏值应被拒绝并提示填纯数字。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [numeric_template.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    items = await _get_template_items(db_session, numeric_template.id)
    with pytest.raises(AppException, match="纯数字"):
        await submit_equipment_check(
            db_session,
            task.id,
            equipment_with_dept.id,
            [
                {
                    "template_item_id": items[0].id,
                    "result": "正常",
                    "actual_value": "25.3℃",
                }
            ],
        )


# ═══════════ 异常自动建单 ═══════════════════════════════════
# (从 test_inspection_work_order.py 搬迁并核对断言)


async def test_submit_with_anomaly_creates_work_order(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """提交含异常结果的检查记录应自动创建工单。"""
    items = await _get_template_items(db_session, template_with_items.id)
    created = await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [
            {"template_item_id": items[0].id, "result": "异常", "remark": "温度超标"},
            {"template_item_id": items[1].id, "result": "正常"},
        ],
    )
    assert len(created) == 2

    pending = await get_pending_work_orders_by_inspection_task(
        db_session, inspection_task.id
    )
    assert len(pending) == 1
    wo = pending[0]
    assert wo.order_type == "异常处理"
    assert wo.status == "待处理"
    assert wo.equipment_id == equipment_with_dept.id
    assert wo.inspection_task_id == inspection_task.id
    assert wo.priority == "高"
    assert "温度检查" in (wo.fault_description or "")
    assert wo.responsible_person_id is not None


async def test_submit_all_normal_no_work_order(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """全部正常的检查结果不应创建工单。"""
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [
            {"template_item_id": items[0].id, "result": "正常"},
            {"template_item_id": items[1].id, "result": "正常"},
        ],
    )
    pending = await get_pending_work_orders_by_inspection_task(
        db_session, inspection_task.id
    )
    assert len(pending) == 0


async def test_duplicate_work_order_not_created(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """重复提交异常结果不应创建重复工单。"""
    items = await _get_template_items(db_session, template_with_items.id)
    records = [
        {"template_item_id": items[0].id, "result": "异常", "remark": "温度超标"},
    ]
    await submit_equipment_check(
        db_session, inspection_task.id, equipment_with_dept.id, records
    )
    await submit_equipment_check(
        db_session, inspection_task.id, equipment_with_dept.id, records
    )
    pending = await get_pending_work_orders_by_inspection_task(
        db_session, inspection_task.id
    )
    assert len(pending) == 1


async def test_anomaly_work_order_metadata(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """异常工单：reporter_id=任务执行人、关联任务、不改设备状态。"""
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [{"template_item_id": items[0].id, "result": "异常", "remark": "温度超标"}],
    )
    pending = await get_pending_work_orders_by_inspection_task(
        db_session, inspection_task.id
    )
    wo = pending[0]
    assert wo.reporter_id == inspector.id
    assert wo.inspection_task_id == inspection_task.id
    assert wo.original_equipment_status == "在用"

    # 设备状态不应被异常工单改动
    eq = await db_session.get(Equipment, equipment_with_dept.id)
    assert eq is not None
    assert eq.status == "在用"


async def test_close_blocked_by_pending_work_order(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """存在未处理工单时关闭巡检任务应抛出 AppException。"""
    ctx = make_access_ctx(inspector)
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [{"template_item_id": items[0].id, "result": "异常", "remark": "温度超标"}],
    )
    await complete_task(db_session, inspection_task.id, ctx)

    with pytest.raises(AppException) as exc_info:
        await close_task(db_session, inspection_task.id, ctx=ctx)
    assert "未处理" in exc_info.value.message
    assert exc_info.value.detail_msg is not None
    assert len(exc_info.value.detail_msg["pending_work_orders"]) == 1


async def test_close_succeeds_after_work_order_closed(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """所有关联工单关闭后，巡检任务可以正常关闭。"""
    ctx = make_access_ctx(inspector)
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [{"template_item_id": items[0].id, "result": "异常", "remark": "温度超标"}],
    )
    await complete_task(db_session, inspection_task.id, ctx)

    await db_session.execute(
        update(WorkOrder)
        .where(WorkOrder.inspection_task_id == inspection_task.id)
        .values(status="已关闭")
    )
    await db_session.flush()

    closed_task = await close_task(db_session, inspection_task.id, ctx=ctx)
    assert closed_task.status == "已关闭"


async def test_work_order_no_responsible_person(
    db_session: AsyncSession,
    inspector: User,
    location: Location,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备没有归属部门时，工单仍应创建但责任人为 None。"""
    ctx = make_access_ctx(inspector)
    eq_no_dept = Equipment(
        equipment_no=f"EQ-{uuid.uuid4().hex[:8]}",
        name="R-202反应釜",
        location_id=location.id,
        status="在用",
        importance="中",
        department_id=None,
    )
    db_session.add(eq_no_dept)
    await db_session.flush()

    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": eq_no_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)

    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        task.id,
        eq_no_dept.id,
        [{"template_item_id": items[0].id, "result": "异常", "remark": "温度异常"}],
    )
    pending = await get_pending_work_orders_by_inspection_task(db_session, task.id)
    assert len(pending) == 1
    wo = pending[0]
    assert wo.responsible_person_id is None
    assert wo.priority == "中"


# ═══════════ submit_route_check ═══════════════════════════════


async def test_submit_route_check_requires_running(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """线路巡检提交时任务非执行中应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"R-{uuid.uuid4().hex[:6]}"}, ctx
    )
    task = await create_task(
        db_session,
        {
            "plan_type": "线路巡检",
            "route_id": route.id,
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    with pytest.raises(AppException, match="执行中"):
        await submit_route_check(db_session, task.id, "正常", ctx=ctx)


async def test_submit_route_check_rejects_equipment_task(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备巡检任务调用线路提交应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    with pytest.raises(AppException, match="仅线路巡检任务支持此操作"):
        await submit_route_check(db_session, inspection_task.id, "正常", ctx=ctx)


async def test_submit_route_check_ok(
    db_session: AsyncSession,
    inspector: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """线路巡检提交应设置总体结果、现场描述并完成任务。"""
    ctx = make_access_ctx(inspector)
    route = await create_route(
        db_session, {"name": f"R-{uuid.uuid4().hex[:6]}"}, ctx
    )
    task = await create_task(
        db_session,
        {
            "plan_type": "线路巡检",
            "route_id": route.id,
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    done = await submit_route_check(
        db_session, task.id, "正常", route_summary="现场无异常", ctx=ctx
    )
    assert done.status == "已完成"
    assert done.overall_result == "正常"
    assert done.route_summary == "现场无异常"


# ═══════════ skip_equipment_check ═══════════════════════════════


async def test_skip_requires_running_task(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """任务非执行中时跳过设备应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [template_with_items.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    with pytest.raises(AppException, match="执行中"):
        await skip_equipment_check(db_session, task.id, equipment_with_dept.id)


async def test_skip_no_check_items(
    db_session: AsyncSession,
    inspector: User,
    equipment_with_dept: Equipment,
    empty_template: InspectionTemplate,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备无关联检查项时跳过应抛 AppException。"""
    ctx = make_access_ctx(inspector)
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment_with_dept.id,
            "template_ids": [empty_template.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    task = await start_task(db_session, task.id, ctx)
    with pytest.raises(AppException, match="没有关联检查项"):
        await skip_equipment_check(db_session, task.id, equipment_with_dept.id)


async def test_skip_creates_skip_records(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """跳过设备应为该设备所有检查项创建"跳过"记录。"""
    items = await _get_template_items(db_session, template_with_items.id)
    created = await skip_equipment_check(
        db_session, inspection_task.id, equipment_with_dept.id, reason="停机维修"
    )
    assert len(created) == len(items)
    assert all(r.result == "跳过" for r in created)
    assert all(r.remark == "停机维修" for r in created)


async def test_skip_replaces_existing_records(
    db_session: AsyncSession,
    inspection_task: InspectionTask,
    equipment_with_dept: Equipment,
    template_with_items: InspectionTemplate,
) -> None:
    """先提交检查再跳过，跳过应替换旧记录（先删后建）。"""
    items = await _get_template_items(db_session, template_with_items.id)
    await submit_equipment_check(
        db_session,
        inspection_task.id,
        equipment_with_dept.id,
        [
            {"template_item_id": items[0].id, "result": "正常"},
            {"template_item_id": items[1].id, "result": "正常"},
        ],
    )
    await skip_equipment_check(
        db_session, inspection_task.id, equipment_with_dept.id
    )
    result = await db_session.execute(
        select(InspectionRecord).where(
            InspectionRecord.task_id == inspection_task.id,
            InspectionRecord.equipment_id == equipment_with_dept.id,
            InspectionRecord.is_deleted == False,  # noqa: E712
        )
    )
    alive = list(result.scalars().all())
    assert len(alive) == len(items)
    assert all(r.result == "跳过" for r in alive)


# ═══════════ save_photo_from_base64 校验（轻量单元，mock 存储 IO） ═══


async def test_photo_decode_failure(db_session: AsyncSession) -> None:
    """无效 base64 应抛 AppException。"""
    with pytest.raises(AppException, match="base64 解码失败"):
        await save_photo_from_base64(
            db_session, uuid.uuid4(), uuid.uuid4(), "not valid base64!!!"
        )


async def test_photo_too_large(db_session: AsyncSession) -> None:
    """超过 10MB 的图片应抛 AppException。"""
    oversized = base64.b64encode(b"\x00" * (10 * 1024 * 1024 + 100)).decode()
    with pytest.raises(AppException, match="超过上限"):
        await save_photo_from_base64(
            db_session, uuid.uuid4(), uuid.uuid4(), oversized
        )


async def test_photo_too_small(db_session: AsyncSession) -> None:
    """小于 64 字节的数据应抛 AppException。"""
    tiny = base64.b64encode(b"\xff\xd8\xff").decode()
    with pytest.raises(AppException, match="过小"):
        await save_photo_from_base64(
            db_session, uuid.uuid4(), uuid.uuid4(), tiny
        )


@pytest.mark.parametrize(
    ("header", "expected_ext"),
    [
        (b"\xff\xd8\xff\xe0", "jpg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"RIFF\x00\x00\x00\x00WEBP", "webp"),
        (b"BM\x00\x00", "bmp"),
    ],
)
async def test_photo_magic_bytes_extension(
    db_session: AsyncSession, header: bytes, expected_ext: str
) -> None:
    """magic bytes 应决定生成文件名的扩展名（mock 存储与落库 IO）。"""
    raw = header + b"\x00" * 100  # 保证 >= 64 字节
    b64 = base64.b64encode(raw).decode()

    captured: dict[str, object] = {}

    async def _fake_create_photo(db: object, data: dict[str, object]) -> object:
        captured.update(data)
        return MagicMock()

    with (
        patch.object(svc, "minio_enabled", return_value=True),
        patch.object(svc, "upload_object", new=MagicMock()),
        patch(
            "app.modules.equipment.service.inspection.repo.create_photo",
            new=AsyncMock(side_effect=_fake_create_photo),
        ),
    ):
        await save_photo_from_base64(
            db_session, uuid.uuid4(), uuid.uuid4(), b64
        )

    assert str(captured["file_name"]).endswith(f".{expected_ext}")
