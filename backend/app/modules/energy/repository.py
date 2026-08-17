"""Energy database queries and persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Date, and_, cast, exists, func, not_, or_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.energy.models import (
    EnergyAlertRecord,
    EnergyAlertRule,
    EnergyCollectLog,
    EnergyDailyPushConfig,
    EnergyData,
    EnergyDeviceConfig,
    EnergyErrorLog,
    EnergyNitrogenPushConfig,
    EnergyTypeConfig,
    EnergyWorkshopConfig,
    PricePeriod,
)
from app.platform.identity.models import Department

# ── 设备配置 ──


async def create_device_config(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyDeviceConfig:
    """创建设备配置（使用原始 INSERT 避免 BaseModel FK 解析异常）。"""
    stmt = pg_insert(EnergyDeviceConfig).values(**data).returning(EnergyDeviceConfig)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_device_config_by_id(
    db: AsyncSession, config_id: UUID
) -> EnergyDeviceConfig | None:
    result = await db.execute(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_device_names_by_ids(
    db: AsyncSession, ids: list[UUID]
) -> dict[UUID, str]:
    """获取设备名称映射（含已删除设备，仅用于推送配置页面的名称回显）。"""
    if not ids:
        return {}
    result = await db.execute(
        select(EnergyDeviceConfig.id, EnergyDeviceConfig.device_name).where(
            EnergyDeviceConfig.id.in_(ids)
        )
    )
    return {row.id: row.device_name for row in result.all()}


async def list_device_configs(
    db: AsyncSession,
    *,
    platform_code: str | None = None,
    energy_type: str | None = None,
    workshop: str | None = None,
    is_enabled: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyDeviceConfig], int]:
    query = select(EnergyDeviceConfig).where(
        EnergyDeviceConfig.is_deleted == False  # noqa: E712
    )
    if platform_code:
        query = query.where(EnergyDeviceConfig.platform_code == platform_code)
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)
    if workshop:
        query = query.where(EnergyDeviceConfig.workshop == workshop)
    if is_enabled is not None:
        query = query.where(EnergyDeviceConfig.is_enabled == is_enabled)
    if keyword:
        query = query.where(EnergyDeviceConfig.device_name.ilike(f"%{keyword}%"))

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyDeviceConfig.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_device_config(
    db: AsyncSession, config_id: UUID, data: dict[str, Any]
) -> EnergyDeviceConfig | None:
    """更新设备配置，更新后 re-fetch 避免 identity map 返回旧值。"""
    await db.execute(
        sa_update(EnergyDeviceConfig)
        .where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .values(**data)
    )
    await db.flush()
    # Re-fetch 获取最新值（避免 session identity map 返回旧对象）
    result = await db.execute(
        select(EnergyDeviceConfig)
        .where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def delete_device_config(db: AsyncSession, config_id: UUID) -> bool:
    """软删除设备配置（处理重复添加→删除的隐形约束冲突）。"""
    # 先查出要删除的设备信息
    obj = await db.scalar(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    if obj is None:
        return False

    # 若已有同编码的已删除记录，先将其编码改名释放唯一约束槽位
    existing_deleted = await db.scalar(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.platform_code == obj.platform_code,
            EnergyDeviceConfig.platform_device_code == obj.platform_device_code,
            EnergyDeviceConfig.is_deleted == True,  # noqa: E712
            EnergyDeviceConfig.id != config_id,
        )
    )
    if existing_deleted is not None:
        await db.execute(
            sa_update(EnergyDeviceConfig)
            .where(EnergyDeviceConfig.id == existing_deleted.id)
            .values(platform_device_code=f"{existing_deleted.platform_device_code}__del_{existing_deleted.id}")
        )

    # 软删除当前设备
    await db.execute(
        sa_update(EnergyDeviceConfig)
        .where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return True


async def exists_device_config(
    db: AsyncSession,
    platform_code: str,
    platform_device_code: str,
    exclude_id: UUID | None = None,
) -> bool:
    query = select(func.count()).where(
        EnergyDeviceConfig.platform_code == platform_code,
        EnergyDeviceConfig.platform_device_code == platform_device_code,
        EnergyDeviceConfig.is_deleted == False,  # noqa: E712
    )
    if exclude_id:
        query = query.where(EnergyDeviceConfig.id != exclude_id)
    count = (await db.execute(query)).scalar() or 0
    return count > 0


async def get_enabled_devices_by_platform(
    db: AsyncSession, platform_code: str
) -> list[EnergyDeviceConfig]:
    result = await db.execute(
        select(EnergyDeviceConfig).where(
            EnergyDeviceConfig.platform_code == platform_code,
            EnergyDeviceConfig.is_enabled == True,  # noqa: E712
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def get_latest_energy_data(
    db: AsyncSession, device_config_id: UUID
) -> EnergyData | None:
    """获取指定设备最近一条能耗数据记录。"""
    result = await db.execute(
        select(EnergyData)
        .where(
            EnergyData.device_config_id == device_config_id,
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .order_by(EnergyData.timestamp.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_distinct_enabled_platforms(db: AsyncSession) -> list[str]:
    """返回所有有启用设备的平台 code 列表（去重）。"""
    result = await db.execute(
        select(EnergyDeviceConfig.platform_code)
        .where(
            EnergyDeviceConfig.is_enabled == True,  # noqa: E712
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .distinct()
    )
    return list(result.scalars().all())


# ── 能耗数据 ──


async def upsert_energy_data(
    db: AsyncSession,
    device_config_id: UUID,
    timestamp: datetime,
    value: float,
    unit: str,
    platform_raw_data: dict[str, Any] | None = None,
) -> EnergyData:
    stmt = pg_insert(EnergyData).values(
        device_config_id=device_config_id,
        timestamp=timestamp,
        value=value,
        unit=unit,
        platform_raw_data=platform_raw_data,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_energy_data_device_timestamp",
        set_={
            "value": value,
            "platform_raw_data": platform_raw_data,
            "collected_at": func.now(),
        },
    )
    returning_stmt = stmt.returning(EnergyData)
    result = await db.execute(returning_stmt)
    return result.scalar_one()


async def list_energy_data(
    db: AsyncSession,
    *,
    device_config_id: UUID | None = None,
    energy_type: str | None = None,
    workshop: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyData], int]:
    query = select(EnergyData).where(
        EnergyData.is_deleted == False  # noqa: E712
    )
    if device_config_id:
        query = query.where(EnergyData.device_config_id == device_config_id)
    if start_time:
        query = query.where(EnergyData.timestamp >= start_time)
    if end_time:
        query = query.where(EnergyData.timestamp <= end_time)
    if energy_type or workshop:
        query = query.join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        ).where(
            EnergyDeviceConfig.is_deleted == False  # noqa: E712
        )
        if energy_type:
            query = query.where(EnergyDeviceConfig.energy_type == energy_type)
        if workshop:
            query = query.where(EnergyDeviceConfig.workshop == workshop)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyData.timestamp.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def list_energy_data_history(
    db: AsyncSession,
    *,
    device_config_id: UUID | None = None,
    energy_type: str | None = None,
    workshop: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    keyword: str | None = None,
    granularity: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询能耗数据历史明细，JOIN 设备配置表返回完整信息。

    granularity='daily': 按 (device_config_id, 日期) 逐小时数据 SUM 聚合。
    granularity='hourly': 返回原始逐小时记录。
    """
    from sqlalchemy import text

    where_clauses = [
        "d.is_deleted = false",
        "c.is_deleted = false",
    ]
    params: dict[str, Any] = {}

    if device_config_id:
        where_clauses.append("d.device_config_id = :device_config_id")
        params["device_config_id"] = device_config_id
    if energy_type:
        where_clauses.append("c.energy_type = :energy_type")
        params["energy_type"] = energy_type
    if workshop:
        where_clauses.append("c.workshop = :workshop")
        params["workshop"] = workshop
    if start_time:
        where_clauses.append("d.timestamp >= :start_time")
        params["start_time"] = start_time
    if end_time:
        where_clauses.append("d.timestamp <= :end_time")
        params["end_time"] = end_time
    if keyword:
        where_clauses.append(
            "(c.device_name ILIKE :keyword OR c.platform_device_code ILIKE :keyword)"
        )
        params["keyword"] = f"%{keyword}%"
    # Note: granularity filter no longer uses daily_sum flag;
    # daily mode uses SQL aggregation instead.

    where_sql = " AND ".join(where_clauses)

    if granularity == "daily":
        # ── 日汇总：按 device + 日期 SUM 聚合 ──
        count_sql = (
            f"SELECT COUNT(*) FROM ("
            f"SELECT 1 FROM energy.energy_data d "
            f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
            f"WHERE {where_sql} "
            f"GROUP BY d.device_config_id, DATE(d.timestamp)"
            f") sub"
        )
        query_sql = (
            f"SELECT "
            f"d.device_config_id::text || '_' || DATE(d.timestamp)::text AS id, "
            f"d.device_config_id, c.device_name, c.platform_device_code, "
            f"c.energy_type, c.workshop, c.production_line, "
            f"DATE(d.timestamp) AS timestamp, "
            f"SUM(d.value) AS value, "
            f"COALESCE(MAX(tc.unit), MAX(d.unit)) AS unit, "
            f"MAX(d.collected_at) AS collected_at, "
            f"'true' AS granularity "
            f"FROM energy.energy_data d "
            f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
            f"LEFT JOIN energy.energy_type_configs tc ON c.energy_type = tc.type_code AND tc.is_deleted = false "
            f"WHERE {where_sql} "
            f"GROUP BY d.device_config_id, c.device_name, c.platform_device_code, "
            f"c.energy_type, c.workshop, c.production_line, DATE(d.timestamp) "
            f"ORDER BY DATE(d.timestamp) DESC "
            f"LIMIT :limit OFFSET :offset"
        )
    else:
        # ── 逐小时：返回原始记录 ──
        count_sql = (
            f"SELECT COUNT(*) FROM energy.energy_data d "
            f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
            f"WHERE {where_sql}"
        )
        query_sql = (
            f"SELECT d.id, d.device_config_id, c.device_name, c.platform_device_code, "
            f"c.energy_type, c.workshop, c.production_line, "
            f"d.timestamp, d.value, COALESCE(tc.unit, d.unit) AS unit, d.collected_at, "
            f"'false' AS granularity "
            f"FROM energy.energy_data d "
            f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
            f"LEFT JOIN energy.energy_type_configs tc ON c.energy_type = tc.type_code AND tc.is_deleted = false "
            f"WHERE {where_sql} "
            f"ORDER BY d.timestamp DESC "
            f"LIMIT :limit OFFSET :offset"
        )

    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    result = await db.execute(text(query_sql), params)
    rows = result.all()
    items = [
        {
            "id": str(row.id),
            "device_config_id": str(row.device_config_id),
            "device_name": row.device_name,
            "platform_device_code": row.platform_device_code,
            "energy_type": row.energy_type,
            "workshop": row.workshop,
            "production_line": row.production_line,
            "timestamp": row.timestamp,
            "value": float(row.value),
            "unit": row.unit,
            "collected_at": row.collected_at,
            "granularity": row.granularity,
        }
        for row in rows
    ]
    return items, total


def _department_priority_subquery(device_config: type[EnergyDeviceConfig]) -> Any:
    """部门优先子条件：部门级设备始终保留，区域级仅在无部门级时保留。

    避免同一车间下部门级总表和区域级子表数据重复累加。
    """
    inner_dept = EnergyDeviceConfig.__table__.alias("d2")
    return or_(
        device_config.is_region_level == False,  # noqa: E712
        not_(
            exists().where(
                inner_dept.c.workshop == device_config.workshop,
                inner_dept.c.energy_type == device_config.energy_type,
                inner_dept.c.is_region_level == False,  # noqa: E712
                inner_dept.c.is_enabled == True,       # noqa: E712
                inner_dept.c.is_deleted == False,      # noqa: E712
            )
        ),
    )


def _total_preferred_filter(device_config: type[EnergyDeviceConfig]) -> Any:
    """总耗优先过滤器（用于总览卡片、趋势图、峰谷默认、车间预警）。

    1. 排除 stat_role='excluded'
    2. 存在区域级 total（is_region_level=True）→ 只用 total，排除所有 normal
    3. 同车间存在 total → 只用 total，排除同车间 normal
    4. 无 total → 用 normal，按部门优先去重
    """
    inner_total = EnergyDeviceConfig.__table__.alias("d_total")
    region_total = EnergyDeviceConfig.__table__.alias("d_region")
    return and_(
        device_config.stat_role != 'excluded',
        or_(
            device_config.stat_role == 'total',
            and_(
                device_config.stat_role == 'normal',
                not_(
                    or_(
                        # 同车间存在 total 设备 → 排除本车间 normal
                        exists().where(
                            inner_total.c.workshop == device_config.workshop,
                            inner_total.c.energy_type == device_config.energy_type,
                            inner_total.c.stat_role == 'total',
                            inner_total.c.is_enabled == True,       # noqa: E712
                            inner_total.c.is_deleted == False,      # noqa: E712
                        ),
                        # 存在区域级 total 设备 → 排除所有 normal
                        exists().where(
                            region_total.c.energy_type == device_config.energy_type,
                            region_total.c.stat_role == 'total',
                            region_total.c.is_region_level == True,  # noqa: E712
                            region_total.c.is_enabled == True,       # noqa: E712
                            region_total.c.is_deleted == False,      # noqa: E712
                        ),
                    )
                ),
                _department_priority_subquery(device_config),
            ),
        ),
    )


def _normal_only_filter(device_config: type[EnergyDeviceConfig]) -> Any:
    """普通设备过滤器（用于部门排名、区域分布、设备分布）。

    只用 stat_role='normal' 的设备，按部门优先去重。
    排除 total（总耗设备不参与细分排名）和 excluded。
    """
    return and_(
        device_config.stat_role == 'normal',
        _department_priority_subquery(device_config),
    )


async def get_energy_statistics(
    db: AsyncSession,
    *,
    group_by: str,
    energy_type: str | None = None,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    if group_by == "workshop":
        group_col = EnergyDeviceConfig.workshop
        extra_cols = []
    elif group_by == "production_line":
        group_col = func.coalesce(EnergyDeviceConfig.production_line, '部门级')
        # 同时带上车间，供前端下钻过滤
        extra_cols = [EnergyDeviceConfig.workshop.label("workshop")]
    else:
        group_col = EnergyDeviceConfig.device_name
        extra_cols = []

    query = (
        select(
            group_col.label("group_key"),
            EnergyDeviceConfig.energy_type,
            func.sum(EnergyData.value).label("total_value"),
            EnergyTypeConfig.unit,
            func.count(EnergyData.id).label("data_count"),
            *extra_cols,
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .join(
            EnergyTypeConfig,
            (EnergyDeviceConfig.energy_type == EnergyTypeConfig.type_code)
            & (EnergyTypeConfig.is_deleted == False),  # noqa: E712
            isouter=True,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyData.timestamp >= start_time,
            EnergyData.timestamp <= end_time,
            _normal_only_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .group_by(group_col, EnergyDeviceConfig.energy_type, EnergyTypeConfig.unit, *extra_cols)
    )
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)

    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "group_key": row.group_key,
            "energy_type": row.energy_type,
            "total_value": float(row.total_value or 0),
            "unit": row.unit,
            "data_count": row.data_count,
            **({"workshop": row.workshop} if hasattr(row, "workshop") and row.workshop is not None else {}),
        }
        for row in rows
    ]


# ── 采集日志 ──


# ── 总览统计 ──


async def get_overview_summary(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """按能源类型汇总能耗，所有设备统一 SUM 聚合。"""
    query = (
        select(
            EnergyDeviceConfig.energy_type,
            func.sum(EnergyData.value).label("total_value"),
            EnergyTypeConfig.unit,
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .join(
            EnergyTypeConfig,
            (EnergyDeviceConfig.energy_type == EnergyTypeConfig.type_code)
            & (EnergyTypeConfig.is_deleted == False),  # noqa: E712
            isouter=True,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyData.timestamp >= start_time,
            EnergyData.timestamp <= end_time,
            _total_preferred_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .group_by(EnergyDeviceConfig.energy_type, EnergyTypeConfig.unit)
    )
    result = await db.execute(query)
    return [
        {
            "energy_type": row.energy_type,
            "total_value": float(row.total_value or 0),
            "unit": row.unit,
        }
        for row in result.all()
    ]


async def get_overview_trend(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    energy_type: str | None = None,
    granularity: str = "hourly",
) -> list[dict[str, Any]]:
    """获取能耗趋势数据。

    granularity: "hourly" 按小时分组, "daily" 按天分组（小时数据自动聚合为日汇总）
    所有设备统一按 granularity 和 energy_type 聚合。
    """
    if granularity == "daily":
        time_col = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp)).label("time_point")
        group_cols = [time_col, EnergyDeviceConfig.energy_type]
        order_col = time_col
    else:
        time_col = EnergyData.timestamp
        group_cols = [EnergyData.timestamp, EnergyDeviceConfig.energy_type]
        order_col = EnergyData.timestamp

    def _row_to_dict(row: Any) -> dict[str, Any]:
        return {
            "time": (
                row.time_point.isoformat()
                if granularity == "daily"
                else row.timestamp.isoformat()
            ),
            "value": float(row.total_value or 0),
            "type": row.energy_type,
        }

    query = (
        select(
            time_col,
            EnergyDeviceConfig.energy_type,
            func.sum(EnergyData.value).label("total_value"),
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyData.timestamp >= start_time,
            EnergyData.timestamp <= end_time,
            _total_preferred_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .group_by(*group_cols)
        .order_by(order_col.asc())
    )
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)

    result = await db.execute(query)
    return sorted(
        [_row_to_dict(row) for row in result.all()],
        key=lambda r: r["time"],
    )


# ── 能耗数据删除 ──


async def delete_energy_data(db: AsyncSession, data_id: UUID) -> bool:
    """软删除单条能耗数据。"""
    result = await db.execute(
        sa_update(EnergyData)
        .where(
            EnergyData.id == data_id,
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return result.rowcount > 0  # type: ignore[attr-defined,no-any-return]


async def batch_delete_energy_data(db: AsyncSession, ids: list[UUID]) -> int:
    """批量软删除能耗数据，返回删除条数。"""
    result = await db.execute(
        sa_update(EnergyData)
        .where(
            EnergyData.id.in_(ids),
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return result.rowcount  # type: ignore[attr-defined,no-any-return]


async def get_energy_data_by_id(db: AsyncSession, data_id: UUID) -> EnergyData | None:
    result = await db.execute(
        select(EnergyData).where(
            EnergyData.id == data_id,
            EnergyData.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def update_energy_data_value(
    db: AsyncSession, data_id: UUID, value: float,
) -> bool:
    """修改能耗数据的值。返回 True 表示更新成功。"""
    result = await db.execute(
        sa_update(EnergyData)
        .where(
            EnergyData.id == data_id,
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .values(value=value)
    )
    return result.rowcount > 0  # type: ignore[attr-defined,no-any-return]


async def create_collect_log(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyCollectLog:
    """写入采集日志（使用原始 INSERT 避免 BaseModel FK 解析异常）。"""
    stmt = pg_insert(EnergyCollectLog).values(**data).returning(EnergyCollectLog)
    result = await db.execute(stmt)
    return result.scalar_one()


async def list_collect_logs(
    db: AsyncSession,
    *,
    platform_code: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyCollectLog], int]:
    query = select(EnergyCollectLog).where(
        EnergyCollectLog.is_deleted == False  # noqa: E712
    )
    if platform_code:
        query = query.where(EnergyCollectLog.platform_code == platform_code)
    if status:
        query = query.where(EnergyCollectLog.status == status)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyCollectLog.collect_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def clear_collect_logs(db: AsyncSession) -> int:
    """清空所有采集日志（软删除）。返回清除的记录数。"""
    result = await db.execute(
        sa_update(EnergyCollectLog)
        .where(EnergyCollectLog.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    return result.rowcount  # type: ignore[attr-defined,no-any-return]


async def get_collect_log_detail(
    db: AsyncSession,
    log_id: UUID,
    time_window_seconds: int = 120,
) -> tuple[EnergyCollectLog | None, list[tuple[EnergyData, EnergyDeviceConfig]]]:
    """获取采集日志详情及关联的能耗数据。

    通过 platform_code + 时间窗口匹配 EnergyData 和 EnergyCollectLog。
    窗口从 collect_time（采集开始）前 120s 到 created_at（日志写入 = 采集结束）后 120s，
    确保覆盖逐小时回退等多设备长时间采集场景。
    """
    log = await db.scalar(
        select(EnergyCollectLog).where(
            EnergyCollectLog.id == log_id,
            EnergyCollectLog.is_deleted == False,  # noqa: E712
        )
    )
    if log is None:
        return None, []

    # 下界：采集开始前 buffer；上界：日志写入后 buffer
    # created_at 在整批采集结束后才写入，保证覆盖所有设备的 collected_at
    window_start = log.collect_time - timedelta(seconds=time_window_seconds)
    window_end = log.created_at + timedelta(seconds=time_window_seconds)

    query = (
        select(EnergyData, EnergyDeviceConfig)
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyDeviceConfig.platform_code == log.platform_code,
            EnergyData.collected_at >= window_start,
            EnergyData.collected_at <= window_end,
            EnergyData.is_deleted == False,  # noqa: E712
        )
        .order_by(EnergyData.timestamp.desc())
    )
    result = await db.execute(query)
    rows = list(result.all())

    return log, rows


# ── 接口错误日志 ──


async def create_error_log(
    db: AsyncSession,
    *,
    method: str,
    path: str,
    path_params: dict[str, Any],
    query_params: dict[str, Any],
    exception_type: str,
    message: str,
    traceback: str,
    request_id: str | None,
) -> EnergyErrorLog:
    """写入一条接口错误日志。"""
    obj = EnergyErrorLog(
        method=method,
        path=path,
        path_params=path_params,
        query_params=query_params,
        exception_type=exception_type,
        message=message,
        traceback=traceback,
        request_id=request_id,
    )
    db.add(obj)
    await db.flush()
    return obj


async def list_error_logs(
    db: AsyncSession,
    *,
    path_keyword: str | None = None,
    exception_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyErrorLog], int]:
    """分页查询接口错误日志（按创建时间倒序）。"""
    conditions = [EnergyErrorLog.is_deleted == False]  # noqa: E712
    if path_keyword:
        conditions.append(EnergyErrorLog.path.ilike(f"%{path_keyword}%"))
    if exception_type:
        conditions.append(EnergyErrorLog.exception_type == exception_type)

    total = await db.scalar(
        select(func.count()).select_from(EnergyErrorLog).where(*conditions)
    )
    result = await db.execute(
        select(EnergyErrorLog)
        .where(*conditions)
        .order_by(EnergyErrorLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), int(total or 0)


async def get_error_log(
    db: AsyncSession, error_id: UUID
) -> EnergyErrorLog | None:
    """查询单条接口错误日志。"""
    result = await db.execute(
        select(EnergyErrorLog).where(
            EnergyErrorLog.id == error_id,
            EnergyErrorLog.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def clear_error_logs(db: AsyncSession) -> int:
    """清空所有接口错误日志（软删除）。返回清除的记录数。"""
    result = await db.execute(
        sa_update(EnergyErrorLog)
        .where(EnergyErrorLog.is_deleted == False)  # noqa: E712
        .values(is_deleted=True)
    )
    return result.rowcount  # type: ignore[attr-defined,no-any-return]


# ── 预警规则 ──


async def create_alert_rule(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyAlertRule:
    """创建预警规则（使用原始 INSERT 避免 BaseModel FK 解析异常）。"""
    stmt = pg_insert(EnergyAlertRule).values(**data).returning(EnergyAlertRule)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_alert_rule_by_id(
    db: AsyncSession, rule_id: UUID
) -> EnergyAlertRule | None:
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.id == rule_id,
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_alert_rules_by_ids(
    db: AsyncSession, rule_ids: list[UUID]
) -> list[EnergyAlertRule]:
    """批量按ID查询预警规则（用于填充冗余字段）。"""
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.id.in_(rule_ids),
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def list_alert_rules(
    db: AsyncSession,
    *,
    energy_type: str | None = None,
    alert_level: str | None = None,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyAlertRule], int]:
    query = select(EnergyAlertRule).where(
        EnergyAlertRule.is_deleted == False  # noqa: E712
    )
    if energy_type:
        query = query.where(EnergyAlertRule.energy_type == energy_type)
    if alert_level:
        query = query.where(EnergyAlertRule.alert_level == alert_level)
    if is_enabled is not None:
        query = query.where(EnergyAlertRule.is_enabled == is_enabled)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyAlertRule.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_alert_rule(
    db: AsyncSession, rule_id: UUID, data: dict[str, Any]
) -> EnergyAlertRule | None:
    """更新预警规则（使用原始 SQL 避免 BaseModel FK 解析异常）。"""
    result = await db.execute(
        sa_update(EnergyAlertRule)
        .where(
            EnergyAlertRule.id == rule_id,
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyAlertRule)
    )
    return result.scalar_one_or_none()


async def delete_alert_rule(db: AsyncSession, rule_id: UUID) -> bool:
    """软删除预警规则（使用原始 SQL 避免 BaseModel FK 解析异常）。"""
    result = await db.execute(
        sa_update(EnergyAlertRule)
        .where(
            EnergyAlertRule.id == rule_id,
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return result.rowcount > 0


# ── 预警记录 ──


async def create_alert_record(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyAlertRecord:
    """创建预警记录（使用原始 INSERT 避免 BaseModel FK 解析异常）。"""
    stmt = pg_insert(EnergyAlertRecord).values(**data).returning(EnergyAlertRecord)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_alert_record_by_id(
    db: AsyncSession, record_id: UUID
) -> EnergyAlertRecord | None:
    result = await db.execute(
        select(EnergyAlertRecord).where(
            EnergyAlertRecord.id == record_id,
            EnergyAlertRecord.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_alert_records(
    db: AsyncSession,
    *,
    energy_type: str | None = None,
    alert_level: str | None = None,
    status: str | None = None,
    workshop: str | None = None,
    workshop_not_null: bool = False,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyAlertRecord], int]:
    query = select(EnergyAlertRecord).where(
        EnergyAlertRecord.is_deleted == False  # noqa: E712
    )
    if energy_type:
        query = query.where(EnergyAlertRecord.energy_type == energy_type)
    if alert_level:
        query = query.where(EnergyAlertRecord.alert_level == alert_level)
    if status:
        query = query.where(EnergyAlertRecord.status == status)
    if workshop:
        query = query.where(EnergyAlertRecord.workshop == workshop)
    if workshop_not_null:
        query = query.where(EnergyAlertRecord.workshop.isnot(None))
    if start_time:
        query = query.where(EnergyAlertRecord.alert_time >= start_time)
    if end_time:
        query = query.where(EnergyAlertRecord.alert_time <= end_time)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyAlertRecord.alert_time.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def update_alert_record(
    db: AsyncSession, record_id: UUID, data: dict[str, Any]
) -> EnergyAlertRecord | None:
    """更新预警记录（使用原始 SQL 避免 BaseModel FK 解析异常）。"""
    result = await db.execute(
        sa_update(EnergyAlertRecord)
        .where(
            EnergyAlertRecord.id == record_id,
            EnergyAlertRecord.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyAlertRecord)
    )
    return result.scalar_one_or_none()


# ── 部门列表（供数据源配置下拉使用） ──


async def list_departments(db: AsyncSession) -> list[dict[str, Any]]:
    result = await db.execute(
        select(Department.feishu_department_id, Department.name)
        .where(
            Department.is_deleted == False,  # noqa: E712
            Department.status_is_deleted == False,  # noqa: E712
        )
        .order_by(Department.order, Department.name)
    )
    return [{"id": row.feishu_department_id, "name": row.name} for row in result.all()]


# ── 关联设备列表（供数据源配置下拉使用） ──


# ── 能源类型可视化配置 ──


async def create_type_config(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyTypeConfig:
    """创建能源类型配置（使用原始 INSERT 避免 BaseModel FK 解析异常）。"""
    stmt = pg_insert(EnergyTypeConfig).values(**data).returning(EnergyTypeConfig)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_type_config_by_id(
    db: AsyncSession, config_id: UUID
) -> EnergyTypeConfig | None:
    result = await db.execute(
        select(EnergyTypeConfig).where(
            EnergyTypeConfig.id == config_id,
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_type_config_by_code(
    db: AsyncSession, type_code: str
) -> EnergyTypeConfig | None:
    result = await db.execute(
        select(EnergyTypeConfig).where(
            EnergyTypeConfig.type_code == type_code,
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_type_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[EnergyTypeConfig], int]:
    query = select(EnergyTypeConfig).where(
        EnergyTypeConfig.is_deleted == False  # noqa: E712
    )
    if is_enabled is not None:
        query = query.where(EnergyTypeConfig.is_enabled == is_enabled)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyTypeConfig.sort_order.asc(), EnergyTypeConfig.created_at.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def list_enabled_type_configs(
    db: AsyncSession,
) -> list[EnergyTypeConfig]:
    """返回所有启用的能源类型配置（供可视化/前端下拉使用）。"""
    result = await db.execute(
        select(EnergyTypeConfig)
        .where(
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
            EnergyTypeConfig.is_enabled == True,    # noqa: E712
        )
        .order_by(EnergyTypeConfig.sort_order.asc())
    )
    return list(result.scalars().all())


async def update_type_config(
    db: AsyncSession, config_id: UUID, data: dict[str, Any]
) -> EnergyTypeConfig | None:
    """更新能源类型配置。"""
    result = await db.execute(
        sa_update(EnergyTypeConfig)
        .where(
            EnergyTypeConfig.id == config_id,
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyTypeConfig)
    )
    return result.scalar_one_or_none()


async def delete_type_config(db: AsyncSession, config_id: UUID) -> bool:
    """软删除能源类型配置（处理重复添加→删除→添加的约束冲突）。"""
    obj = await db.scalar(
        select(EnergyTypeConfig).where(
            EnergyTypeConfig.id == config_id,
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
        )
    )
    if obj is None:
        return False

    # 若已有同 type_code 的已删除记录，先将其编码改名释放唯一约束槽位
    existing_deleted = await db.scalar(
        select(EnergyTypeConfig).where(
            EnergyTypeConfig.type_code == obj.type_code,
            EnergyTypeConfig.is_deleted == True,  # noqa: E712
            EnergyTypeConfig.id != config_id,
        )
    )
    if existing_deleted is not None:
        await db.execute(
            sa_update(EnergyTypeConfig)
            .where(EnergyTypeConfig.id == existing_deleted.id)
            .values(type_code=f"{existing_deleted.type_code}__del_{existing_deleted.id}")
        )

    await db.execute(
        sa_update(EnergyTypeConfig)
        .where(
            EnergyTypeConfig.id == config_id,
            EnergyTypeConfig.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return True


# ── 车间预警配置 ──


async def create_workshop_config(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyWorkshopConfig:
    """创建车间预警配置。"""
    stmt = pg_insert(EnergyWorkshopConfig).values(**data).returning(EnergyWorkshopConfig)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_workshop_config_by_id(
    db: AsyncSession, config_id: UUID
) -> EnergyWorkshopConfig | None:
    result = await db.execute(
        select(EnergyWorkshopConfig).where(
            EnergyWorkshopConfig.id == config_id,
            EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_workshop_config_by_workshop(
    db: AsyncSession, workshop: str
) -> EnergyWorkshopConfig | None:
    result = await db.execute(
        select(EnergyWorkshopConfig).where(
            EnergyWorkshopConfig.workshop == workshop,
            EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_workshop_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyWorkshopConfig], int]:
    query = select(EnergyWorkshopConfig).where(
        EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
    )
    if is_enabled is not None:
        query = query.where(EnergyWorkshopConfig.is_enabled == is_enabled)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyWorkshopConfig.workshop.asc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_enabled_workshop_configs(
    db: AsyncSession,
) -> list[EnergyWorkshopConfig]:
    """返回所有启用 + 自动通知开启的车间配置。"""
    result = await db.execute(
        select(EnergyWorkshopConfig).where(
            EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
            EnergyWorkshopConfig.is_enabled == True,    # noqa: E712
            EnergyWorkshopConfig.auto_notify_enabled == True,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def update_workshop_config(
    db: AsyncSession, config_id: UUID, data: dict[str, Any]
) -> EnergyWorkshopConfig | None:
    """更新车间预警配置。"""
    result = await db.execute(
        sa_update(EnergyWorkshopConfig)
        .where(
            EnergyWorkshopConfig.id == config_id,
            EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyWorkshopConfig)
    )
    return result.scalar_one_or_none()


async def soft_delete_workshop_config(db: AsyncSession, config_id: UUID) -> bool:
    """软删除车间预警配置。"""
    # 先处理重复添加→删除→添加的唯一约束冲突
    obj = await db.scalar(
        select(EnergyWorkshopConfig).where(
            EnergyWorkshopConfig.id == config_id,
            EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
        )
    )
    if obj is None:
        return False

    existing_deleted = await db.scalar(
        select(EnergyWorkshopConfig).where(
            EnergyWorkshopConfig.workshop == obj.workshop,
            EnergyWorkshopConfig.is_deleted == True,  # noqa: E712
            EnergyWorkshopConfig.id != config_id,
        )
    )
    if existing_deleted is not None:
        await db.execute(
            sa_update(EnergyWorkshopConfig)
            .where(EnergyWorkshopConfig.id == existing_deleted.id)
            .values(workshop=f"{existing_deleted.workshop}__del_{existing_deleted.id}")
        )

    await db.execute(
        sa_update(EnergyWorkshopConfig)
        .where(
            EnergyWorkshopConfig.id == config_id,
            EnergyWorkshopConfig.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return True


# ── 车间能耗查询 ──


async def get_workshop_daily_consumption(
    db: AsyncSession,
    workshop: str,
    energy_type: str,
    target_date: datetime,
) -> float | None:
    """查询指定车间 + 能源类型在某一天的总能耗（CST 日期，排除与日汇总重叠的小时数据）。

    返回 None 表示当天没有数据。
    """
    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))
    query = (
        select(func.coalesce(func.sum(EnergyData.value), 0))
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.workshop == workshop,
            EnergyDeviceConfig.energy_type == energy_type,
            cst_date == cast(target_date.date(), Date),
            _total_preferred_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(query)
    total = result.scalar()
    return float(total) if total is not None and total > 0 else None


async def get_workshop_avg_consumption(
    db: AsyncSession,
    workshop: str,
    energy_type: str,
    end_date: datetime,
    max_days: int = 30,
) -> float | None:
    """查询指定车间 + 能源类型在 end_date 前 max_days 天内的日均能耗。

    - 数据不足 max_days 天时，按实际天数计算平均值
    - 数据 >= max_days 时，取最近 max_days 天
    - 无数据返回 None
    """
    start_date = end_date - timedelta(days=max_days)
    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))

    # 按 CST 天聚合每日总能耗
    daily_query = (
        select(
            cst_date.label("day"),
            func.sum(EnergyData.value).label("daily_total"),
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.workshop == workshop,
            EnergyDeviceConfig.energy_type == energy_type,
            cst_date >= cast(start_date.date(), Date),
            cst_date <= cast(end_date.date(), Date),
            _total_preferred_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .group_by(cst_date)
        .subquery()
    )

    query = select(
        func.count(daily_query.c.day).label("day_count"),
        func.avg(daily_query.c.daily_total).label("avg_value"),
    )
    result = await db.execute(query)
    row = result.one_or_none()
    if row is None or row.day_count == 0:
        return None
    return float(row.avg_value)


async def get_distinct_workshop_energy_types(
    db: AsyncSession,
) -> list[dict[str, str]]:
    """获取所有已存在的 (workshop, energy_type) 组合（从启用的设备配置中）。"""
    query = (
        select(
            EnergyDeviceConfig.workshop,
            EnergyDeviceConfig.energy_type,
        )
        .where(
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.is_enabled == True,    # noqa: E712
        )
        .distinct()
        .order_by(EnergyDeviceConfig.workshop, EnergyDeviceConfig.energy_type)
    )
    result = await db.execute(query)
    return [
        {"workshop": row.workshop, "energy_type": row.energy_type}
        for row in result.all()
    ]


async def get_device_options_by_energy_type(
    db: AsyncSession, energy_type: str | None = None
) -> list[dict[str, str]]:
    """获取启用的设备配置列表（device_name, workshop），可选按能源类型过滤。

    供车间预警配置的新建/编辑下拉框使用：展示数据源名称，值存车间名。
    """
    query = (
        select(
            EnergyDeviceConfig.device_name,
            EnergyDeviceConfig.workshop,
        )
        .where(
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.is_enabled == True,    # noqa: E712
        )
    )
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)
    query = query.order_by(EnergyDeviceConfig.device_name)
    result = await db.execute(query)
    return [
        {"device_name": row.device_name, "workshop": row.workshop}
        for row in result.all()
    ]


async def get_distinct_workshops(db: AsyncSession) -> list[str]:
    """获取所有启用的设备配置中的不重复车间名称列表。"""
    result = await db.execute(
        select(EnergyDeviceConfig.workshop)
        .where(
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.is_enabled == True,    # noqa: E712
        )
        .distinct()
        .order_by(EnergyDeviceConfig.workshop)
    )
    return [row.workshop for row in result.all()]


# ── 系统规则管理 ──


async def get_system_alert_rule(
    db: AsyncSession, workshop: str, energy_type: str
) -> EnergyAlertRule | None:
    """查询指定车间 + 能源类型的系统规则。"""
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.workshop == workshop,
            EnergyAlertRule.energy_type == energy_type,
            EnergyAlertRule.is_system == True,  # noqa: E712
            EnergyAlertRule.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def ensure_system_rules(
    db: AsyncSession, workshop: str, energy_types: list[str], unit_map: dict[str, str]
) -> list[EnergyAlertRule]:
    """确保指定车间下的每个能源类型都有系统规则（幂等：已存在则跳过）。"""
    rules: list[EnergyAlertRule] = []
    for et in energy_types:
        existing = await get_system_alert_rule(db, workshop, et)
        if existing is not None:
            rules.append(existing)
            continue
        unit = unit_map.get(et, "")
        rule = await create_alert_rule(db, {
            "rule_name": f"[系统] {workshop} - {et} 预警",
            "rule_description": f"系统自动生成：{workshop} 车间 {et} 能源用量超过近30日均值15%时预警",
            "energy_type": et,
            "monitor_metric": "daily_total",
            "threshold_type": "greater_than",
            "threshold_value": 0,  # 动态阈值，由 evaluate 计算
            "unit": unit,
            "alert_level": "warning",
            "notify_method": ["feishu"],
            "notify_users": [],  # 由 evaluate 从 workshop config 动态获取
            "notify_frequency": "first",
            "workshop": workshop,
            "is_system": True,
        })
        rules.append(rule)
    return rules


async def find_today_alert_record(
    db: AsyncSession, workshop: str, energy_type: str, today: datetime,
) -> EnergyAlertRecord | None:
    """查重：同一 (workshop, energy_type) 当天是否已有预警记录。"""
    cst_start = today.replace(hour=0, minute=0, second=0, microsecond=0)
    cst_end = cst_start + timedelta(days=1)
    result = await db.execute(
        select(EnergyAlertRecord).where(
            EnergyAlertRecord.workshop == workshop,
            EnergyAlertRecord.energy_type == energy_type,
            EnergyAlertRecord.alert_time >= cst_start,
            EnergyAlertRecord.alert_time < cst_end,
            EnergyAlertRecord.is_deleted == False,  # noqa: E712
        ).limit(1)
    )
    return result.scalar_one_or_none()


# ── 人员候选人 ──


async def get_personnel_candidates(db: AsyncSession) -> list[dict[str, Any]]:
    """从平台 identity.users 查询所有用户，作为负责人候选人列表。"""
    from app.platform.identity.models import User

    stmt = select(User).where(
        User.is_deleted == False,  # noqa: E712
    ).order_by(User.name)
    result = await db.execute(stmt)
    users = result.scalars().all()

    return [
        {
            "name": u.name,
            "feishu_open_id": u.feishu_open_id or "",
            "department": u.department,
        }
        for u in users
    ]


async def list_user_alert_rules_for_select(
    db: AsyncSession,
) -> list[EnergyAlertRule]:
    """查询用户手动创建的、已启用的预警规则列表，供车间配置下拉框使用。"""
    result = await db.execute(
        select(EnergyAlertRule).where(
            EnergyAlertRule.is_deleted == False,  # noqa: E712
            EnergyAlertRule.is_system == False,   # noqa: E712
            EnergyAlertRule.is_enabled == True,   # noqa: E712
        ).order_by(EnergyAlertRule.created_at.desc())
    )
    return list(result.scalars().all())


# ── 能源日耗推送配置 ──


async def create_daily_push_config(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyDailyPushConfig:
    stmt = pg_insert(EnergyDailyPushConfig).values(**data).returning(EnergyDailyPushConfig)
    result = await db.execute(stmt)
    return result.scalar_one()


async def get_daily_push_config_by_id(
    db: AsyncSession, config_id: UUID
) -> EnergyDailyPushConfig | None:
    result = await db.execute(
        select(EnergyDailyPushConfig).where(
            EnergyDailyPushConfig.id == config_id,
            EnergyDailyPushConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_daily_push_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyDailyPushConfig], int]:
    query = select(EnergyDailyPushConfig).where(
        EnergyDailyPushConfig.is_deleted == False  # noqa: E712
    )
    if is_enabled is not None:
        query = query.where(EnergyDailyPushConfig.is_enabled == is_enabled)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    query = query.order_by(EnergyDailyPushConfig.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_enabled_daily_push_configs(
    db: AsyncSession,
) -> list[EnergyDailyPushConfig]:
    """返回所有启用且设置了定时推送时间的推送配置。"""
    result = await db.execute(
        select(EnergyDailyPushConfig).where(
            EnergyDailyPushConfig.is_deleted == False,  # noqa: E712
            EnergyDailyPushConfig.is_enabled == True,    # noqa: E712
            EnergyDailyPushConfig.notify_time.isnot(None),
        )
    )
    return list(result.scalars().all())


async def update_daily_push_config(
    db: AsyncSession, config_id: UUID, data: dict[str, Any]
) -> EnergyDailyPushConfig | None:
    result = await db.execute(
        sa_update(EnergyDailyPushConfig)
        .where(
            EnergyDailyPushConfig.id == config_id,
            EnergyDailyPushConfig.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyDailyPushConfig)
    )
    return result.scalar_one_or_none()


async def delete_daily_push_config(db: AsyncSession, config_id: UUID) -> bool:
    result = await db.execute(
        sa_update(EnergyDailyPushConfig)
        .where(
            EnergyDailyPushConfig.id == config_id,
            EnergyDailyPushConfig.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return result.rowcount > 0


# ── 能源日耗推送专用查询 ──


async def get_daily_total_by_energy_type(
    db: AsyncSession,
    energy_type: str,
    target_date: datetime,
) -> float | None:
    """按能源类型汇总指定日期的总能耗（跨所有车间），总耗优先。"""
    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))

    query = (
        select(func.coalesce(func.sum(EnergyData.value), 0))
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.energy_type == energy_type,
            cst_date == cast(target_date.date(), Date),
            _total_preferred_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    result = await db.execute(query)
    total = result.scalar()
    return float(total) if total is not None and total > 0 else None


async def get_daily_top_workshops(
    db: AsyncSession,
    energy_type: str,
    target_date: datetime,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """获取指定能源类型在某日用量最高的 TOP N 部门。

    返回列表，每项包含 workshop, total_value, percentage。
    只用 stat_role='normal' 设备，总耗设备不参与排名。
    """
    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))

    # 总量：只用普通设备
    total_result = await db.execute(
        select(func.coalesce(func.sum(EnergyData.value), 0))
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.energy_type == energy_type,
            cst_date == cast(target_date.date(), Date),
            _normal_only_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
    )
    grand_total = float(total_result.scalar() or 0)

    if grand_total == 0:
        return []

    # 按部门汇总
    query = (
        select(
            EnergyDeviceConfig.workshop,
            func.sum(EnergyData.value).label("total_value"),
        )
        .join(
            EnergyDeviceConfig,
            EnergyData.device_config_id == EnergyDeviceConfig.id,
        )
        .where(
            EnergyData.is_deleted == False,  # noqa: E712
            EnergyDeviceConfig.energy_type == energy_type,
            cst_date == cast(target_date.date(), Date),
            _normal_only_filter(EnergyDeviceConfig),
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .group_by(EnergyDeviceConfig.workshop)
        .order_by(func.sum(EnergyData.value).desc())
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "workshop": row.workshop,
            "total_value": float(row.total_value or 0),
            "percentage": round(float(row.total_value or 0) / grand_total * 100, 1),
        }
        for row in rows
    ]


async def get_device_daily_value(
    db: AsyncSession,
    device_id: UUID,
    target_date: datetime,
) -> float | None:
    """查询指定设备在目标日期的采集值（日汇总优先，否则小时数据求和）。"""
    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))

    query = (
        select(func.coalesce(func.sum(EnergyData.value), 0))
        .where(
            EnergyData.device_config_id == device_id,
            EnergyData.is_deleted == False,  # noqa: E712
            cst_date == cast(target_date.date(), Date),
        )
    )
    result = await db.execute(query)
    total = result.scalar()
    return float(total) if total is not None and total > 0 else None


# ── 氮气月度推送配置 CRUD ──


async def create_nitrogen_push_config(
    db: AsyncSession, data: dict[str, Any]
) -> EnergyNitrogenPushConfig:
    stmt = (
        pg_insert(EnergyNitrogenPushConfig)
        .values(**data)
        .returning(EnergyNitrogenPushConfig)
    )
    result = await db.execute(stmt)
    obj = result.scalar_one()
    await db.flush()
    return obj


async def get_nitrogen_push_config_by_id(
    db: AsyncSession, config_id: UUID
) -> EnergyNitrogenPushConfig | None:
    result = await db.execute(
        select(EnergyNitrogenPushConfig).where(
            EnergyNitrogenPushConfig.id == config_id,
            EnergyNitrogenPushConfig.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_nitrogen_push_configs(
    db: AsyncSession,
    *,
    is_enabled: bool | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EnergyNitrogenPushConfig], int]:
    conditions: list[Any] = [EnergyNitrogenPushConfig.is_deleted == False]  # noqa: E712
    if is_enabled is not None:
        conditions.append(EnergyNitrogenPushConfig.is_enabled == is_enabled)  # noqa: E712

    base_query = select(EnergyNitrogenPushConfig).where(*conditions)
    total_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = total_result.scalar() or 0

    items_result = await db.execute(
        base_query
        .order_by(EnergyNitrogenPushConfig.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(items_result.scalars().all()), total


async def get_enabled_nitrogen_push_configs(
    db: AsyncSession,
) -> list[EnergyNitrogenPushConfig]:
    """返回所有启用且设置了定时推送时间的氮气推送配置。"""
    result = await db.execute(
        select(EnergyNitrogenPushConfig).where(
            EnergyNitrogenPushConfig.is_deleted == False,  # noqa: E712
            EnergyNitrogenPushConfig.is_enabled == True,    # noqa: E712
            EnergyNitrogenPushConfig.notify_time.isnot(None),
        )
    )
    return list(result.scalars().all())


async def update_nitrogen_push_config(
    db: AsyncSession, config_id: UUID, data: dict[str, Any]
) -> EnergyNitrogenPushConfig | None:
    result = await db.execute(
        sa_update(EnergyNitrogenPushConfig)
        .where(
            EnergyNitrogenPushConfig.id == config_id,
            EnergyNitrogenPushConfig.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyNitrogenPushConfig)
    )
    return result.scalar_one_or_none()


async def delete_nitrogen_push_config(db: AsyncSession, config_id: UUID) -> bool:
    result = await db.execute(
        sa_update(EnergyNitrogenPushConfig)
        .where(
            EnergyNitrogenPushConfig.id == config_id,
            EnergyNitrogenPushConfig.is_deleted == False,  # noqa: E712
        )
        .values(is_deleted=True)
    )
    return result.rowcount > 0


# ── 氮气月度查询 ──


async def delete_hourly_data_for_device_on_date(
    db: AsyncSession, device_config_id: UUID, target_date: datetime
) -> int:
    """物理删除指定设备在指定 CST 日期的所有能耗数据。

    用于氮气月度推送前清理逐小时数据，避免日汇总与小时数据被 SUM 重复累加。
    使用物理删除而非软删除，否则 upsert 会因 (device_config_id, timestamp)
    唯一约束冲突而覆盖失败。
    """
    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))
    result = await db.execute(
        sa_delete(EnergyData).where(
            EnergyData.device_config_id == device_config_id,
            cst_date == cast(target_date.date(), Date),
        )
    )
    return result.rowcount


async def get_monthly_nitrogen_total(
    db: AsyncSession,
    device_ids: list[UUID],
    year: int,
    month: int,
    up_to_day: int,
) -> float | None:
    """从月1日到 up_to_day 汇总所有指定氮气设备的累计用量。"""
    if not device_ids:
        return None

    cst_date = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp))
    query = (
        select(func.coalesce(func.sum(EnergyData.value), 0))
        .where(
            EnergyData.device_config_id.in_(device_ids),
            EnergyData.is_deleted == False,  # noqa: E712
            func.extract('year', cst_date) == year,
            func.extract('month', cst_date) == month,
            func.extract('day', cst_date) <= up_to_day,
        )
    )
    result = await db.execute(query)
    total = result.scalar()
    return float(total) if total is not None and total > 0 else None


async def get_price_category_distribution(
    db: AsyncSession,
    start_time: datetime,
    end_time: datetime,
    energy_type: str | None = None,
    workshop: str | None = None,
) -> list[dict[str, Any]]:
    """按峰谷电价分类聚合能耗数据。

    从 energy.price_periods 表读取用户配置的规则，按优先级（尖>峰>平>谷）分类。
    """
    from sqlalchemy import text

    # 1. 加载所有规则，构建 (hour, month) → category 映射
    rules_result = await db.execute(
        select(PricePeriod).where(PricePeriod.is_deleted == False)  # noqa: E712
    )
    rules = rules_result.scalars().all()

    # 优先级：尖>峰>平>谷（数字越小优先级越高）
    priority = {"尖": 1, "峰": 2, "平": 3, "谷": 4}

    # 构建映射: {(hour, month): (priority, category)}
    lookup: dict[tuple[int, int], tuple[int, str]] = {}
    for r in rules:
        for month in r.months:
            for hour in range(r.start_hour, r.end_hour):
                key = (hour, month)
                prio = priority.get(r.category, 99)
                if key not in lookup or prio < lookup[key][0]:
                    lookup[key] = (prio, r.category)

    # 2. 查询原始数据
    where_clauses = [
        "d.is_deleted = false",
        "c.is_deleted = false",
        "d.timestamp >= :start_time",
        "d.timestamp <= :end_time",
    ]
    params: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
    }

    if energy_type:
        where_clauses.append("c.energy_type = :energy_type")
        params["energy_type"] = energy_type

    if workshop:
        where_clauses.append("c.workshop = :workshop")
        params["workshop"] = workshop
        # 按部门查看 → 只用普通设备（子表），排除总耗设备
        where_clauses.append("c.stat_role = 'normal'")
    else:
        # 默认总览 → 总耗设备优先，无总耗时用普通设备
        where_clauses.append("c.stat_role != 'excluded'")
        where_clauses.append(
            "(c.stat_role = 'total' OR (c.stat_role = 'normal' AND NOT EXISTS ("
            "SELECT 1 FROM energy.energy_device_configs t "
            "WHERE t.workshop = c.workshop AND t.energy_type = c.energy_type "
            "AND t.stat_role = 'total' AND t.is_enabled = true AND t.is_deleted = false"
            ")))"
        )

    where_sql = " AND ".join(where_clauses)
    raw_sql = (
        f"SELECT d.value, d.unit, "
        f"EXTRACT(HOUR FROM d.timestamp AT TIME ZONE 'Asia/Shanghai')::int AS hour, "
        f"EXTRACT(MONTH FROM d.timestamp AT TIME ZONE 'Asia/Shanghai')::int AS month "
        f"FROM energy.energy_data d "
        f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
        f"WHERE {where_sql}"
    )

    result = await db.execute(text(raw_sql), params)
    raw_rows = result.all()

    # 3. 分类聚合
    from collections import defaultdict
    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"total_value": 0.0, "unit": ""})
    for row in raw_rows:
        key = (int(row.hour), int(row.month))
        cat = lookup.get(key, (99, "平"))[1]
        agg[cat]["total_value"] += float(row.value or 0)
        agg[cat]["unit"] = row.unit or agg[cat]["unit"]

    # 4. 按优先级排序
    order = {"尖": 1, "峰": 2, "平": 3, "谷": 4}
    categories = sorted(
        [
            {
                "category": cat,
                "total_value": round(data["total_value"], 4),
                "unit": data["unit"],
                "percentage": 0.0,
            }
            for cat, data in agg.items()
        ],
        key=lambda c: order.get(c["category"], 99),
    )

    grand_total = sum(c["total_value"] for c in categories)
    for c in categories:
        c["percentage"] = round(c["total_value"] / grand_total * 100, 1) if grand_total > 0 else 0.0

    return categories


# ── 峰谷时段规则 CRUD ──


async def list_price_periods(db: AsyncSession) -> list[dict[str, Any]]:
    """列出所有未删除的峰谷时段规则。"""
    result = await db.execute(
        select(PricePeriod).where(PricePeriod.is_deleted == False).order_by(  # noqa: E712
            PricePeriod.category, PricePeriod.start_hour
        )
    )
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "category": r.category,
            "start_hour": r.start_hour,
            "end_hour": r.end_hour,
            "months": r.months,
        }
        for r in rows
    ]


async def create_price_period(
    db: AsyncSession, category: str, start_hour: int, end_hour: int, months: list[int]
) -> dict[str, Any]:
    """新增一条峰谷时段规则。"""
    period = PricePeriod(
        category=category,
        start_hour=start_hour,
        end_hour=end_hour,
        months=months,
    )
    db.add(period)
    await db.flush()
    return {
        "id": str(period.id),
        "category": period.category,
        "start_hour": period.start_hour,
        "end_hour": period.end_hour,
        "months": period.months,
    }


async def delete_price_period(db: AsyncSession, period_id: UUID) -> bool:
    """软删除一条峰谷时段规则。"""
    result = await db.execute(
        select(PricePeriod).where(
            PricePeriod.id == period_id,
            PricePeriod.is_deleted == False,  # noqa: E712
        )
    )
    period = result.scalars().first()
    if period is None:
        return False
    period.is_deleted = True
    await db.flush()
    return True


async def reset_price_periods(db: AsyncSession) -> list[dict[str, Any]]:
    """重置为默认规则：软删除全部现有规则，插入默认值。"""
    # 软删除全部
    result = await db.execute(
        select(PricePeriod).where(PricePeriod.is_deleted == False)  # noqa: E712
    )
    for r in result.scalars().all():
        r.is_deleted = True
    await db.flush()

    # 插入默认规则
    defaults = [
        ("谷", 0, 8, list(range(1, 13))),
        ("平", 8, 10, list(range(1, 13))),
        ("平", 12, 15, list(range(1, 13))),
        ("平", 20, 21, list(range(1, 13))),
        ("平", 22, 24, list(range(1, 13))),
        ("峰", 10, 11, list(range(1, 13))),
        ("峰", 11, 12, [1, 2, 3, 4, 5, 6, 10, 11, 12]),
        ("峰", 15, 17, list(range(1, 13))),
        ("峰", 17, 18, [1, 2, 3, 4, 5, 6, 10, 11, 12]),
        ("峰", 18, 20, list(range(1, 13))),
        ("峰", 21, 22, list(range(1, 13))),
        ("尖", 11, 12, [7, 8, 9]),
        ("尖", 17, 18, [7, 8, 9]),
    ]
    periods = []
    for cat, sh, eh, months in defaults:
        p = PricePeriod(category=cat, start_hour=sh, end_hour=eh, months=months)
        db.add(p)
        periods.append(p)
    await db.flush()
    return [
        {"id": str(p.id), "category": p.category, "start_hour": p.start_hour,
         "end_hour": p.end_hour, "months": p.months}
        for p in periods
    ]
