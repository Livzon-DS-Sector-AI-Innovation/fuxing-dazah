"""巡检数值类型：解析函数与提交阻断测试。"""

import uuid
from decimal import Decimal, InvalidOperation
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import Equipment, Location
from app.modules.equipment.models.inspection_template import (
    InspectionTemplate,
    InspectionTemplateItem,
)
from app.modules.equipment.service.inspection import (
    _parse_numeric_value,
    complete_task,
    create_task,
    start_task,
    submit_equipment_check,
)
from app.platform.identity.models import User


@pytest.fixture(autouse=True)
def _mock_notifications():
    """Mock 飞书通知，避免测试触发外部调用。"""
    with (
        patch(
            "app.modules.equipment.service.inspection_notification."
            "send_inspection_start_notification",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.equipment.service.inspection_notification."
            "send_work_order_notification",
            new_callable=AsyncMock,
        ),
    ):
        yield


def test_parse_numeric_value():
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


@pytest.fixture
async def inspector(db_session: AsyncSession) -> User:
    user = User(name="巡检员", employee_no=f"EMP-{uuid.uuid4().hex[:8]}")
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
async def equipment(db_session: AsyncSession) -> Equipment:
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
    r = await db.execute(
        select(InspectionTemplateItem).where(
            InspectionTemplateItem.template_id == template_id
        )
    )
    return r.scalars().first()


async def _running_task(db, inspector, equipment, template):
    from datetime import UTC, datetime

    # 服务层现要求 ctx（权限重构后）；测试用超管范围 ctx，跳过归属校验。
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


async def test_numeric_value_parsed_and_stored(
    db_session, inspector, equipment, numeric_template
):
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
    db_session, inspector, equipment, numeric_template
):
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


def test_template_item_schema_has_type_fields():
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


async def test_numeric_empty_value_not_blocked(
    db_session, inspector, equipment, numeric_template
):
    task = await _running_task(db_session, inspector, equipment, numeric_template)
    item = await _item(db_session, numeric_template.id)

    created = await submit_equipment_check(
        db_session,
        task.id,
        equipment.id,
        [{"template_item_id": item.id, "result": "跳过", "actual_value": ""}],
    )
    assert created[0].numeric_value is None


# ── Schema tests (analytics) ──

from decimal import Decimal as _D
from datetime import date as _date


def test_trend_schema_roundtrip():
    from app.modules.equipment.schemas.inspection import (
        TrendDataPoint,
        TrendSeries,
        TrendResponse,
    )

    dp = TrendDataPoint(date=_date(2026, 7, 1), value=_D("25.3"), result="正常")
    s = TrendSeries(
        template_item_id="550e8400-e29b-41d4-a716-446655440000",
        item_name="电机温度",
        unit="℃",
        data_points=[dp],
    )
    r = TrendResponse(equipment_name="R-101", equipment_no="EQ-001", series=[s])
    assert r.series[0].data_points[0].value == _D("25.3")


def test_anomaly_schema_roundtrip():
    from app.modules.equipment.schemas.inspection import (
        AnomalyRankingItem,
        AnomalyMonthlyItem,
        AnomalyResponse,
    )

    a = AnomalyResponse(
        equipment_ranking=[
            AnomalyRankingItem(
                equipment_id="550e8400-e29b-41d4-a716-446655440000",
                equipment_name="R-101",
                equipment_no="EQ-001",
                total_count=30,
                abnormal_count=5,
                anomaly_rate=16.7,
            )
        ],
        item_ranking=[
            AnomalyRankingItem(
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


def test_equipment_list_schema():
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


# ── Repository tests (analytics) ──

async def test_get_trend_data_returns_series(
    db_session, inspector, equipment, numeric_template
):
    """参数趋势查询返回正确的数据点结构。"""
    from datetime import UTC, datetime

    from app.modules.equipment.repository.inspection import get_trend_data

    item = (
        await db_session.execute(
            select(InspectionTemplateItem).where(
                InspectionTemplateItem.template_id == numeric_template.id
            )
        )
    ).scalars().first()

    ctx = EquipmentAccessContext(user=inspector, data_scope="all")
    task = await create_task(
        db_session,
        {
            "plan_type": "设备巡检",
            "equipment_id": equipment.id,
            "template_ids": [numeric_template.id],
            "assigned_to": inspector.id,
            "planned_time": datetime.now(UTC),
        },
        ctx=ctx,
    )
    task = await start_task(db_session, task.id, ctx=ctx)
    await submit_equipment_check(
        db_session,
        task.id,
        equipment.id,
        [{"template_item_id": item.id, "result": "正常", "actual_value": "25.3"}],
    )
    await complete_task(db_session, task.id, ctx=ctx)

    result = await get_trend_data(
        db_session,
        equipment.id,
        [item.id],
        from_date=datetime(2026, 1, 1).date(),
        to_date=datetime(2026, 12, 31).date(),
    )
    assert len(result) == 1
    assert result[0]["item_name"] == "电机温度"
    assert result[0]["unit"] == "℃"
    assert len(result[0]["data_points"]) == 1
    assert result[0]["data_points"][0]["value"] == Decimal("25.3")
