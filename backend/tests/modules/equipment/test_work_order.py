"""工单域(work order)业务规则测试。

覆盖状态机、create/start/complete/verify/close 各分支、领料(consume_materials),
以及 repository/API 的代表性用例。断言以业务规则为准,不逆向 app 代码。
"""

import uuid
from collections.abc import Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import (
    Equipment,
    Location,
    WorkOrder,
)
from app.modules.equipment.models.spare_part import (
    SparePart,
    SparePartStock,
    SparePartTransaction,
)
from app.modules.equipment.repository import (
    count_open_fault_work_orders,
    count_open_work_orders_by_equipment,
    exists_unclosed_work_order,
    get_max_work_order_no,
)
from app.modules.equipment.repository import (
    create_work_order as repo_create_work_order,
)
from app.modules.equipment.schemas import (
    WorkOrderComplete,
    WorkOrderCreate,
    WorkOrderVerify,
)
from app.modules.equipment.schemas.work_order import WorkOrderType
from app.modules.equipment.service import (
    assign_work_order,
    close_work_order,
    complete_work_order,
    consume_materials,
    create_work_order,
    generate_work_order_no,
    get_work_order_statistics,
    start_work_order,
    verify_work_order,
)
from app.modules.equipment.service.work_order import (
    _VALID_TRANSITIONS,
    _validate_transition,
)
from app.platform.identity.models import User


def _uid() -> str:
    """共享库唯一后缀,避免唯一键冲突。"""
    return uuid.uuid4().hex[:8]


# ==================== 通用 fixtures ====================


@pytest.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """报修人。"""
    user = User(name="测试报修人", employee_no=f"EMP-R-{_uid()}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def sample_equipment(db_session: AsyncSession) -> Equipment:
    """完好设备(分类走关联表,工单测试无需分类)。"""
    location = Location(name="一车间", code=f"WS-{_uid()}")
    db_session.add(location)
    await db_session.flush()

    equipment = Equipment(
        equipment_no=f"EQ-{_uid()}",
        name="R-101反应釜",
        location_id=location.id,
        status="完好",
    )
    db_session.add(equipment)
    await db_session.flush()
    return equipment


async def _new_user(db_session: AsyncSession, name: str) -> User:
    user = User(name=name, employee_no=f"EMP-{_uid()}")
    db_session.add(user)
    await db_session.flush()
    return user


# ==================== 状态机 ====================


def test_state_machine_legal_edges() -> None:
    """状态机每条合法边都应通过校验,不抛异常。"""
    for src, targets in _VALID_TRANSITIONS.items():
        for tgt in targets:
            _validate_transition(src, tgt)  # 不抛即通过


@pytest.mark.parametrize(
    ("src", "tgt"),
    [
        ("待处理", "待验收"),   # 待处理不可直接待验收
        ("待处理", "已完成"),   # 待处理不可直接已完成
        ("执行中", "待处理"),   # 不可回退到待处理
        ("待验收", "待处理"),   # 待验收不可回退到待处理
        ("已完成", "执行中"),   # 已完成不可回执行中
        ("已完成", "待验收"),   # 已完成不可回待验收
        ("已关闭", "执行中"),   # 终态不可再转
        ("已关闭", "已完成"),   # 终态不可再转
        ("已关闭", "已关闭"),   # 终态无出边
    ],
)
def test_state_machine_illegal_edges(src: str, tgt: str) -> None:
    """非法状态转换应抛 AppException。"""
    with pytest.raises(AppException):
        _validate_transition(src, tgt)


def test_state_machine_reject_edge_is_legal() -> None:
    """验收退回:待验收→执行中 是合法边。"""
    _validate_transition("待验收", "执行中")  # 不抛即通过


def test_state_machine_closed_is_terminal() -> None:
    """已关闭为终态,无任何合法出边。"""
    assert _VALID_TRANSITIONS["已关闭"] == []


# ==================== create ====================


async def test_generate_work_order_no(db_session: AsyncSession) -> None:
    """工单号格式:WO-yyyyMMdd-0001,总长 16。"""
    wo_no = await generate_work_order_no(db_session)
    assert wo_no.startswith("WO-")
    assert len(wo_no) == 16  # WO-(3) + yyyyMMdd(8) + -(1) + 0001(4)


async def test_create_work_order(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """创建工单:初始状态待处理,工单号格式正确,reporter_id=当前用户。"""
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        order_type="故障维修",
        priority="高",
        fault_description="设备发出异响",
    )
    wo = await create_work_order(db_session, data, make_access_ctx(sample_user))
    assert wo.work_order_no.startswith("WO-")
    assert wo.status == "待处理"
    assert wo.equipment_id == sample_equipment.id
    # reporter_id 由 ctx.user.id 决定
    assert wo.reporter_id == sample_user.id


async def test_create_work_order_equipment_scrapped(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """设备报废时不能创建工单。"""
    sample_equipment.status = "报废"
    await db_session.flush()

    data = WorkOrderCreate(equipment_id=sample_equipment.id)
    with pytest.raises(AppException):
        await create_work_order(db_session, data, make_access_ctx(sample_user))


async def test_create_fault_sets_equipment_pending_check(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """故障维修工单创建后,设备状态自动改为「故障待检」。"""
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id, order_type="故障维修"
    )
    await create_work_order(db_session, data, make_access_ctx(sample_user))
    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    assert refreshed.status == "故障待检"


async def test_start_fault_sets_equipment_repairing(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """故障维修开始执行后设备进入「维修中」,关单后恢复「完好」。"""
    ctx = make_access_ctx(sample_user)
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        order_type="故障维修",
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, sample_user.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)

    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    assert refreshed.status == "维修中"

    await close_work_order(db_session, wo.id, ctx)
    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    assert refreshed.status == "完好"


@pytest.mark.parametrize(
    "order_type", ["计划维护", "校准", "异常处理", "日常维护"]
)
async def test_create_non_fault_keeps_equipment_status(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    order_type: WorkOrderType,
) -> None:
    """非故障维修类型创建工单不改设备状态,设备仍为「完好」。"""
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id, order_type=order_type
    )
    await create_work_order(db_session, data, make_access_ctx(sample_user))
    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    assert refreshed.status == "完好"


# ==================== start ====================


async def test_start_requires_assignee(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """有责任人但未指派维修人时不能开始执行。"""
    ctx = make_access_ctx(sample_user)
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    # 未 assign,assignee_id 为空
    with pytest.raises(AppException):
        await start_work_order(db_session, wo.id, ctx)


async def test_start_requires_responsible(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """已指派维修人但无责任人时不能开始执行。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维修员")
    data = WorkOrderCreate(equipment_id=sample_equipment.id)
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    # responsible_person_id 仍为空
    with pytest.raises(AppException):
        await start_work_order(db_session, wo.id, ctx)


async def test_start_neither_set(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """责任人和维修人都为空时不能开始执行。"""
    ctx = make_access_ctx(sample_user)
    data = WorkOrderCreate(equipment_id=sample_equipment.id)
    wo = await create_work_order(db_session, data, ctx)
    with pytest.raises(AppException):
        await start_work_order(db_session, wo.id, ctx)


# ==================== complete ====================


@pytest.mark.parametrize(
    "order_type", ["故障维修", "校准", "异常处理", "计划维护"]
)
async def test_complete_repair_types_go_pending_verify(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
    order_type: WorkOrderType,
) -> None:
    """需验收的4类工单完成后进入「待验收」,并计算实际耗时。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维修员")
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        order_type=order_type,
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="已处理"), ctx
    )
    assert wo.status == "待验收"
    assert wo.completed_at is not None
    assert wo.actual_duration is not None


async def test_complete_daily_maintenance_goes_done(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """日常维护完成后直接「已完成」(无需验收)。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "巡检员")
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        order_type="日常维护",
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="巡检完成"), ctx
    )
    assert wo.status == "已完成"


# ==================== verify ====================


async def test_verify_pass_goes_done(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """验收合格 → 已完成。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维修员")
    verifier = await _new_user(db_session, "验收员")
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="更换轴承"), ctx
    )
    wo = await verify_work_order(
        db_session, wo.id, make_access_ctx(verifier),
        WorkOrderVerify(result="合格"),
    )
    assert wo.status == "已完成"
    assert wo.verification_result == "合格"
    assert wo.verified_by == verifier.id


async def test_verify_reject_returns_to_executing_keeps_timestamps(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """验收不合格 → 退回「执行中」,且不重置首次维修的时间戳与耗时。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维修员")
    verifier = await _new_user(db_session, "验收员")
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="简单处理"), ctx
    )
    started_at = wo.started_at
    completed_at = wo.completed_at
    actual_duration = wo.actual_duration

    wo = await verify_work_order(
        db_session, wo.id, make_access_ctx(verifier),
        WorkOrderVerify(result="不合格", remark="问题未解决"),
    )
    assert wo.status == "执行中"
    assert wo.verification_result == "不合格"
    # 退回不重置维修时间戳/耗时,保留首次维修记录用于审计
    assert wo.started_at == started_at
    assert wo.completed_at == completed_at
    assert wo.actual_duration == actual_duration


async def test_verify_not_allowed_for_daily_maintenance(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """日常维护工单不支持验收。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维护员")
    verifier = await _new_user(db_session, "验收员")
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        order_type="日常维护",
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="维护完成"), ctx
    )
    with pytest.raises(AppException):
        await verify_work_order(
            db_session, wo.id, make_access_ctx(verifier),
            WorkOrderVerify(result="合格"),
        )


# ==================== 完整生命周期(迁移) ====================


async def test_work_order_lifecycle(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """故障维修完整生命周期:创建→指派→开始→完成→验收→关闭。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维修员")
    verifier = await _new_user(db_session, "验收员")

    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        fault_description="设备异响",
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    assert wo.status == "待处理"

    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    assert wo.status == "待处理"
    assert wo.assignee_id == assignee.id

    wo = await start_work_order(db_session, wo.id, ctx)
    assert wo.status == "执行中"
    assert wo.started_at is not None

    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="更换了轴承"), ctx
    )
    assert wo.status == "待验收"

    wo = await verify_work_order(
        db_session, wo.id, make_access_ctx(verifier),
        WorkOrderVerify(result="合格"),
    )
    assert wo.status == "已完成"

    wo = await close_work_order(db_session, wo.id, ctx)
    assert wo.status == "已关闭"


async def test_maintenance_work_order_lifecycle(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """计划维护生命周期:创建→指派→执行→完成(待验收)→关闭。"""
    from datetime import date

    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "维护员")

    data = WorkOrderCreate(
        equipment_id=sample_equipment.id,
        order_type="计划维护",
        planned_start_date=date(2026, 6, 10),
        responsible_person_id=sample_user.id,
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id,
        WorkOrderComplete(repair_detail="更换润滑油,检查密封"), ctx,
    )
    assert wo.status == "待验收"
    wo = await close_work_order(db_session, wo.id, ctx)
    assert wo.status == "已关闭"


# ==================== close 设备状态恢复 ====================


async def test_close_fault_restores_equipment(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """关闭故障维修工单后,该设备无未关闭故障工单 → 恢复「完好」(建单未开始即关单,从故障待检恢复)。"""
    ctx = make_access_ctx(sample_user)
    data = WorkOrderCreate(
        equipment_id=sample_equipment.id, order_type="故障维修"
    )
    wo = await create_work_order(db_session, data, ctx)
    # 创建后设备应为故障待检
    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None and refreshed.status == "故障待检"

    # 待处理 → 已关闭 是合法边
    wo = await close_work_order(db_session, wo.id, ctx)
    assert wo.status == "已关闭"

    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    assert refreshed.status == "完好"


async def test_close_non_fault_does_not_restore(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """非故障维修类型关闭不触发设备状态恢复(维修中保持不变)。"""
    ctx = make_access_ctx(sample_user)
    # 人为把设备置为维修中
    sample_equipment.status = "维修中"
    await db_session.flush()

    data = WorkOrderCreate(
        equipment_id=sample_equipment.id, order_type="计划维护"
    )
    wo = await create_work_order(db_session, data, ctx)
    wo = await close_work_order(db_session, wo.id, ctx)
    assert wo.status == "已关闭"

    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    # 计划维护不触发恢复,设备仍为维修中
    assert refreshed.status == "维修中"


async def test_close_fault_keeps_repairing_when_other_open_fault(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """仍有未关闭的故障维修工单时,关闭其一不恢复设备状态。"""
    ctx = make_access_ctx(sample_user)
    wo1 = await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="故障维修"),
        ctx,
    )
    await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="故障维修"),
        ctx,
    )
    # 关闭 wo1,但 wo2 仍未关闭
    await close_work_order(db_session, wo1.id, ctx)

    refreshed = await db_session.get(Equipment, sample_equipment.id)
    assert refreshed is not None
    assert refreshed.status == "故障待检"


# ==================== consume_materials 领料 ====================


async def _make_spare_part_with_stock(
    db_session: AsyncSession,
    qty: int,
    unit_price: float | None = None,
) -> SparePart:
    """创建备件 + 库存记录(直接 ORM,便于控制库存数量)。"""
    spare_part = SparePart(
        code=f"SP-{_uid()}",
        name="轴承",
        unit="个",
        unit_price=unit_price,
    )
    db_session.add(spare_part)
    await db_session.flush()
    stock = SparePartStock(spare_part_id=spare_part.id, current_qty=qty)
    db_session.add(stock)
    await db_session.flush()
    return spare_part


async def test_consume_materials_success(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """领料成功:扣减库存 + 建负数出库流水(无单价时费用为0)。"""
    ctx = make_access_ctx(sample_user)
    spare_part = await _make_spare_part_with_stock(db_session, qty=10)
    wo = await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="故障维修"),
        ctx,
    )

    transactions = await consume_materials(
        db_session, wo.id,
        [{"spare_part_id": spare_part.id, "quantity": 3}], ctx,
    )
    assert len(transactions) == 1

    # 库存扣减到 7
    stock = await db_session.scalar(
        select(SparePartStock).where(
            SparePartStock.spare_part_id == spare_part.id
        )
    )
    assert stock is not None
    assert stock.current_qty == 7

    # 出库流水为负数,且关联本工单
    txn = await db_session.scalar(
        select(SparePartTransaction).where(
            SparePartTransaction.work_order_id == wo.id
        )
    )
    assert txn is not None
    assert txn.quantity == -3
    assert txn.transaction_type == "出库"

    # 无单价时费用为 0
    refreshed = await db_session.get(WorkOrder, wo.id)
    assert refreshed is not None
    assert (refreshed.spare_parts_cost or 0.0) == 0.0


async def test_consume_materials_accumulates_cost(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """领料成功时按单价累加工单备件费用(单价50×2=100)。"""
    ctx = make_access_ctx(sample_user)
    spare_part = await _make_spare_part_with_stock(
        db_session, qty=10, unit_price=50.0
    )
    wo = await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="故障维修"),
        ctx,
    )

    await consume_materials(
        db_session, wo.id,
        [{"spare_part_id": spare_part.id, "quantity": 2}], ctx,
    )

    refreshed = await db_session.get(WorkOrder, wo.id)
    assert refreshed is not None
    assert refreshed.spare_parts_cost == pytest.approx(100.0)


async def test_consume_materials_insufficient_stock(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """库存不足时领料抛 AppException。"""
    ctx = make_access_ctx(sample_user)
    spare_part = await _make_spare_part_with_stock(db_session, qty=1)
    wo = await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="故障维修"),
        ctx,
    )
    with pytest.raises(AppException):
        await consume_materials(
            db_session, wo.id,
            [{"spare_part_id": spare_part.id, "quantity": 5}], ctx,
        )


async def test_consume_materials_rejected_when_closed(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """已完成/已关闭工单不能领料。"""
    ctx = make_access_ctx(sample_user)
    assignee = await _new_user(db_session, "巡检员")
    spare_part = await _make_spare_part_with_stock(db_session, qty=10)
    # 日常维护 → 完成后直接「已完成」
    wo = await create_work_order(
        db_session,
        WorkOrderCreate(
            equipment_id=sample_equipment.id,
            order_type="日常维护",
            responsible_person_id=sample_user.id,
        ),
        ctx,
    )
    wo = await assign_work_order(db_session, wo.id, assignee.id, ctx)
    wo = await start_work_order(db_session, wo.id, ctx)
    wo = await complete_work_order(
        db_session, wo.id, WorkOrderComplete(repair_detail="完成"), ctx
    )
    assert wo.status == "已完成"

    with pytest.raises(AppException):
        await consume_materials(
            db_session, wo.id,
            [{"spare_part_id": spare_part.id, "quantity": 1}], ctx,
        )


# ==================== statistics ====================


async def test_get_work_order_statistics_structure(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """工单统计返回 total / by_status / by_type / by_priority 结构。"""
    ctx = make_access_ctx(sample_user)
    await create_work_order(
        db_session,
        WorkOrderCreate(
            equipment_id=sample_equipment.id,
            order_type="故障维修",
            priority="高",
        ),
        ctx,
    )
    stats = await get_work_order_statistics(db_session, ctx)
    assert set(stats.keys()) >= {"total", "by_status", "by_type", "by_priority"}
    assert isinstance(stats["by_status"], dict)
    assert isinstance(stats["by_type"], dict)


# ==================== repository ====================


async def test_repo_create_work_order(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
) -> None:
    """repo 直接创建工单。"""
    wo = await repo_create_work_order(db_session, {
        "work_order_no": f"WO-20260603-{_uid()[:4]}",
        "equipment_id": sample_equipment.id,
        "order_type": "故障维修",
        "priority": "中",
        "status": "待处理",
        "reporter_id": sample_user.id,
    })
    assert wo.status == "待处理"
    assert wo.equipment_id == sample_equipment.id


async def test_repo_get_max_work_order_no(db_session: AsyncSession) -> None:
    """当天最大工单号为 None 或以 WO- 开头。"""
    result = await get_max_work_order_no(db_session)
    assert result is None or result.startswith("WO-")


async def test_repo_count_open_work_orders_by_equipment(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """统计设备未关闭工单数:新建后为1,关闭后为0。"""
    ctx = make_access_ctx(sample_user)
    assert await count_open_work_orders_by_equipment(
        db_session, sample_equipment.id
    ) == 0
    wo = await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="计划维护"),
        ctx,
    )
    assert await count_open_work_orders_by_equipment(
        db_session, sample_equipment.id
    ) == 1
    await close_work_order(db_session, wo.id, ctx)
    assert await count_open_work_orders_by_equipment(
        db_session, sample_equipment.id
    ) == 0


async def test_repo_count_open_fault_work_orders(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
    make_access_ctx: Callable[[User], EquipmentAccessContext],
) -> None:
    """仅统计未关闭的「故障维修」工单,计划维护不计入。"""
    ctx = make_access_ctx(sample_user)
    await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="计划维护"),
        ctx,
    )
    assert await count_open_fault_work_orders(
        db_session, sample_equipment.id
    ) == 0
    await create_work_order(
        db_session,
        WorkOrderCreate(equipment_id=sample_equipment.id, order_type="故障维修"),
        ctx,
    )
    assert await count_open_fault_work_orders(
        db_session, sample_equipment.id
    ) == 1


async def test_repo_exists_unclosed_work_order(
    db_session: AsyncSession,
    sample_equipment: Equipment,
    sample_user: User,
) -> None:
    """按巡检任务+设备检测是否存在未关闭工单。"""
    task_id = uuid.uuid4()
    assert await exists_unclosed_work_order(
        db_session, task_id, sample_equipment.id
    ) is False

    await repo_create_work_order(db_session, {
        "work_order_no": f"WO-20260603-{_uid()[:4]}",
        "equipment_id": sample_equipment.id,
        "order_type": "故障维修",
        "priority": "中",
        "status": "待处理",
        "reporter_id": sample_user.id,
        "inspection_task_id": task_id,
    })
    assert await exists_unclosed_work_order(
        db_session, task_id, sample_equipment.id
    ) is True


# ==================== API 代表性用例 ====================


async def _create_api_equipment(client: AsyncClient) -> str:
    """经 API 创建设备,返回 equipment_id。"""
    uid = _uid()
    cat_resp = await client.post(
        "/api/v1/equipment/categories",
        json={"name": "测试分类", "code": f"TC-{uid}"},
    )
    cat_id = cat_resp.json()["data"]["id"]
    loc_resp = await client.post(
        "/api/v1/equipment/locations",
        json={"name": "测试位置", "code": f"TL-{uid}"},
    )
    loc_id = loc_resp.json()["data"]["id"]
    eq_resp = await client.post(
        "/api/v1/equipment/equipments",
        json={
            "name": f"测试设备-{uid}",
            "equipment_no": f"EQ-{uid}",
            "category_ids": [cat_id],
            "location_id": loc_id,
        },
    )
    return str(eq_resp.json()["data"]["id"])


async def test_api_create_work_order(client: AsyncClient) -> None:
    """API 创建工单:返回待处理 + WO- 工单号。"""
    equipment_id = await _create_api_equipment(client)
    response = await client.post(
        "/api/v1/equipment/maintenance/work-orders/",
        json={
            "equipment_id": equipment_id,
            "order_type": "故障维修",
            "priority": "高",
            "fault_description": "设备发出异响",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "待处理"
    assert data["work_order_no"].startswith("WO-")


async def test_api_work_order_full_lifecycle(
    client: AsyncClient, test_assignee: User
) -> None:
    """API 完整生命周期:创建→指派→开始→完成→验收→关闭。"""
    equipment_id = await _create_api_equipment(client)
    create_resp = await client.post(
        "/api/v1/equipment/maintenance/work-orders/",
        json={
            "equipment_id": equipment_id,
            "fault_description": "异响",
            "responsible_person_id": str(test_assignee.id),
        },
    )
    wo_id = create_resp.json()["data"]["id"]
    assert create_resp.json()["data"]["status"] == "待处理"

    assign_resp = await client.put(
        f"/api/v1/equipment/maintenance/work-orders/{wo_id}/assign",
        json={"assignee_id": str(test_assignee.id)},
    )
    assert assign_resp.json()["data"]["status"] == "待处理"

    start_resp = await client.put(
        f"/api/v1/equipment/maintenance/work-orders/{wo_id}/start",
    )
    assert start_resp.json()["data"]["status"] == "执行中"

    complete_resp = await client.put(
        f"/api/v1/equipment/maintenance/work-orders/{wo_id}/complete",
        json={"repair_detail": "更换了轴承"},
    )
    assert complete_resp.json()["data"]["status"] == "待验收"

    verify_resp = await client.put(
        f"/api/v1/equipment/maintenance/work-orders/{wo_id}/verify",
        json={"result": "合格"},
    )
    assert verify_resp.json()["data"]["status"] == "已完成"

    close_resp = await client.put(
        f"/api/v1/equipment/maintenance/work-orders/{wo_id}/close",
    )
    assert close_resp.json()["data"]["status"] == "已关闭"


async def test_api_work_order_list(client: AsyncClient) -> None:
    """API 工单列表返回至少一条。"""
    equipment_id = await _create_api_equipment(client)
    await client.post(
        "/api/v1/equipment/maintenance/work-orders/",
        json={"equipment_id": equipment_id},
    )
    response = await client.get("/api/v1/equipment/maintenance/work-orders/")
    assert response.status_code == 200
    assert len(response.json()["data"]) >= 1


async def test_api_work_order_statistics(client: AsyncClient) -> None:
    """API 工单统计返回 total / by_status。"""
    response = await client.get(
        "/api/v1/equipment/maintenance/work-orders/statistics"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert "total" in data
    assert "by_status" in data
