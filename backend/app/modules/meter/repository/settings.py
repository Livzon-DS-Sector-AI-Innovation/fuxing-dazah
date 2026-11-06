"""Meter 全局设置数据访问。"""

from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter.models import MeterSettings


async def get_or_create_meter_settings(db: AsyncSession) -> MeterSettings:
    """获取全局 meter 设置；不存在时创建默认值（17:45）。

    表无唯一约束，历史脏数据可能出现多行——固定取最早创建的一行，
    保证并发/多行场景下读写稳定指向同一行。
    """
    result = await db.execute(
        # id 兜底：同一事务插入的多行 created_at 相同，没有次级排序时
        # 每次查询可能选中不同行，提醒时间会与实际生效行不一致
        select(MeterSettings)
        .order_by(MeterSettings.created_at.asc(), MeterSettings.id.asc())
        .limit(1)
    )
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = MeterSettings()
        db.add(settings)
        await db.flush()
    return settings


async def update_meter_settings(
    db: AsyncSession, notify_time: time,
) -> MeterSettings:
    """更新提醒时间并重新拉取配置。"""
    # 先确保只有一行，再更新
    settings = await get_or_create_meter_settings(db)
    stmt = (
        sa_update(MeterSettings)
        .where(MeterSettings.id == settings.id)
        .values(notify_time=notify_time)
    )
    await db.execute(stmt)
    await db.flush()
    result = await db.execute(select(MeterSettings).where(MeterSettings.id == settings.id))
    return result.scalar_one()
