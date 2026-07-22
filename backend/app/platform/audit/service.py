import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.models import AuditLog


async def record_audit_log(
    db: AsyncSession,
    *,
    action: str,
    user: Any = None,
    user_id: uuid.UUID | None = None,
    request_id: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    impersonated_by: uuid.UUID | None = None,
) -> AuditLog:
    """记录审计日志。

    传入 user 对象时自动提取 user_id 和 _impersonated_by（代理模式）。
    也可直接传 user_id 兼容现有调用方。
    """
    if user is not None:
        user_id = user.id
        impersonated_by = getattr(user, "_impersonated_by", None)

    if impersonated_by:
        if extra is None:
            extra = {}
        extra["impersonated_by"] = str(impersonated_by)

    audit_log = AuditLog(
        request_id=request_id,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        extra=extra,
    )
    db.add(audit_log)
    await db.flush()
    return audit_log
