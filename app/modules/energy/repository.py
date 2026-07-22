"""Energy database queries and persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, not_, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.energy.models import (
    EnergyAlertRecord,
    EnergyAlertRule,
    EnergyCollectLog,
    EnergyData,
    EnergyDeviceConfig,
    EnergyTypeConfig,
    EnergyWorkshopConfig,
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
    """更新设备配置（使用原始 SQL 避免 BaseModel FK 解析异常）。"""
    result = await db.execute(
        sa_update(EnergyDeviceConfig)
        .where(
            EnergyDeviceConfig.id == config_id,
            EnergyDeviceConfig.is_deleted == False,  # noqa: E712
        )
        .values(**data)
        .returning(EnergyDeviceConfig)
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


async def daily_record_exists(
    db: AsyncSession, device_config_id: UUID, day_start: datetime
) -> bool:
    """检查某设备某天是否已有日汇总记录（timestamp = 当天 00:00:00 且 daily_sum=true）。"""
    from sqlalchemy import String

    result = await db.execute(
        select(func.count()).where(
            EnergyData.device_config_id == device_config_id,
            EnergyData.timestamp == day_start,
            EnergyData.platform_raw_data["daily_sum"].cast(String) == "true",
            EnergyData.is_deleted == False,  # noqa: E712
        )
    )
    return (result.scalar() or 0) > 0


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
    """查询能耗数据历史明细，JOIN 设备配置表返回完整信息。"""
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
        where_clauses.append("(c.device_name ILIKE :keyword OR c.platform_device_code ILIKE :keyword)")
        params["keyword"] = f"%{keyword}%"
    if granularity:
        if granularity == "daily":
            where_clauses.append("d.platform_raw_data->>'daily_sum' = 'true'")
        elif granularity == "hourly":
            where_clauses.append("(d.platform_raw_data->>'daily_sum' IS NULL OR d.platform_raw_data->>'daily_sum' != 'true')")

    where_sql = " AND ".join(where_clauses)

    count_sql = (
        f"SELECT COUNT(*) FROM energy.energy_data d "
        f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
        f"WHERE {where_sql}"
    )
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    query_sql = (
        f"SELECT d.id, d.device_config_id, c.device_name, c.platform_device_code, "
        f"c.energy_type, c.workshop, c.production_line, "
        f"d.timestamp, d.value, COALESCE(tc.unit, d.unit) AS unit, d.collected_at, "
        f"COALESCE(d.platform_raw_data->>'daily_sum', 'false') AS granularity "
        f"FROM energy.energy_data d "
        f"JOIN energy.energy_device_configs c ON d.device_config_id = c.id "
        f"LEFT JOIN energy.energy_type_configs tc ON c.energy_type = tc.type_code AND tc.is_deleted = false "
        f"WHERE {where_sql} "
        f"ORDER BY d.timestamp DESC "
        f"LIMIT :limit OFFSET :offset"
    )
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


def _exclude_hourly_overlap(outer: type[EnergyData]) -> Any:
    """生成 WHERE 子句：排除已有日汇总记录的同一设备同一天的小时数据。

    避免 SUM 时把日汇总和小时数据重复累加。
    使用 CST 时区（Asia/Shanghai）比较日期，避免 UTC 日期跨天导致的去重失效。
    """
    inner = EnergyData.__table__.alias("d2")
    # 将 timestamptz 转为 CST 日期再比较，避免 UTC 跨天问题
    cst_date_inner = func.date(func.timezone('Asia/Shanghai', inner.c.timestamp))
    cst_date_outer = func.date(func.timezone('Asia/Shanghai', outer.timestamp))
    return or_(
        outer.platform_raw_data["daily_sum"].astext == "true",
        not_(
            exists().where(
                inner.c.device_config_id == outer.device_config_id,
                cst_date_inner == cst_date_outer,
                inner.c.platform_raw_data["daily_sum"].astext == "true",
                inner.c.is_deleted == False,  # noqa: E712
            )
        ),
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
        group_col = EnergyDeviceConfig.production_line
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
            _exclude_hourly_overlap(EnergyData),
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
    """按能源类型汇总能耗"""
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
            EnergyDeviceConfig.daily_collect_time.isnot(None),
            _exclude_hourly_overlap(EnergyData),
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

    granularity: "hourly" 按小时分组, "daily" 按天分组（日汇总记录优先，小时数据自动聚合）
    """
    if granularity == "daily":
        time_col = func.date(func.timezone('Asia/Shanghai', EnergyData.timestamp)).label("time_point")
        group_cols = [time_col, EnergyDeviceConfig.energy_type]
        order_col = time_col
    else:
        time_col = EnergyData.timestamp
        group_cols = [EnergyData.timestamp, EnergyDeviceConfig.energy_type]
        order_col = EnergyData.timestamp

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
            _exclude_hourly_overlap(EnergyData),
        )
        .group_by(*group_cols)
        .order_by(order_col.asc())
    )
    if energy_type:
        query = query.where(EnergyDeviceConfig.energy_type == energy_type)

    result = await db.execute(query)
    return [
        {
            "time": (
                row.time_point.isoformat()
                if granularity == "daily"
                else row.timestamp.isoformat()
            ),
            "value": float(row.total_value or 0),
            "type": row.energy_type,
        }
        for row in result.all()
    ]


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
    默认 ±120 秒窗口，覆盖日汇总采集的多轮 API 调用耗时。
    """
    log = await db.scalar(
        select(EnergyCollectLog).where(
            EnergyCollectLog.id == log_id,
            EnergyCollectLog.is_deleted == False,  # noqa: E712
        )
    )
    if log is None:
        return None, []

    window_start = log.collect_time - timedelta(seconds=time_window_seconds)
    window_end = log.collect_time + timedelta(seconds=time_window_seconds)

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


async def list_equipments_for_select(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """查询设备台账中在用的设备列表（只读，跨 schema 查询）。"""
    from sqlalchemy import text

    where_clauses = ["e.is_deleted = false"]
    params: dict[str, Any] = {}

    if keyword:
        where_clauses.append("(e.name ILIKE :keyword OR e.equipment_no ILIKE :keyword)")
        params["keyword"] = f"%{keyword}%"
    if status:
        where_clauses.append("e.status = :status")
        params["status"] = status

    where_sql = " AND ".join(where_clauses)

    count_sql = f"SELECT COUNT(*) FROM equipment.equipments e WHERE {where_sql}"
    count_result = await db.execute(text(count_sql), params)
    total = count_result.scalar() or 0

    query_sql = (
        f"SELECT e.id, e.equipment_no, e.name, e.status, e.model, e.specification, e.location_id "
        f"FROM equipment.equipments e "
        f"WHERE {where_sql} "
        f"ORDER BY e.name "
        f"LIMIT :limit OFFSET :offset"
    )
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size

    result = await db.execute(text(query_sql), params)
    rows = result.all()
    items = [
        {
            "id": str(row.id),
            "equipment_no": row.equipment_no,
            "name": row.name,
            "status": row.status,
            "model": row.model,
            "specification": row.specification,
            "location_id": str(row.location_id) if row.location_id else None,
        }
        for row in rows
    ]
    return items, total


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
            cst_date == func.date(target_date),
            _exclude_hourly_overlap(EnergyData),
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
            cst_date >= func.date(start_date),
            cst_date <= func.date(end_date),
            _exclude_hourly_overlap(EnergyData),
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
