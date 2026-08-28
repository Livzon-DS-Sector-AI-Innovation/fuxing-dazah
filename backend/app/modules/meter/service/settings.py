"""Meter 全局设置业务工作流。"""

from __future__ import annotations

from datetime import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.meter import repository as repo


async def get_meter_settings(db: AsyncSession) -> dict[str, str]:
    """获取全局 meter 设置。"""
    cfg = await repo.get_or_create_meter_settings(db)
    return {"notify_time": cfg.notify_time.strftime("%H:%M")}


async def update_meter_settings(
    db: AsyncSession, notify_time_str: str,
) -> dict[str, str]:
    """校验并更新提醒时间。"""
    try:
        h, m = map(int, notify_time_str.split(":"))
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError("时间值超出范围")
    except (ValueError, TypeError):
        raise ValueError(f"无效的时间格式: {notify_time_str}，期望 HH:MM") from None

    cfg = await repo.update_meter_settings(db, time(h, m))
    return {"notify_time": cfg.notify_time.strftime("%H:%M")}
