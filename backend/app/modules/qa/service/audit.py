"""QA 操作日志查询：注册表驱动的通用读模型。

写入方在各自 service 里调 platform ``record_audit_log`` 写自己的
resource_type；开始写日志的域在本文件 ``OPERATION_LOG_SOURCES`` 登记
``{resource_type: (label, actions)}``，读取侧即自动纳入。注册表同时是
隔离闸门：旧版 QA 审计写过的杂项事件（ai_analysis_*/preview 等）不在
词表内，不会漏进操作日志页。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.service.apr.common import APR_LOG_ACTIONS

# 当前唯一来源：PQR 数据变更。新域接入 = 写入方 + 这里加一行。
OPERATION_LOG_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "qa.apr_batch": ("PQR 数据录入", APR_LOG_ACTIONS),
}


async def list_operation_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 50,
    resource_type: str | None = None,
    extra_equals: dict[str, str] | None = None,
    user_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[list[Any], int]:
    """按已登记的日志来源域分页读取操作日志。

    ``resource_type`` 不传 = 全部已登记域；``extra_equals`` 是来源域
    自定义定位字段的精确过滤（如 PQR 的 product_id/year）。
    """
    from app.platform.audit.service import list_audit_logs as _list_audit_logs

    sources = (
        {resource_type: OPERATION_LOG_SOURCES[resource_type]}
        if resource_type is not None
        else OPERATION_LOG_SOURCES
    )
    return await _list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        resource_types=sorted(sources),
        actions=sorted({a for _, actions in sources.values() for a in actions}),
        user_id=user_id,
        extra_equals=extra_equals,
        start_at=start_at,
        end_at=end_at,
    )
