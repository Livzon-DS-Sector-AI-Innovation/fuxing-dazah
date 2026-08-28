"""Meter 全局设置 schema。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MeterSettingsResponse(BaseModel):
    """全局设置响应。"""
    notify_time: str = Field(..., description="每日提醒时间 HH:MM")





class MeterSettingsUpdate(BaseModel):
    """更新全局设置。"""
    notify_time: str = Field(..., pattern=r"^\d{2}:\d{2}$", description="提醒时间 HH:MM")
