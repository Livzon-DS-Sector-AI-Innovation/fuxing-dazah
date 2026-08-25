"""工具箱 API 契约（无 ORM）。registry 的 dataclass 经 from_attributes 直接校验输出。"""

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
    options: list[str] | None = None
    from_step: str | None = None
    from_key: str | None = None


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


class ToolOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    image: str | None = None
    steps: list[ToolStepOut]
    config_schema: list[ConfigFieldOut] = []


class StepRunResponse(BaseModel):
    execution_id: str
    data: dict[str, Any]
    file_ids: dict[str, list[str]]


class ExecutionOut(BaseModel):
    execution_id: str
    tool_id: str
    outputs: dict[str, Any]
    files: dict[str, Any]
