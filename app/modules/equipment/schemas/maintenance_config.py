"""Maintenance config schemas."""

from pydantic import BaseModel, Field


class ClaimTimeoutConfig(BaseModel):
    """抢单超时配置（按优先级）"""

    emergency: int = Field(default=15, ge=1, le=1440, description="紧急工单超时（分钟）")
    high: int = Field(default=30, ge=1, le=1440, description="高优先级超时（分钟）")
    medium: int = Field(default=60, ge=1, le=1440, description="中优先级超时（分钟）")
    low: int = Field(default=120, ge=1, le=1440, description="低优先级超时（分钟）")


class ClaimTimeoutUpdateRequest(BaseModel):
    """更新超时配置请求"""

    emergency: int | None = Field(default=None, ge=1, le=1440)
    high: int | None = Field(default=None, ge=1, le=1440)
    medium: int | None = Field(default=None, ge=1, le=1440)
    low: int | None = Field(default=None, ge=1, le=1440)


class AdvanceDaysConfig(BaseModel):
    """维护计划提前创建工单天数配置"""

    advance_days: int = Field(default=0, ge=0, le=364, description="提前天数，0=当天触发")


class AdvanceDaysUpdateRequest(BaseModel):
    """更新提前天数配置请求"""

    advance_days: int = Field(
        ..., ge=0, le=364, description="提前天数，0-364，0=当天触发"
    )
