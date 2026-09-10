"""定时任务配置 Schema — PUT /scheduler-config/tasks/{job_name} 请求体."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SchedulerTaskUpdate(BaseModel):
    """定时任务覆写配置更新体。

    仅提供需要覆写/修改的字段；enabled 必填。
    未提供的可空字段保持现有数据库/代码默认值不变。
    """

    enabled: bool = Field(..., description="是否启用（False 仅停用，不清除历史覆写）")
    hour: int | None = Field(None, ge=0, le=23, description="执行小时 0-23")
    minute: int | None = Field(None, ge=0, le=59, description="执行分钟 0-59")
    dow: int | None = Field(None, ge=0, le=6, description="星期 0-6（周一-周日），NULL=每天")
    retry_until_hour: int | None = Field(None, ge=0, le=23, description="补发窗口截止小时")
    retry_until_minute: int | None = Field(None, ge=0, le=59, description="补发窗口截止分钟")
    target_chat_id: str | None = Field(None, min_length=1, max_length=128, description="飞书群聊 chat_id")
    target_chat_name: str | None = Field(None, max_length=128, description="群名（冗余，前端展示）")


class SchedulerPreviewRequest(BaseModel):
    """报告预览请求体。"""

    date: str | None = Field(None, description="目标日期 ISO（YYYY-MM-DD），默认今天")
