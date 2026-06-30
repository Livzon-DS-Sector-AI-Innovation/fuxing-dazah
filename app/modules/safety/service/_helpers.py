"""Shared helper functions for safety service classes."""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.audit.service import record_audit_log

logger = logging.getLogger(__name__)


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
