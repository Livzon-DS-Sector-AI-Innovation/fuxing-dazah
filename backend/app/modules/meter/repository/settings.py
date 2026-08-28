"""Meter 全局设置数据访问。"""

from __future__ import annotations

from datetime import time

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter.models import MeterSettings


async def get_or_create_meter_settings(db: AsyncSession) -> MeterSettings:
    """获取全局 meter 设置；不存在时创建默认值（17:45）。"""
    result = await db.execute(select(MeterSettings).limit(1))
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
