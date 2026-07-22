"""维护计划域测试：创建/更新/日期计算/到期查询/定时生成工单/模型约束。

覆盖 app.modules.equipment 维护计划的业务规则（service + repository + model）。
断言以业务规则为准，而非照抄实现。
"""

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import time as app_time
from app.core.exceptions import AppException, ForbiddenException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import (
    Equipment,
    EquipmentCategory,
    EquipmentCategoryLink,
    Location,
    MaintenancePlan,
    WorkOrder,
)
from app.modules.equipment.schemas import (
    MaintenancePlanCreate,
    MaintenancePlanUpdate,
    WorkOrderComplete,
)
from app.modules.equipment.service import (
    complete_work_order,
    create_maintenance_plan,
    generate_due_work_orders,
    get_maintenance_plan_by_id,
    get_overdue_maintenance_plans,
    update_maintenance_plan,
)
from app.modules.equipment.service.maintenance_plan import (
    _add_months,
    _calculate_next_maintenance_date,
)
from app.platform.identity.models import User

# ══════════════════════════ Fixtures ══════════════════════════


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    """计划创建人（用于 created_by 归属）。"""
    user = User(name="计划创建人", employee_no=f"EMP-OW-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def executor(db_session: AsyncSession) -> User:
    """执行人（无飞书账号，不触发通知分支）。"""
    user = User(name="维护执行人", employee_no=f"EMP-EX-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def executor_with_feishu(db_session: AsyncSession) -> User:
    """执行人：带 feishu_user_id，才会触发通知分支。"""
    user = User(
        name="维护执行人",
        employee_no=f"EMP-EX-{uuid.uuid4().hex[:8]}",
        feishu_user_id=f"fs_{uuid.uuid4().hex[:8]}",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def location(db_session: AsyncSession) -> Location:
    """一个位置。"""
    loc = Location(name="维护车间", code=f"WS-M-{uuid.uuid4().hex[:6]}")
    db_session.add(loc)
    await db_session.flush()
    return loc


@pytest.fixture
async def due_equipment(db_session: AsyncSession, location: Location) -> Equipment:
    """完好设备。"""
    equipment = Equipment(
        equipment_no=f"EQ-M-{uuid.uuid4().hex[:8]}",
        name="待维护设备",
        location_id=location.id,
        status="完好",
    )
    db_session.add(equipment)
    await db_session.flush()
    return equipment


async def _make_category_with_equipment(
    db: AsyncSession,
    location: Location,
    status: str = "完好",
) -> tuple[EquipmentCategory, Equipment]:
    """创建一个分类并挂一台设备（通过关联表）。返回 (分类, 设备)。"""
    category = EquipmentCategory(
        name="反应釜类",
        code=f"CAT-{uuid.uuid4().hex[:8]}",
    )
    db.add(category)
    await db.flush()

    equipment = Equipment(
        equipment_no=f"EQ-C-{uuid.uuid4().hex[:8]}",
        name="分类设备",
        location_id=location.id,
        status=status,
    )
    db.add(equipment)
    await db.flush()

    link = EquipmentCategoryLink(
        equipment_id=equipment.id, category_id=category.id
    )
    db.add(link)
    await db.flush()
    return category, equipment


# ══════════════════════ 创建维护计划 ══════════════════════


async def test_create_plan_computes_next_from_last(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """提供 last_maintenance_date 时应自动计算 next_maintenance_date。"""
    data = MaintenancePlanCreate(
        equipment_id=due_equipment.id,
        plan_name="月度保养",
        frequency=1,
        frequency_unit="月",
        last_maintenance_date=date(2026, 1, 15),
        executor_id=executor.id,
    )
    plan = await create_maintenance_plan(db_session, data, make_access_ctx(owner))

    assert plan.next_maintenance_date == date(2026, 2, 15)
    assert plan.created_by == owner.id
    assert plan.equipment_id == due_equipment.id
    assert plan.category_id is None


async def test_create_plan_no_last_date_leaves_next_none(
    db_session: AsyncSession,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """无 last_maintenance_date 时不自动计算 next（保持 None）。"""
    data = MaintenancePlanCreate(
        category_id=uuid.uuid4(),
        plan_name="分类保养",
        frequency=3,
        frequency_unit="月",
    )
    plan = await create_maintenance_plan(db_session, data, make_access_ctx(owner))

    assert plan.next_maintenance_date is None
    assert plan.category_id is not None
    assert plan.equipment_id is None


def test_schema_rejects_both_equipment_and_category() -> None:
    """equipment_id 与 category_id 同时提供应被 schema 拒绝。"""
    with pytest.raises(ValueError):
        MaintenancePlanCreate(
            equipment_id=uuid.uuid4(),
            category_id=uuid.uuid4(),
            plan_name="x",
            frequency=1,
            frequency_unit="月",
        )


def test_schema_rejects_neither_equipment_nor_category() -> None:
    """两者都不提供应被 schema 拒绝。"""
    with pytest.raises(ValueError):
        MaintenancePlanCreate(
            plan_name="x",
            frequency=1,
            frequency_unit="月",
        )


async def test_create_plan_service_guard_rejects_both(
    db_session: AsyncSession,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """service 层二次保险：同时提供 equipment_id 与 category_id 抛 AppException。

    绕过 schema 校验（model_construct）直接验证 service 守卫。
    """
    data = MaintenancePlanCreate.model_construct(
        equipment_id=uuid.uuid4(),
        category_id=uuid.uuid4(),
        plan_name="x",
        frequency=1,
        frequency_unit="月",
        last_maintenance_date=None,
    )
    with pytest.raises(AppException):
        await create_maintenance_plan(db_session, data, make_access_ctx(owner))


async def test_create_plan_service_guard_rejects_neither(
    db_session: AsyncSession,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """service 层二次保险：两者都为空抛 AppException。"""
    data = MaintenancePlanCreate.model_construct(
        equipment_id=None,
        category_id=None,
        plan_name="x",
        frequency=1,
        frequency_unit="月",
        last_maintenance_date=None,
    )
    with pytest.raises(AppException):
        await create_maintenance_plan(db_session, data, make_access_ctx(owner))


# ══════════════════════ 更新维护计划 ══════════════════════


async def test_update_recomputes_next_when_last_changes(
    db_session: AsyncSession,
    due_equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """更新 last_maintenance_date 后应基于频率重算 next。"""
    ctx = make_access_ctx(owner)
    plan = await create_maintenance_plan(
        db_session,
        MaintenancePlanCreate(
            equipment_id=due_equipment.id,
            plan_name="季度保养",
            frequency=3,
            frequency_unit="月",
            last_maintenance_date=date(2026, 1, 10),
        ),
        ctx,
    )
    assert plan.next_maintenance_date == date(2026, 4, 10)

    updated = await update_maintenance_plan(
        db_session,
        plan.id,
        MaintenancePlanUpdate(last_maintenance_date=date(2026, 2, 10)),
        ctx,
    )
    assert updated.last_maintenance_date == date(2026, 2, 10)
    assert updated.next_maintenance_date == date(2026, 5, 10)


async def test_update_clears_next_when_last_cleared(
    db_session: AsyncSession,
    due_equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """显式清空 last_maintenance_date 应同步清空 next。"""
    ctx = make_access_ctx(owner)
    plan = await create_maintenance_plan(
        db_session,
        MaintenancePlanCreate(
            equipment_id=due_equipment.id,
            plan_name="月度保养",
            frequency=1,
            frequency_unit="月",
            last_maintenance_date=date(2026, 1, 10),
        ),
        ctx,
    )
    assert plan.next_maintenance_date is not None

    updated = await update_maintenance_plan(
        db_session,
        plan.id,
        MaintenancePlanUpdate(last_maintenance_date=None),
        ctx,
    )
    assert updated.last_maintenance_date is None
    assert updated.next_maintenance_date is None


async def test_update_recomputes_next_when_frequency_changes(
    db_session: AsyncSession,
    due_equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """仅改频率（last 沿用旧值）也应重算 next。"""
    ctx = make_access_ctx(owner)
    plan = await create_maintenance_plan(
        db_session,
        MaintenancePlanCreate(
            equipment_id=due_equipment.id,
            plan_name="保养",
            frequency=1,
            frequency_unit="月",
            last_maintenance_date=date(2026, 1, 10),
        ),
        ctx,
    )
    assert plan.next_maintenance_date == date(2026, 2, 10)

    updated = await update_maintenance_plan(
        db_session,
        plan.id,
        MaintenancePlanUpdate(frequency=2),
        ctx,
    )
    assert updated.frequency == 2
    assert updated.next_maintenance_date == date(2026, 3, 10)


async def test_update_forbidden_for_other_user(
    db_session: AsyncSession,
    due_equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """受限数据范围下，无权修改他人创建的计划。"""
    plan = await create_maintenance_plan(
        db_session,
        MaintenancePlanCreate(
            equipment_id=due_equipment.id,
            plan_name="保养",
            frequency=1,
            frequency_unit="月",
        ),
        make_access_ctx(owner),
    )

    other = User(name="他人", employee_no=f"EMP-OT-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    await db_session.flush()
    restricted_ctx = EquipmentAccessContext(
        user=other, data_scope="self_only", department_user_ids=[]
    )

    with pytest.raises(ForbiddenException):
        await update_maintenance_plan(
            db_session,
            plan.id,
            MaintenancePlanUpdate(plan_name="改名"),
            restricted_ctx,
        )


# ══════════════════════ 下次日期计算（纯函数） ══════════════════════


@pytest.mark.parametrize(
    ("last", "freq", "unit", "expected"),
    [
        (date(2026, 1, 1), 10, "天", date(2026, 1, 11)),
        (date(2026, 1, 1), 2, "周", date(2026, 1, 15)),
        (date(2026, 1, 15), 1, "月", date(2026, 2, 15)),
        (date(2026, 12, 15), 2, "月", date(2027, 2, 15)),
        (date(2026, 1, 15), 1, "年", date(2027, 1, 15)),
    ],
)
def test_calculate_next_maintenance_date(
    last: date, freq: int, unit: str, expected: date
) -> None:
    """各频率单位下的下次维护日期计算。"""
    assert _calculate_next_maintenance_date(last, freq, unit) == expected


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        # 1/31 + 1月 → 2月末（2026 非闰 → 28）
        (date(2026, 1, 31), 1, date(2026, 2, 28)),
        # 1/31 + 1月 → 2月末（2024 闰 → 29）
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        # 跨年
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        # 闰日 + 12月 → 落到非闰年 2月末
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
    ],
)
def test_add_months_handles_month_end(
    start: date, months: int, expected: date
) -> None:
    """_add_months 应正确处理月末溢出（闰/非闰年、跨年）。"""
    assert _add_months(start, months) == expected


# ══════════════════════ 到期查询 ══════════════════════


async def test_get_overdue_includes_due_excludes_future(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """默认 30 天内到期计划应被返回，远期计划不返回。"""
    today = app_time.today()
    due_plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="即将到期",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=today + timedelta(days=10),
        executor_id=executor.id,
        status="启用",
        created_by=owner.id,
    )
    future_plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="远期",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=today + timedelta(days=90),
        executor_id=executor.id,
        status="启用",
        created_by=owner.id,
    )
    db_session.add_all([due_plan, future_plan])
    await db_session.flush()

    overdue = await get_overdue_maintenance_plans(
        db_session, make_access_ctx(owner), days=30
    )
    ids = {p.id for p in overdue}
    assert due_plan.id in ids
    assert future_plan.id not in ids


async def test_get_overdue_excludes_disabled_plans(
    db_session: AsyncSession,
    due_equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """停用计划即使到期也不返回。"""
    today = app_time.today()
    disabled = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="已停用",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=today,
        status="停用",
        created_by=owner.id,
    )
    db_session.add(disabled)
    await db_session.flush()

    overdue = await get_overdue_maintenance_plans(
        db_session, make_access_ctx(owner), days=30
    )
    assert disabled.id not in {p.id for p in overdue}


# ══════════════════════ 定时生成工单 ══════════════════════


async def _wo_count_for_plan(db: AsyncSession, plan_id: uuid.UUID) -> int:
    """统计某计划已生成的工单数。"""
    return await db.scalar(  # type: ignore[return-value]
        select(func.count())
        .select_from(WorkOrder)
        .where(WorkOrder.maintenance_plan_id == plan_id)
    )


async def test_generate_due_creates_wo_and_notifies(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor_with_feishu: User,
    _mock_notifications: AsyncMock,
) -> None:
    """到期维护计划应自动生成工单，并飞书通知执行人（mock 拦截，不真发）。"""
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="月度保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=app_time.today(),  # 今天到期
        executor_id=executor_with_feishu.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    created, _skipped = await generate_due_work_orders(db_session, advance_days=0)

    # ① 本计划生成了工单
    assert await _wo_count_for_plan(db_session, plan.id) == 1
    assert created >= 1
    # ② 防重字段已推进
    assert plan.last_generated_date == plan.next_maintenance_date
    # ③ 通知发给了正确的执行人（第 4 个位置参数 = executor_feishu_id）
    assert any(
        c.args[3] == executor_with_feishu.feishu_user_id
        for c in _mock_notifications.await_args_list
    )


async def test_generate_due_skips_when_already_generated(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor_with_feishu: User,
    _mock_notifications: AsyncMock,
) -> None:
    """已生成过（last_generated_date >= next）的计划应跳过，不重复建单/通知。"""
    today = app_time.today()
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="月度保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=today,
        last_generated_date=today,  # 已生成
        executor_id=executor_with_feishu.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    assert await _wo_count_for_plan(db_session, plan.id) == 0
    assert not any(
        c.args[3] == executor_with_feishu.feishu_user_id
        for c in _mock_notifications.await_args_list
    )


async def test_generate_sets_expected_work_order_fields(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
) -> None:
    """生成的工单字段应符合约定（计划维护/中/无报修人/责任=指派=执行人/计划开始日）。"""
    next_date = app_time.today()
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=next_date,
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    wo = (
        await db_session.execute(
            select(WorkOrder).where(WorkOrder.maintenance_plan_id == plan.id)
        )
    ).scalar_one()
    assert wo.order_type == "计划维护"
    assert wo.priority == "中"
    # 已自动派工执行人 → 直接进「执行中」并写开工时间
    assert wo.status == "执行中"
    assert wo.started_at is not None
    assert wo.reporter_id is None
    assert wo.responsible_person_id == executor.id
    assert wo.assignee_id == executor.id
    assert wo.planned_start_date == next_date


async def test_generate_auto_execute_off_assigns_but_stays_pending(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
) -> None:
    """auto_execute=False 时有执行人的工单仍自动派工，但保持「待处理」不开工。"""
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=app_time.today(),
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0, auto_execute=False)

    wo = (
        await db_session.execute(
            select(WorkOrder).where(WorkOrder.maintenance_plan_id == plan.id)
        )
    ).scalar_one()
    assert wo.status == "待处理"
    assert wo.started_at is None
    # 派工信息不受 auto_execute 影响
    assert wo.responsible_person_id == executor.id
    assert wo.assignee_id == executor.id
    assert wo.assigned_at is not None


async def test_generate_auto_execute_on_without_executor_stays_pending(
    db_session: AsyncSession,
    due_equipment: Equipment,
) -> None:
    """auto_execute=True 但计划无执行人时，工单保持「待处理」且不派工。"""
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=app_time.today(),
        executor_id=None,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0, auto_execute=True)

    wo = (
        await db_session.execute(
            select(WorkOrder).where(WorkOrder.maintenance_plan_id == plan.id)
        )
    ).scalar_one()
    assert wo.status == "待处理"
    assert wo.started_at is None
    assert wo.assignee_id is None
    assert wo.assigned_at is None


async def test_generate_device_level_does_not_advance_next(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
) -> None:
    """设备级计划生成工单后不推进 next（由工单完成推进），只置 last_generated。"""
    next_date = app_time.today()
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=next_date,
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    assert plan.next_maintenance_date == next_date  # 未推进
    assert plan.last_generated_date == next_date  # 已置防重


async def test_generate_category_creates_wo_and_advances_next(
    db_session: AsyncSession,
    location: Location,
    executor: User,
) -> None:
    """分类级计划：为分类下可用设备建单，并在扫描处推进 next。"""
    category, equipment = await _make_category_with_equipment(db_session, location)
    next_date = app_time.today()
    plan = MaintenancePlan(
        category_id=category.id,
        plan_name="分类月保",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=next_date,
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    # 为分类下设备建了单，且 planned_start_date 用的是原始 next
    wo = (
        await db_session.execute(
            select(WorkOrder).where(WorkOrder.maintenance_plan_id == plan.id)
        )
    ).scalar_one()
    assert wo.equipment_id == equipment.id
    assert wo.planned_start_date == next_date

    # 分类级：next 推进一个周期，last_generated 保持为原始日期（防重：记录本次已生成的周期）
    expected_next = _add_months(next_date, 1)
    assert plan.next_maintenance_date == expected_next
    assert plan.last_generated_date == next_date


async def test_generate_category_skips_when_no_available_equipment(
    db_session: AsyncSession,
    executor: User,
) -> None:
    """分类下无可用设备时跳过，不建单、不推进。"""
    category = EquipmentCategory(name="空分类", code=f"CAT-{uuid.uuid4().hex[:8]}")
    db_session.add(category)
    await db_session.flush()

    next_date = app_time.today()
    plan = MaintenancePlan(
        category_id=category.id,
        plan_name="空分类保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=next_date,
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    assert await _wo_count_for_plan(db_session, plan.id) == 0
    assert plan.next_maintenance_date == next_date
    assert plan.last_generated_date is not None  # 防重：无可用设备时也置防重，避免无限重试


async def test_generate_skips_scrapped_equipment(
    db_session: AsyncSession,
    location: Location,
    executor: User,
) -> None:
    """设备状态为报废时跳过该设备，不建单、不置防重。"""
    equipment = Equipment(
        equipment_no=f"EQ-S-{uuid.uuid4().hex[:8]}",
        name="报废设备",
        location_id=location.id,
        status="报废",
    )
    db_session.add(equipment)
    await db_session.flush()

    next_date = app_time.today()
    plan = MaintenancePlan(
        equipment_id=equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=next_date,
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    assert await _wo_count_for_plan(db_session, plan.id) == 0
    assert plan.last_generated_date is not None  # 防重：避免下次调度无限重试


async def test_generate_skips_deleted_equipment(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
) -> None:
    """设备已软删时跳过，不建单。"""
    due_equipment.is_deleted = True
    await db_session.flush()

    next_date = app_time.today()
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=next_date,
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)

    assert await _wo_count_for_plan(db_session, plan.id) == 0
    assert plan.last_generated_date is not None  # 防重：避免下次调度无限重试


# ══════════════════════ 工单完成推进计划（设备级） ══════════════════════


async def test_device_plan_advances_on_work_order_completion(
    db_session: AsyncSession,
    due_equipment: Equipment,
    executor: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备级计划：工单完成后推进 last/next 并重置 last_generated。"""
    plan = MaintenancePlan(
        equipment_id=due_equipment.id,
        plan_name="保养",
        plan_type="预防性维护",
        frequency=1,
        frequency_unit="月",
        next_maintenance_date=app_time.today(),
        executor_id=executor.id,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    await generate_due_work_orders(db_session, advance_days=0)
    assert plan.last_generated_date is not None  # 生成后已置防重

    wo = (
        await db_session.execute(
            select(WorkOrder).where(WorkOrder.maintenance_plan_id == plan.id)
        )
    ).scalar_one()

    ctx = make_access_ctx(executor)
    # 带执行人的自动工单已直接进「执行中」,无需再手动 start
    assert wo.status == "执行中"
    await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="保养完成"), ctx
    )

    today = date.today()
    await db_session.refresh(plan)
    assert plan.last_maintenance_date == today
    assert plan.next_maintenance_date == _add_months(today, 1)
    assert plan.last_generated_date is None  # 防重锁已重置


# ══════════════════════ 模型 CheckConstraint ══════════════════════


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_type", "非法类型"),
        ("frequency_unit", "刻"),
        ("status", "未知"),
    ],
)
async def test_model_check_constraints_reject_invalid(
    db_session: AsyncSession,
    due_equipment: Equipment,
    field: str,
    value: str,
) -> None:
    """plan_type/frequency_unit/status 非法值应被 CheckConstraint 拒绝。"""
    kwargs: dict[str, object] = {
        "equipment_id": due_equipment.id,
        "plan_name": "约束测试",
        "plan_type": "预防性维护",
        "frequency": 1,
        "frequency_unit": "月",
        "status": "启用",
    }
    kwargs[field] = value
    db_session.add(MaintenancePlan(**kwargs))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_get_maintenance_plan_by_id_roundtrip(
    db_session: AsyncSession,
    due_equipment: Equipment,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    owner: User,
) -> None:
    """创建后可按 ID 读回。"""
    plan = await create_maintenance_plan(
        db_session,
        MaintenancePlanCreate(
            equipment_id=due_equipment.id,
            plan_name="保养",
            frequency=1,
            frequency_unit="月",
        ),
        make_access_ctx(owner),
    )
    fetched = await get_maintenance_plan_by_id(db_session, plan.id)
    assert fetched.id == plan.id
    assert fetched.plan_name == "保养"
