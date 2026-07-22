"""设备状态日志 service：状态变更记录、时间开动率计算。"""

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import time as app_time
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models import EquipmentStatusLog
from app.modules.equipment.repository import status_log as repo
from app.modules.equipment.schemas.status_log import (
    AvailabilityItem,
    AvailabilityResponse,
    EquipmentStatusLogItem,
)

POWER_ON = "开机"


async def record_status_change(
    db: AsyncSession,
    equipment_id: uuid.UUID,
    old_status: str | None,
    new_status: str,
    *,
    source: str,
    operator_id: uuid.UUID | None = None,
    log_type: str = "status",
) -> None:
    """记录一次设备状态/运行状态变更；状态未变化时不落记录"""
    if old_status == new_status:
        return
    db.add(
        EquipmentStatusLog(
            equipment_id=equipment_id,
            log_type=log_type,
            old_status=old_status,
            new_status=new_status,
            changed_at=app_time.now(),
            source=source,
            created_by=operator_id,
        )
    )
    await db.flush()


def compute_status_durations(
    events: list[tuple[datetime, str]],
    range_start: datetime,
    range_end: datetime,
) -> dict[str, float]:
    """按状态事件重建区间，返回范围内各状态的时长（秒）。

    events: (changed_at, new_status) 升序，需包含 range_end 之前的全部事件。
    设备在范围中途才有首条记录时，只统计有记录之后的时间。
    """
    durations: dict[str, float] = {}
    if not events or range_start >= range_end:
        return durations

    # 区间起点状态 = range_start 前最后一条事件；无则从首条事件时刻起算
    current_status: str | None = None
    cursor = range_start
    idx = 0
    for i, (t, s) in enumerate(events):
        if t <= range_start:
            current_status = s
            idx = i + 1
        else:
            break

    for t, s in events[idx:]:
        if t >= range_end:
            break
        if current_status is not None and t > cursor:
            durations[current_status] = (
                durations.get(current_status, 0.0) + (t - cursor).total_seconds()
            )
        cursor = max(cursor, t)
        current_status = s

    if current_status is not None and range_end > cursor:
        durations[current_status] = (
            durations.get(current_status, 0.0) + (range_end - cursor).total_seconds()
        )
    return durations


async def get_status_logs(
    db: AsyncSession,
    equipment_id: uuid.UUID,
) -> list[EquipmentStatusLogItem]:
    """获取单台设备的状态变更历史"""
    logs = await repo.get_status_logs_by_equipment(db, equipment_id)
    return [EquipmentStatusLogItem.model_validate(log) for log in logs]


async def get_availability(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    from_date: date,
    to_date: date,
) -> AvailabilityResponse:
    """计算时间范围内各设备的时间开动率。

    开动率 = 开机时长 / 有运行记录的日历时长（开机+停机）；报废设备不参与统计。
    结束时刻取 min(to_date 当天末尾, 当前时间)，未来时间不计入。
    """
    tz = app_time.APP_TZ
    range_start = datetime.combine(from_date, time.min, tzinfo=tz)
    range_end = min(
        datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=tz),
        app_time.now(),
    )

    equipments = await repo.get_equipments_for_availability(db, ctx)
    events_map = await repo.get_status_events_until(
        db, [row.id for row in equipments], range_end, log_type="running"
    )

    items: list[AvailabilityItem] = []
    sum_available = 0.0
    sum_total = 0.0
    for row in equipments:
        durations = compute_status_durations(
            events_map.get(row.id, []), range_start, range_end
        )
        available = durations.get(POWER_ON, 0.0)
        total = sum(durations.values())
        sum_available += available
        sum_total += total
        items.append(
            AvailabilityItem(
                equipment_id=row.id,
                equipment_no=row.equipment_no,
                name=row.name,
                current_status=row.status,
                current_running_status=row.running_status,
                status_hours={k: round(v / 3600, 2) for k, v in durations.items()},
                available_hours=round(available / 3600, 2),
                total_hours=round(total / 3600, 2),
                availability_rate=round(available / total, 4) if total > 0 else None,
            )
        )

    return AvailabilityResponse(
        from_date=from_date,
        to_date=to_date,
        overall_rate=round(sum_available / sum_total, 4) if sum_total > 0 else None,
        items=items,
    )
