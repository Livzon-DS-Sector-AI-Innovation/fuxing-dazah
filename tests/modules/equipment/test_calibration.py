"""校准域（校准计划 + 校准记录）测试。

覆盖 service 层业务规则、模型 CheckConstraint 约束，以及 API 端到端。
断言以业务规则为准，而非照抄现有实现。
"""

import uuid
from collections.abc import Callable
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, NotFoundException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import (
    CalibrationPlan,
    CalibrationRecord,
    Equipment,
    Location,
)
from app.modules.equipment.schemas import (
    CalibrationPlanCreate,
    CalibrationPlanUpdate,
    CalibrationRecordCreate,
)
from app.modules.equipment.service import (
    create_calibration_plan,
    create_calibration_record,
    delete_calibration_plan,
    get_calibration_plan_by_id,
    get_calibration_plans,
    get_calibration_record_by_id,
    get_calibration_records,
    get_overdue_calibration_plans,
    update_calibration_plan,
)
from app.platform.identity.models import User


def _uid() -> str:
    """生成 8 位十六进制随机后缀，避免共享测试库唯一键冲突。"""
    return uuid.uuid4().hex[:8]


# ==================== Service 层 fixtures ====================


@pytest.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """创建测试用户。"""
    user = User(name="校准员", employee_no=f"EMP-CAL-{_uid()}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def sample_equipment(db_session: AsyncSession) -> Equipment:
    """创建测试用在用设备。"""
    location = Location(name="校准车间", code=f"WS-CAL-{_uid()}")
    db_session.add(location)
    await db_session.flush()

    equipment = Equipment(
        equipment_no=f"EQ-CAL-{_uid()}",
        name="压力表",
        location_id=location.id,
        status="在用",
    )
    db_session.add(equipment)
    await db_session.flush()
    return equipment


# ==================== 校准计划：创建 ====================


async def test_create_calibration_plan(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建校准计划：有上次日期时按周期自动算下次日期。"""
    data = CalibrationPlanCreate(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        last_calibration_date=date(2026, 1, 1),
    )
    plan = await create_calibration_plan(
        db_session, data, make_access_ctx(sample_user)
    )
    assert plan.calibration_type == "内部校准"
    assert plan.cycle_months == 6
    assert plan.last_calibration_date == date(2026, 1, 1)
    assert plan.next_calibration_date == date(2026, 7, 1)


async def test_create_calibration_plan_without_last_date(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建校准计划：无上次日期时不自动计算下次日期。"""
    data = CalibrationPlanCreate(
        equipment_id=sample_equipment.id,
        calibration_type="外部检定",
        cycle_months=12,
    )
    plan = await create_calibration_plan(
        db_session, data, make_access_ctx(sample_user)
    )
    assert plan.next_calibration_date is None


async def test_create_calibration_plan_default_status_enabled(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建校准计划：未指定状态时默认为启用。"""
    data = CalibrationPlanCreate(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=3,
    )
    plan = await create_calibration_plan(
        db_session, data, make_access_ctx(sample_user)
    )
    assert plan.status == "启用"


async def test_create_calibration_plan_cross_year(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建校准计划：跨年月份进位正确（11月 + 3月 → 次年2月）。"""
    data = CalibrationPlanCreate(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=3,
        last_calibration_date=date(2026, 11, 30),
    )
    plan = await create_calibration_plan(
        db_session, data, make_access_ctx(sample_user)
    )
    # 11月30 + 3月 = 次年2月，2月无30日，取该月最后一天28日
    assert plan.next_calibration_date == date(2027, 2, 28)


# ==================== 校准计划：查询 ====================


async def test_get_calibration_plan_by_id(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """按 ID 获取已存在的校准计划。"""
    data = CalibrationPlanCreate(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
    )
    created = await create_calibration_plan(
        db_session, data, make_access_ctx(sample_user)
    )
    result = await get_calibration_plan_by_id(db_session, created.id)
    assert result.id == created.id
    assert result.calibration_type == "内部校准"


async def test_get_calibration_plan_not_found(
    db_session: AsyncSession,
) -> None:
    """获取不存在的校准计划抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await get_calibration_plan_by_id(db_session, uuid.uuid4())


async def test_get_calibration_plans_filter_by_equipment(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """校准计划列表按设备过滤，只返回目标设备的计划。"""
    ctx = make_access_ctx(sample_user)
    await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
        ),
        ctx,
    )
    plans, total = await get_calibration_plans(
        db_session, ctx=ctx, equipment_id=sample_equipment.id
    )
    assert total >= 1
    assert all(p.equipment_id == sample_equipment.id for p in plans)


# ==================== 校准计划：更新 ====================


async def test_update_plan_recomputes_next_date(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """更新计划：给定新的上次日期与周期齐全时重算下次日期。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    updated = await update_calibration_plan(
        db_session,
        plan.id,
        CalibrationPlanUpdate(last_calibration_date=date(2026, 3, 1), cycle_months=3),
        ctx,
    )
    assert updated.last_calibration_date == date(2026, 3, 1)
    assert updated.next_calibration_date == date(2026, 6, 1)


async def test_update_plan_recompute_uses_existing_last_date(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """更新计划：只改周期时，用计划已有的上次日期重算下次日期。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    updated = await update_calibration_plan(
        db_session, plan.id, CalibrationPlanUpdate(cycle_months=12), ctx
    )
    assert updated.next_calibration_date == date(2027, 1, 1)


async def test_update_plan_clears_next_when_last_cleared(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """更新计划：显式清空上次日期时，同步清空下次日期。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    assert plan.next_calibration_date == date(2026, 7, 1)

    updated = await update_calibration_plan(
        db_session,
        plan.id,
        CalibrationPlanUpdate(last_calibration_date=None),
        ctx,
    )
    assert updated.last_calibration_date is None
    assert updated.next_calibration_date is None


async def test_update_plan_status_only(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """更新计划：只改状态时，不触碰下次日期。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    updated = await update_calibration_plan(
        db_session, plan.id, CalibrationPlanUpdate(status="停用"), ctx
    )
    assert updated.status == "停用"
    assert updated.next_calibration_date == date(2026, 7, 1)


async def test_update_plan_not_found(
    db_session: AsyncSession,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """更新不存在的计划抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await update_calibration_plan(
            db_session,
            uuid.uuid4(),
            CalibrationPlanUpdate(cycle_months=3),
            make_access_ctx(sample_user),
        )


async def test_update_plan_forbidden_for_non_owner(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
) -> None:
    """写归属校验：受限用户无权修改他人创建的计划。"""
    owner = sample_user
    other = User(name="其他人", employee_no=f"EMP-OT-{_uid()}")
    db_session.add(other)
    await db_session.flush()

    plan = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="启用",
        created_by=owner.id,
    )
    db_session.add(plan)
    await db_session.flush()

    restricted_ctx = EquipmentAccessContext(
        user=other, data_scope="self_only", department_user_ids=[]
    )
    with pytest.raises(ForbiddenException):
        await update_calibration_plan(
            db_session, plan.id, CalibrationPlanUpdate(cycle_months=3), restricted_ctx
        )


async def test_update_plan_allowed_for_owner(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
) -> None:
    """写归属校验：受限用户可修改自己创建的计划。"""
    plan = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="启用",
        created_by=sample_user.id,
    )
    db_session.add(plan)
    await db_session.flush()

    restricted_ctx = EquipmentAccessContext(
        user=sample_user, data_scope="self_only", department_user_ids=[]
    )
    updated = await update_calibration_plan(
        db_session, plan.id, CalibrationPlanUpdate(cycle_months=3), restricted_ctx
    )
    assert updated.cycle_months == 3


# ==================== 校准计划：删除 ====================


async def test_delete_calibration_plan(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """软删除校准计划后再查抛 NotFoundException。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
        ),
        ctx,
    )
    result = await delete_calibration_plan(db_session, plan.id, ctx)
    assert result is True
    with pytest.raises(NotFoundException):
        await get_calibration_plan_by_id(db_session, plan.id)


# ==================== 校准计划：到期/逾期查询 ====================


async def test_get_overdue_plans_membership(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """到期查询：只含启用且下次日期在阈值内的计划，排除停用与未到期。"""
    ctx = make_access_ctx(sample_user)
    today = date.today()

    due = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="启用",
        next_calibration_date=today - timedelta(days=1),
    )
    disabled = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="停用",
        next_calibration_date=today - timedelta(days=1),
    )
    future = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="启用",
        next_calibration_date=today + timedelta(days=60),
    )
    db_session.add_all([due, disabled, future])
    await db_session.flush()

    plans = await get_overdue_calibration_plans(db_session, ctx, days=0)
    ids = {p.id for p in plans}
    assert due.id in ids
    assert disabled.id not in ids
    assert future.id not in ids


async def test_get_overdue_plans_respects_days_window(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """到期查询：提前天数窗口内的启用计划应被纳入。"""
    ctx = make_access_ctx(sample_user)
    today = date.today()

    within = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="启用",
        next_calibration_date=today + timedelta(days=10),
    )
    db_session.add(within)
    await db_session.flush()

    plans = await get_overdue_calibration_plans(db_session, ctx, days=30)
    assert within.id in {p.id for p in plans}


# ==================== 校准记录 ====================


async def test_create_record_computes_due_and_advances_plan(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建记录：算下次到期、带出设备ID，并同步推进计划的上次/下次日期。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    record = await create_calibration_record(
        db_session,
        CalibrationRecordCreate(
            calibration_plan_id=plan.id,
            calibration_date=date(2026, 7, 1),
            calibration_type="内部校准",
            result="合格",
        ),
        ctx,
    )
    # 记录：next_due = 校准日期 + 周期；设备ID 来自计划
    assert record.next_due_date == date(2027, 1, 1)
    assert record.equipment_id == sample_equipment.id

    # 计划日期被同步推进
    await db_session.refresh(plan)
    assert plan.last_calibration_date == date(2026, 7, 1)
    assert plan.next_calibration_date == date(2027, 1, 1)


async def test_create_record_for_plan_without_last_date(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建记录：计划原本无上次日期时，记录仍按校准日期算下次到期并初始化计划。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="外部检定",
            cycle_months=12,
        ),
        ctx,
    )
    assert plan.next_calibration_date is None

    record = await create_calibration_record(
        db_session,
        CalibrationRecordCreate(
            calibration_plan_id=plan.id,
            calibration_date=date(2026, 5, 10),
            calibration_type="外部检定",
            result="合格",
        ),
        ctx,
    )
    assert record.next_due_date == date(2027, 5, 10)
    await db_session.refresh(plan)
    assert plan.last_calibration_date == date(2026, 5, 10)
    assert plan.next_calibration_date == date(2027, 5, 10)


async def test_create_record_plan_not_found(
    db_session: AsyncSession,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建记录：关联计划不存在时抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await create_calibration_record(
            db_session,
            CalibrationRecordCreate(
                calibration_plan_id=uuid.uuid4(),
                calibration_date=date(2026, 7, 1),
                calibration_type="内部校准",
                result="合格",
            ),
            make_access_ctx(sample_user),
        )


async def test_get_calibration_record_by_id(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """按 ID 获取已存在的校准记录。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    created = await create_calibration_record(
        db_session,
        CalibrationRecordCreate(
            calibration_plan_id=plan.id,
            calibration_date=date(2026, 7, 1),
            calibration_type="内部校准",
            result="合格",
        ),
        ctx,
    )
    result = await get_calibration_record_by_id(db_session, created.id)
    assert result.id == created.id
    assert result.result == "合格"


async def test_get_calibration_record_not_found(
    db_session: AsyncSession,
) -> None:
    """获取不存在的校准记录抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await get_calibration_record_by_id(db_session, uuid.uuid4())


async def test_get_records_filter_by_plan(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """记录列表按计划过滤，只返回目标计划的记录。"""
    ctx = make_access_ctx(sample_user)
    plan = await create_calibration_plan(
        db_session,
        CalibrationPlanCreate(
            equipment_id=sample_equipment.id,
            calibration_type="内部校准",
            cycle_months=6,
            last_calibration_date=date(2026, 1, 1),
        ),
        ctx,
    )
    await create_calibration_record(
        db_session,
        CalibrationRecordCreate(
            calibration_plan_id=plan.id,
            calibration_date=date(2026, 7, 1),
            calibration_type="内部校准",
            result="合格",
        ),
        ctx,
    )
    records, total = await get_calibration_records(
        db_session, ctx=ctx, plan_id=plan.id
    )
    assert total >= 1
    assert all(r.calibration_plan_id == plan.id for r in records)


# ==================== 模型 CheckConstraint 约束 ====================


async def test_plan_invalid_calibration_type_rejected(
    db_session: AsyncSession,
    sample_equipment: Equipment,
) -> None:
    """计划：非法校准类型违反 CHECK 约束。"""
    plan = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="非法类型",
        cycle_months=6,
        status="启用",
    )
    db_session.add(plan)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_plan_invalid_status_rejected(
    db_session: AsyncSession,
    sample_equipment: Equipment,
) -> None:
    """计划：非法状态违反 CHECK 约束。"""
    plan = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="废弃",
    )
    db_session.add(plan)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_record_invalid_result_rejected(
    db_session: AsyncSession,
    sample_equipment: Equipment,
) -> None:
    """记录：非法校准结果违反 CHECK 约束。"""
    plan = CalibrationPlan(
        equipment_id=sample_equipment.id,
        calibration_type="内部校准",
        cycle_months=6,
        status="启用",
    )
    db_session.add(plan)
    await db_session.flush()

    record = CalibrationRecord(
        calibration_plan_id=plan.id,
        equipment_id=sample_equipment.id,
        calibration_date=date(2026, 7, 1),
        calibration_type="内部校准",
        result="待定",
        next_due_date=date(2027, 1, 1),
    )
    db_session.add(record)
    with pytest.raises(IntegrityError):
        await db_session.flush()


# ==================== API 端到端 ====================


async def _create_test_equipment(client: AsyncClient) -> str:
    """经 API 创建设备并返回 equipment_id。"""
    uid = _uid()
    cat_resp = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "校准分类", "code": f"TC-{uid}"},
    )
    cat_id = cat_resp.json()["data"]["id"]
    loc_resp = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "校准位置", "code": f"TL-{uid}"},
    )
    loc_id = loc_resp.json()["data"]["id"]
    eq_resp = await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": f"校准设备-{uid}",
            "equipment_no": f"EQ-{uid}",
            "category_ids": [cat_id],
            "location_id": loc_id,
        },
    )
    return str(eq_resp.json()["data"]["id"])


async def test_api_create_calibration_plan(client: AsyncClient) -> None:
    """API：创建校准计划返回自动算出的下次日期。"""
    equipment_id = await _create_test_equipment(client)
    response = await client.post(
        "/api/v1/equipment/maintenance/calibration/plans",
        json={
            "equipment_id": equipment_id,
            "calibration_type": "内部校准",
            "cycle_months": 6,
            "last_calibration_date": "2026-01-01",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["calibration_type"] == "内部校准"
    assert data["data"]["next_calibration_date"] == "2026-07-01"


async def test_api_calibration_plan_crud(client: AsyncClient) -> None:
    """API：校准计划创建→查询→修改→列表→删除全流程。"""
    equipment_id = await _create_test_equipment(client)

    create_resp = await client.post(
        "/api/v1/equipment/maintenance/calibration/plans",
        json={
            "equipment_id": equipment_id,
            "calibration_type": "外部检定",
            "cycle_months": 12,
        },
    )
    plan_id = create_resp.json()["data"]["id"]

    get_resp = await client.get(
        f"/api/v1/equipment/maintenance/calibration/plans/{plan_id}"
    )
    assert get_resp.status_code == 200

    update_resp = await client.put(
        f"/api/v1/equipment/maintenance/calibration/plans/{plan_id}",
        json={"cycle_months": 3},
    )
    assert update_resp.json()["data"]["cycle_months"] == 3

    list_resp = await client.get("/api/v1/equipment/maintenance/calibration/plans")
    assert list_resp.status_code == 200

    del_resp = await client.delete(
        f"/api/v1/equipment/maintenance/calibration/plans/{plan_id}"
    )
    assert del_resp.status_code == 200


async def test_api_create_calibration_record(client: AsyncClient) -> None:
    """API：创建校准记录返回结果与下次到期日期。"""
    equipment_id = await _create_test_equipment(client)

    plan_resp = await client.post(
        "/api/v1/equipment/maintenance/calibration/plans",
        json={
            "equipment_id": equipment_id,
            "calibration_type": "内部校准",
            "cycle_months": 6,
            "last_calibration_date": "2026-01-01",
        },
    )
    plan_id = plan_resp.json()["data"]["id"]

    record_resp = await client.post(
        "/api/v1/equipment/maintenance/calibration/records",
        json={
            "calibration_plan_id": plan_id,
            "calibration_date": "2026-07-01",
            "calibration_type": "内部校准",
            "result": "合格",
            "certificate_no": "CERT-2026-001",
        },
    )
    assert record_resp.status_code == 200
    data = record_resp.json()
    assert data["data"]["result"] == "合格"
    assert data["data"]["next_due_date"] == "2027-01-01"
    assert data["data"]["equipment_id"] == equipment_id


async def test_api_calibration_records_list(client: AsyncClient) -> None:
    """API：校准记录列表可访问。"""
    response = await client.get(
        "/api/v1/equipment/maintenance/calibration/records"
    )
    assert response.status_code == 200


async def test_api_calibration_plan_overdue(client: AsyncClient) -> None:
    """API：查询到期/逾期计划，逾期计划应出现在结果中。"""
    equipment_id = await _create_test_equipment(client)

    create_resp = await client.post(
        "/api/v1/equipment/maintenance/calibration/plans",
        json={
            "equipment_id": equipment_id,
            "calibration_type": "内部校准",
            "cycle_months": 6,
            "last_calibration_date": "2025-01-01",
        },
    )
    plan_id = create_resp.json()["data"]["id"]

    response = await client.get(
        "/api/v1/equipment/maintenance/calibration/plans/overdue",
        params={"days": 365},
    )
    assert response.status_code == 200
    ids = {p["id"] for p in response.json()["data"]}
    assert plan_id in ids
