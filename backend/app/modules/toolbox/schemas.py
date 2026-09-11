"""工具箱 API 契约。registry 的 dataclass 经 from_attributes 直接校验输出。"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolInputOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    type: str
    accept: str | None = None
    required: bool = False
    multiple: bool = False
    default: Any = None
    placeholder: str | None = None
    options: list[str] | list[dict[str, str]] | None = None
    from_step: str | None = None
    from_key: str | None = None
    show_when: tuple[str, str] | None = None
    help: str | None = None


class ToolStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    inputs: list[ToolInputOut]


class ConfigFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    type: str
    section: str = ""
    required: bool = False
    help: str | None = None


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    image: str | None = None
    steps: list[ToolStepOut]
    config_schema: list[ConfigFieldOut] = []
    can_use: bool = False
    can_config: bool = False
    background: bool = False


class StepRunResponse(BaseModel):
    execution_id: str
    data: dict[str, Any]
    file_ids: dict[str, list[str]]
    warning: str | None = None  # 执行成功但记录落库失败时的提示；正常为 None
    # done=同步执行完毕（data 为工具结果）；running=后台执行已启动（data 为空，
    # 最终结果与进度经 GET /executions/{id} 轮询获取）
    status: str = "done"


class ExecutionOut(BaseModel):
    execution_id: str
    tool_id: str
    outputs: dict[str, Any]
    files: dict[str, Any]
    # 各步骤执行进度：step_id -> {percent, message, status(running/done/failed), error, updated_at}
    progress: dict[str, Any] = {}


class ExecutionSummaryOut(BaseModel):
    """执行会话列表摘要（当前用户、跨工具），驱动执行页「进行中/上次执行」提示条。"""

    execution_id: str
    tool_id: str
    status: str  # running / done / failed
    percent: int
    message: str
    error: str
    created_at: float


# ── 使用权限管理 ──


class GrantUserOut(BaseModel):
    """工具授权名单中的用户（含展示信息）。"""

    user_id: uuid.UUID
    name: str
    employee_no: str | None = None
    department: str | None = None


class ToolGrantsOut(BaseModel):
    """某工具的使用/配置授权名单。"""

    tool_id: str
    tool_name: str
    use_users: list[GrantUserOut] = []
    config_users: list[GrantUserOut] = []


class UpdateToolGrantsIn(BaseModel):
    """整体替换某工具的授权名单。

    空名单含义：use_user_ids 为空 → 该工具不再限制（全员可用）；
    config_user_ids 为空 → 仅超级管理员可修改配置。
    """

    use_user_ids: list[uuid.UUID] = []
    config_user_ids: list[uuid.UUID] = []
