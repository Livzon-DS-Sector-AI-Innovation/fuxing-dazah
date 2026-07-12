"""巡检数值 / 分析 / 定时(cron)域测试。

覆盖:
- ``_parse_numeric_value`` 严格解析边界;
- 数值型检查项提交(合法写入 numeric_value / 脏值阻断 / 空值放行);
- 分析响应 schema 往返构造;
- 分析仓储聚合(趋势 / 异常热力 / 可选设备列表);
- cron 计算与校验(5 段 / 6 段 / 非法);
- 路线定时任务的增删改查。
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import time as app_time
from app.core.exceptions import AppException, NotFoundException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, Location
from app.modules.equipment.models.inspection import (
    InspectionRoute,
    InspectionTask,
)
from app.modules.equipment.models.inspection_template import (
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.modules.equipment.repository.inspection import (
    get_analytics_equipment_list,
    get_anomaly_stats,
    get_schedule_by_id,
    get_trend_data,
)
from app.modules.equipment.service.inspection import (
    _parse_numeric_value,
    _validate_cron,
    complete_task,
    compute_next_cron,
    create_route,
    create_schedule,
    create_task,
    delete_schedule,
    get_schedules_by_route,
    start_task,
    submit_equipment_check,
    update_schedule,
)
from app.platform.identity.models import User


# ══════════ fixtures ══════════
@pytest.fixture
async def inspector(db_session: AsyncSession) -> User:
    """巡检执行人。"""
    user = User(name="巡检员", employee_no=f"EMP-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def equipment(db_session: AsyncSession) -> Equipment:
    """一台在用设备(带所属地点)。"""
    loc = Location(name="车间", code=f"WS-{uuid.uuid4().hex[:6]}")
    db_session.add(loc)
    await db_session.flush()
    eq = Equipment(
        equipment_no=f"EQ-{uuid.uuid4().hex[:8]}",
        name="反应釜",
        location_id=loc.id,
        status="在用",
        importance="中",
    )
    db_session.add(eq)
    await db_session.flush()
    return eq


@pytest.fixture
async def numeric_template(db_session: AsyncSession) -> InspectionTemplate:
    """含单个 numeric 检查项(电机温度/℃)的模板。"""
    tpl = InspectionTemplate(name=f"数值模板-{uuid.uuid4().hex[:6]}")
    db_session.add(tpl)
    await db_session.flush()
    db_session.add(
        InspectionTemplateItem(
            template_id=tpl.id,
            item_name="电机温度",
            data_type="numeric",
            unit="℃",
            sort_order=1,
        )
    )
    await db_session.flush()
    return tpl


async def _item(db: AsyncSession, template_id: uuid.UUID) -> InspectionTemplateItem:
    """取模板的首个检查项。"""
    r = await db.execute(
        select(InspectionTemplateItem).where(
            InspectionTemplateItem.template_id == template_id
        )
    )
    item = r.scalars().first()
    assert item is not None
    return item


async def _running_task(
    db: AsyncSession,
    inspector: User,
    equipment: Equipment,
    template: InspectionTemplate,
) -> InspectionTask:
    """创建并启动一个设备巡检任务,返回执行中的任务。"""
    # 服务层要求 ctx(权限重构后);测试用超管范围 ctx,跳过归属校验。
    ctx = EquipmentAccessContext(user=inspector, data_scope="all")
    task = await create_task(
        db,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment.id,
            "template_ids": [template.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx,
    )
    return await start_task(db, task.id, ctx)


async def _submit_and_complete(
    db: AsyncSession,
    inspector: User,
    equipment: Equipment,
    template: InspectionTemplate,
    records: list[dict[str, object]],
) -> None:
    """走完 创建→启动→提交→完成 全流程,用于分析仓储的数据准备。"""
    ctx = EquipmentAccessContext(user=inspector, data_scope="all")
    task = await _running_task(db, inspector, equipment, template)
    await submit_equipment_check(db, task.id, equipment.id, records)
    await complete_task(db, task.id, ctx=ctx)


# ══════════ _parse_numeric_value ══════════
def test_parse_numeric_value() -> None:
    """严格解析:空/纯空白/None→None;纯数字→Decimal;非纯数字→抛 InvalidOperation。"""
    assert _parse_numeric_value("25") == Decimal("25")
    assert _parse_numeric_value("25.3") == Decimal("25.3")
    assert _parse_numeric_value("-0.6") == Decimal("-0.6")
    assert _parse_numeric_value("") is None
    assert _parse_numeric_value("   ") is None
    assert _parse_numeric_value(None) is None
    with pytest.raises(InvalidOperation):
        _parse_numeric_value("25℃")
    with pytest.raises(InvalidOperation):
        _parse_numeric_value("正常")


# ══════════ 数值型提交 ══════════
async def test_numeric_value_parsed_and_stored(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """numeric 检查项提交合法数字:actual_value 原样保留,numeric_value 解析写入。"""
    task = await _running_task(db_session, inspector, equipment, numeric_template)
    item = await _item(db_session, numeric_template.id)

    created = await submit_equipment_check(
        db_session,
        task.id,
        equipment.id,
        [{"template_item_id": item.id, "result": "正常", "actual_value": "25.3"}],
    )
    assert created[0].numeric_value == Decimal("25.3")
    assert created[0].actual_value == "25.3"


async def test_numeric_value_with_unit_blocks_submit(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """numeric 检查项提交带单位脏值(25℃)应阻断,报错含检查项名与原值。"""
    task = await _running_task(db_session, inspector, equipment, numeric_template)
    item = await _item(db_session, numeric_template.id)

    with pytest.raises(AppException) as exc:
        await submit_equipment_check(
            db_session,
            task.id,
            equipment.id,
            [{"template_item_id": item.id, "result": "正常", "actual_value": "25℃"}],
        )
    assert "电机温度" in str(exc.value.message)
    assert "25℃" in str(exc.value.message)


async def test_numeric_empty_value_not_blocked(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """numeric 检查项提交空实测值不阻断,numeric_value 记为 None。"""
    task = await _running_task(db_session, inspector, equipment, numeric_template)
    item = await _item(db_session, numeric_template.id)

    created = await submit_equipment_check(
        db_session,
        task.id,
        equipment.id,
        [{"template_item_id": item.id, "result": "跳过", "actual_value": ""}],
    )
    assert created[0].numeric_value is None


def test_template_item_schema_has_type_fields() -> None:
    """模板检查项 schema 具备 data_type/unit 字段与默认值(text/None)。"""
    from app.modules.equipment.schemas.inspection_template import (
        InspectionTemplateItemCreate,
        InspectionTemplateItemResponse,
    )

    c = InspectionTemplateItemCreate(item_name="温度", data_type="numeric", unit="℃")
    assert c.data_type == "numeric"
    assert c.unit == "℃"
    # 默认值
    d = InspectionTemplateItemCreate(item_name="外观")
    assert d.data_type == "text"
    assert d.unit is None
    assert "data_type" in InspectionTemplateItemResponse.model_fields
    assert "unit" in InspectionTemplateItemResponse.model_fields


# ══════════ 分析响应 schema 往返 ══════════
def test_trend_schema_roundtrip() -> None:
    """趋势响应 schema 可用嵌套数据点构造并保留 Decimal 值。"""
    from app.modules.equipment.schemas.inspection import (
        TrendDataPoint,
        TrendResponse,
        TrendSeries,
    )

    dp = TrendDataPoint(date=date(2026, 7, 1), value=Decimal("25.3"), result="正常")
    s = TrendSeries(
        template_item_id="550e8400-e29b-41d4-a716-446655440000",
        item_name="电机温度",
        unit="℃",
        data_points=[dp],
    )
    r = TrendResponse(equipment_name="R-101", equipment_no="EQ-001", series=[s])
    assert r.series[0].data_points[0].value == Decimal("25.3")


def test_anomaly_schema_roundtrip() -> None:
    """异常热力响应 schema:设备排行/检查项排行/月度趋势均可构造。"""
    from app.modules.equipment.schemas.inspection import (
        AnomalyMonthlyItem,
        AnomalyRankingItem,
        AnomalyResponse,
    )

    a = AnomalyResponse(
        equipment_ranking=[
            AnomalyRankingItem(
                equipment_id="550e8400-e29b-41d4-a716-446655440000",
                equipment_name="R-101",
                equipment_no="EQ-001",
                template_item_id=None,
                item_name="",
                template_name="",
                total_count=30,
                abnormal_count=5,
                anomaly_rate=16.7,
            )
        ],
        item_ranking=[
            AnomalyRankingItem(
                equipment_id=None,
                equipment_name="",
                equipment_no="",
                template_item_id="550e8400-e29b-41d4-a716-446655440001",
                item_name="密封性",
                template_name="反应釜巡检",
                total_count=300,
                abnormal_count=42,
                anomaly_rate=14.0,
            )
        ],
        monthly_trend=[
            AnomalyMonthlyItem(
                month="2026-06", normal=280, abnormal=40, skip=10, total=330
            )
        ],
    )
    assert a.equipment_ranking[0].anomaly_rate == 16.7


def test_equipment_list_schema() -> None:
    """可选设备列表响应 schema 可构造并保留数值型检查项数量。"""
    from app.modules.equipment.schemas.inspection import (
        EquipmentListItem,
        EquipmentListResponse,
    )

    r = EquipmentListResponse(
        equipments=[
            EquipmentListItem(
                equipment_id="550e8400-e29b-41d4-a716-446655440000",
                equipment_name="R-101",
                equipment_no="EQ-001",
                numeric_item_count=3,
                latest_inspection_date="2026-07-09",
            )
        ]
    )
    assert r.equipments[0].numeric_item_count == 3


# ══════════ 分析仓储聚合 ══════════
async def test_get_trend_data_returns_series(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """参数趋势查询返回正确的数据点结构(item_name/unit/value)。"""
    item = await _item(db_session, numeric_template.id)
    await _submit_and_complete(
        db_session,
        inspector,
        equipment,
        numeric_template,
        [{"template_item_id": item.id, "result": "正常", "actual_value": "25.3"}],
    )

    result = await get_trend_data(
        db_session,
        equipment.id,
        [item.id],
        from_date=date(2026, 1, 1),
        to_date=date(2026, 12, 31),
    )
    assert len(result) == 1
    assert result[0]["item_name"] == "电机温度"
    assert result[0]["unit"] == "℃"
    assert len(result[0]["data_points"]) == 1
    assert result[0]["data_points"][0]["value"] == Decimal("25.3")


async def test_get_trend_data_empty_item_ids_returns_all_numeric(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """item_ids 传空时不过滤检查项,返回该设备全部数值型参数序列。"""
    item = await _item(db_session, numeric_template.id)
    await _submit_and_complete(
        db_session,
        inspector,
        equipment,
        numeric_template,
        [{"template_item_id": item.id, "result": "正常", "actual_value": "30"}],
    )

    result = await get_trend_data(
        db_session,
        equipment.id,
        [],
        from_date=date(2026, 1, 1),
        to_date=date(2026, 12, 31),
    )
    assert len(result) == 1
    assert result[0]["template_item_id"] == str(item.id)
    assert result[0]["data_points"][0]["value"] == Decimal("30")


async def test_get_anomaly_stats_counts_our_equipment(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """异常热力统计:本设备一条异常记录 → 排行中总数1/异常1/异常率100。"""
    item = await _item(db_session, numeric_template.id)
    await _submit_and_complete(
        db_session,
        inspector,
        equipment,
        numeric_template,
        [
            {
                "template_item_id": item.id,
                "result": "异常",
                "actual_value": "",
                "remark": "温度过高",
            }
        ],
    )

    stats = await get_anomaly_stats(
        db_session, from_date=date(2026, 1, 1), to_date=date(2026, 12, 31)
    )

    # 共享库需按本设备过滤,避免其他测试数据干扰
    eq_entry = next(
        (
            r
            for r in stats["equipment_ranking"]
            if r["equipment_id"] == str(equipment.id)
        ),
        None,
    )
    assert eq_entry is not None
    assert eq_entry["total_count"] == 1
    assert eq_entry["abnormal_count"] == 1
    assert eq_entry["anomaly_rate"] == 100.0

    item_entry = next(
        (
            r
            for r in stats["item_ranking"]
            if r["template_item_id"] == str(item.id)
        ),
        None,
    )
    assert item_entry is not None
    assert item_entry["abnormal_count"] == 1

    assert isinstance(stats["monthly_trend"], list)
    for m in stats["monthly_trend"]:
        assert {"month", "normal", "abnormal", "skip", "total"} <= set(m.keys())


async def test_get_analytics_equipment_list_filters_numeric(
    db_session: AsyncSession,
    inspector: User,
    equipment: Equipment,
    numeric_template: InspectionTemplate,
) -> None:
    """可选设备列表:仅含有数值型记录的设备,含数值项数量与最近巡检日期。"""
    item = await _item(db_session, numeric_template.id)
    await _submit_and_complete(
        db_session,
        inspector,
        equipment,
        numeric_template,
        [{"template_item_id": item.id, "result": "正常", "actual_value": "25.3"}],
    )

    # 用唯一设备编号做关键字,隔离共享库其他数据
    rows = await get_analytics_equipment_list(db_session, keyword=equipment.equipment_no)
    assert len(rows) == 1
    row = rows[0]
    assert row["equipment_id"] == str(equipment.id)
    assert row["equipment_no"] == equipment.equipment_no
    assert row["numeric_item_count"] == 1
    assert row["latest_inspection_date"] != ""


# ══════════ cron 计算与校验 ══════════
def test_compute_next_cron_five_segment() -> None:
    """5 段 cron(min hour dom mon dow)计算下次触发,带应用时区。"""
    base = datetime(2026, 7, 11, 8, 0, tzinfo=app_time.APP_TZ)
    nxt = compute_next_cron("0 12 * * *", base)
    assert nxt.hour == 12
    assert nxt.minute == 0
    assert nxt > base
    assert nxt.tzinfo == app_time.APP_TZ


def test_compute_next_cron_six_segment() -> None:
    """6 段 cron(sec min hour dom mon dow)同样支持,秒位在最前。"""
    base = datetime(2026, 7, 11, 8, 0, tzinfo=app_time.APP_TZ)
    nxt = compute_next_cron("0 0 12 * * *", base)
    assert nxt.hour == 12
    assert nxt.minute == 0
    assert nxt > base


def test_validate_cron_accepts_valid() -> None:
    """合法 cron(5 段与 6 段)校验通过,不抛异常。"""
    _validate_cron("0 8 * * *")
    _validate_cron("30 0 8 * * *")


@pytest.mark.parametrize("bad", ["not a cron", "99 99 99 99 99", "60 0 * * *", ""])
def test_validate_cron_rejects_invalid(bad: str) -> None:
    """非法 cron 表达式应抛 AppException,消息含「无效的 cron 表达式」。"""
    with pytest.raises(AppException) as exc:
        _validate_cron(bad)
    assert "无效的 cron 表达式" in str(exc.value.message)


# ══════════ 路线定时任务 ══════════
@pytest.fixture
async def route(db_session: AsyncSession, inspector: User) -> InspectionRoute:
    """一条巡检路线,供定时任务测试挂载。"""
    ctx = EquipmentAccessContext(user=inspector, data_scope="all")
    return await create_route(
        db_session,
        {"name": f"巡检路线-{uuid.uuid4().hex[:8]}"},
        ctx,
    )


async def test_create_schedule_computes_next_trigger(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """创建定时任务:校验路线存在与 cron 合法,并算出 next_trigger_at。"""
    schedule = await create_schedule(
        db_session,
        route.id,
        {
            "cron_expression": "0 8 * * *",
            "assigned_to": inspector.id,
            "is_active": True,
        },
    )
    assert schedule.cron_expression == "0 8 * * *"
    assert schedule.is_active is True
    assert schedule.next_trigger_at is not None
    assert schedule.next_trigger_at.hour == 8
    # route_id / assigned_to 直接以 UUID 类型断言(与模型声明一致)
    assert schedule.route_id == route.id
    assert schedule.assigned_to == inspector.id


async def test_create_schedule_returns_uuid_typed_ids(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """新建定时任务返回对象的 route_id/assigned_to 应为 UUID 类型(与模型声明一致)。"""
    schedule = await create_schedule(
        db_session,
        route.id,
        {"cron_expression": "0 8 * * *", "assigned_to": inspector.id},
    )
    assert isinstance(schedule.route_id, uuid.UUID)
    assert isinstance(schedule.assigned_to, uuid.UUID)
    assert schedule.route_id == route.id
    assert schedule.assigned_to == inspector.id


async def test_create_schedule_invalid_cron_rejected(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """创建定时任务时 cron 非法应阻断。"""
    with pytest.raises(AppException) as exc:
        await create_schedule(
            db_session,
            route.id,
            {"cron_expression": "bad cron", "assigned_to": inspector.id},
        )
    assert "无效的 cron 表达式" in str(exc.value.message)


async def test_create_schedule_route_not_found(
    db_session: AsyncSession,
    inspector: User,
) -> None:
    """路线不存在时创建定时任务应抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await create_schedule(
            db_session,
            uuid.uuid4(),
            {"cron_expression": "0 8 * * *", "assigned_to": inspector.id},
        )


async def test_get_schedules_by_route_populates_assignee_name(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """按路线查询定时任务,响应含巡检人姓名。"""
    await create_schedule(
        db_session,
        route.id,
        {"cron_expression": "0 8 * * *", "assigned_to": inspector.id},
    )
    schedules = await get_schedules_by_route(db_session, route.id)
    assert len(schedules) == 1
    assert schedules[0].cron_expression == "0 8 * * *"
    assert schedules[0].assignee_name == inspector.name


async def test_update_schedule_recomputes_next_trigger(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """更新 cron 时重新计算 next_trigger_at。"""
    schedule = await create_schedule(
        db_session,
        route.id,
        {"cron_expression": "0 8 * * *", "assigned_to": inspector.id},
    )
    updated = await update_schedule(
        db_session, schedule.id, {"cron_expression": "0 9 * * *"}
    )
    assert updated.cron_expression == "0 9 * * *"
    assert updated.next_trigger_at is not None
    assert updated.next_trigger_at.hour == 9


async def test_update_schedule_can_clear_assignee(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """更新时可将巡检人清空为 None。"""
    schedule = await create_schedule(
        db_session,
        route.id,
        {"cron_expression": "0 8 * * *", "assigned_to": inspector.id},
    )
    updated = await update_schedule(db_session, schedule.id, {"assigned_to": None})
    assert updated.assigned_to is None


async def test_delete_schedule(
    db_session: AsyncSession,
    inspector: User,
    route: InspectionRoute,
) -> None:
    """删除定时任务后再查询应不可见。"""
    schedule = await create_schedule(
        db_session,
        route.id,
        {"cron_expression": "0 8 * * *", "assigned_to": inspector.id},
    )
    assert await delete_schedule(db_session, schedule.id) is True
    assert await get_schedule_by_id(db_session, schedule.id) is None


async def test_delete_schedule_not_found(db_session: AsyncSession) -> None:
    """删除不存在的定时任务应抛 NotFoundException。"""
    with pytest.raises(NotFoundException):
        await delete_schedule(db_session, uuid.uuid4())
