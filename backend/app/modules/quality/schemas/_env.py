"""环境监测 Schema。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MONITOR_TYPES = Literal["settle", "float", "particle", "temp_humidity", "pressure"]


class EnvPointCreate(BaseModel):
    """监测点新增。"""

    room: str = Field(max_length=128, description="房间/区域")
    point_no: str = Field(max_length=64, description="点位编号")
    monitor_type: MONITOR_TYPES = Field(description="监测类型")
    frequency: Literal["per_batch", "weekly", "monthly"] | None = Field(default=None, description="监测频次")
    alert_limit: float | None = Field(default=None, ge=0, description="警戒限")
    action_limit: float | None = Field(default=None, ge=0, description="行动限")
    status: Literal["active", "inactive"] = Field(default="active", description="启用/停用")
    remark: str | None = Field(default=None, max_length=200)


class EnvPointUpdate(BaseModel):
    """监测点更新（全部可选）。"""

    room: str | None = Field(default=None, max_length=128)
    point_no: str | None = Field(default=None, max_length=64)
    monitor_type: MONITOR_TYPES | None = None
    frequency: Literal["per_batch", "weekly", "monthly"] | None = None
    alert_limit: float | None = Field(default=None, ge=0)
    action_limit: float | None = Field(default=None, ge=0)
    status: Literal["active", "inactive"] | None = None
    remark: str | None = Field(default=None, max_length=200)


class EnvPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    room: str
    point_no: str
    monitor_type: str
    frequency: str | None
    alert_limit: float | None
    action_limit: float | None
    status: str
    remark: str | None
    created_at: datetime


class EnvRecordCreate(BaseModel):
    """监测记录填报：按点位的警戒限/行动限自动判定三态。"""

    point_id: uuid.UUID = Field(description="监测点")
    record_date: str = Field(max_length=32, description="监测日期 YYYY-MM-DD")
    result_value: float | None = Field(default=None, ge=0, description="检测结果值")
    remark: str | None = Field(default=None, max_length=200)


class EnvRecordOut(BaseModel):
    id: uuid.UUID
    point_id: uuid.UUID
    room: str
    point_no: str
    monitor_type: str
    record_date: str
    result_value: float | None
    alert_limit: float | None
    action_limit: float | None
    judge: str | None
    handle_status: str
    handled_at: str | None
    handled_by: uuid.UUID | None
    handled_by_name: str | None
    handled_remark: str | None
    recorded_by: uuid.UUID | None
    recorded_by_name: str | None
    remark: str | None
    created_at: datetime


class EnvRecordHandle(BaseModel):
    """超行动限记录闭环：标记已处理并留处理说明。"""

    handled_remark: str | None = Field(default=None, max_length=200, description="处理说明")


class BatchReleaseCreate(BaseModel):
    """发起批放行：以已完成检验任务为基准生成放行记录与汇总快照。"""

    task_id: uuid.UUID = Field(description="已完成检验任务")
    remark: str | None = Field(default=None, max_length=200)


class BatchReleaseRelease(BaseModel):
    """专员放行：记录放行人/日期与备注。"""

    release_remark: str | None = Field(default=None, max_length=200, description="放行备注")


class BatchReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    batch_no: str
    product_name: str
    task_id: uuid.UUID | None
    snapshot: dict[str, object] | None
    status: str
    released_by: uuid.UUID | None
    released_by_name: str | None = None
    released_at: str | None
    release_remark: str | None
    remark: str | None
    created_at: datetime


class ShiftTeamIn(BaseModel):
    """班组保存（成员为 identity.users.id 列表）。"""

    name: str = Field(max_length=64)
    group_key: str = Field(default="仪器组", max_length=32, description="归属组别")
    member_ids: list[uuid.UUID] = Field(default_factory=list, description="班组成员")
    seq: int = Field(default=0, ge=0)
    remark: str | None = Field(default=None, max_length=200)


class ShiftTeamOut(BaseModel):
    id: uuid.UUID
    name: str
    member_ids: list[str] | None
    member_names: list[str] = Field(default_factory=list)
    seq: int
    remark: str | None


class ShiftConfigIn(BaseModel):
    """轮换配置：基准日期 + 周期天数 + 同时当班班组数（group 为空=全局）。"""

    group: str | None = Field(default=None, max_length=32, description="组别（空=全局）")
    start_date: str = Field(max_length=32, description="基准日期 YYYY-MM-DD")
    period_days: int = Field(default=3, ge=1, le=30)
    duty_teams: int = Field(default=2, ge=1, le=10)
