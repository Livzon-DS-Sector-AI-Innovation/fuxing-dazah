"""四新域页面骨架响应模型（3.0 四期 1-B）。

字段口径（stats 键/ledger 行英文字段）的唯一事实源是
docs/DESIGN-安全模块3.0四期-四新域表结构与页面口径-20261014.md；
骨架阶段 stats/ledger 行用受信封约束的宽松类型（dict），接入后字段
如与蓝本有出入只需改 service 层映射，本模型不动。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DomainPageStatus = Literal["not_connected", "live", "degraded"]


class LedgerMetaOut(BaseModel):
    total: int
    page: int
    page_size: int


class LedgerOut(BaseModel):
    data: list[dict[str, Any]]
    meta: LedgerMetaOut


class DomainPageOut(BaseModel):
    """三态信封（蓝本 §6）：not_connected=表未建；live=直读出数；degraded=读取降级。"""

    status: DomainPageStatus
    stats: dict[str, Any] | None = Field(
        default=None, description="蓝本统计卡字段；未接入/降级为 null，副表未配置的统计组为 null"
    )
    ledger: LedgerOut
    errors: list[str] = Field(default_factory=list, description="降级时的错误标注")
