"""Shared helper functions for safety service classes."""

import datetime as _dt
import logging
import uuid
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)


def json_safe(value: Any) -> Any:
    """将审计入参递归转成 JSON 可序列化值（datetime/date/uuid/Enum → str）。

    audit.logs 的 old_value/new_value 是 JSON 列，直接传 datetime 会在
    flush 时抛 JSON 序列化错误并污染事务，必须在此归一。
    """
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


async def audit_log(
    session: AsyncSession,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record an audit log entry, swallowing errors.

    This is a shared helper used by all safety service classes to avoid
    duplicating the same try/except audit wrapper in every service file.
    """
    try:
        await record_audit_log(
            session,
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            old_value=old_value,
            new_value=new_value,
            extra=extra,
        )
    except Exception:
        logger.exception("审计日志记录失败 (%s:%s)", resource_type, action)
