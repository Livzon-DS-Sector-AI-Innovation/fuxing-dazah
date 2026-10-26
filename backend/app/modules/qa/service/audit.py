"""QA 审计日志查询。"""

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa import (
    file_service as file_service,  # 显式再导出，供 api 层与测试补丁使用
)

logger = logging.getLogger(__name__)


async def list_audit_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 50,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[list[Any], int]:
    from app.platform.audit.service import list_audit_logs as _list_audit_logs

    # 审计表由 platform/audit 拥有，这里只绑定 QA 的资源域前缀。
    normalized_resource_type = resource_type
    if normalized_resource_type and not normalized_resource_type.startswith("qa."):
        normalized_resource_type = f"qa.{normalized_resource_type}"
    return await _list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        resource_type_prefix="qa",
        user_id=user_id,
        action=action,
        resource_type=normalized_resource_type,
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
    )
