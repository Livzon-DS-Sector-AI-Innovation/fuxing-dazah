"""Safety schemas — 应用配置中心（app_config）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AppConfigValueUpdate(BaseModel):
    """PUT /app-config/{key} 请求体。

    - value：字符串形态写入（bool 接受 true/false/1/0 等，store 归一化；
      str 允许空串 = 清除覆盖，回落 env/registry 默认）；
    - enabled：可选，false = 整行停用（回落 env/默认，行保留）；
    - note：可选备注。
    """

    value: str = Field(max_length=1024)
    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=255)


class AppConfigAuditOut(BaseModel):
    """审计行（before/after 已在 store 内脱敏）。"""

    key: str
    action: str
    before_json: dict[str, Any] | None
    after_json: dict[str, Any] | None
    operator_name: str | None
    created_at: str


class AppConfigListOut(BaseModel):
    """GET /app-config 响应（items = store.effective_items()）。"""

    items: list[dict[str, Any]]
    categories: dict[str, str]
