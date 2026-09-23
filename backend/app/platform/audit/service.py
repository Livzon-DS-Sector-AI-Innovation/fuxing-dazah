import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.platform.audit.models import AuditLog
from app.shared.sql import escape_like


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


async def list_audit_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 50,
    resource_type: str | None = None,
    resource_type_prefix: str | None = None,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[list[AuditLog], int]:
    """按条件分页读取审计日志，返回 ``(日志列表, 总数)``。

    这是审计表对外唯一的读接口：业务模块要展示某个资源域的审计记录时调用
    这里，不要直接 import ``AuditLog`` 自行拼查询（那样绕过审计模块的模型
    与索引约定，审计表结构变更时会同步炸掉所有调用方）。

    返回的是审计模块自己的 ORM 行，调用方只应读取字段，不要再做持久化。
    ``resource_type_prefix`` 用于按资源域前缀取子集（例如 ``"qa"``）。
    """
    conditions: list[ColumnElement[bool]] = []
    if resource_type_prefix:
        conditions.append(
            AuditLog.resource_type.like(
                f"{escape_like(resource_type_prefix)}%", escape="\\"
            )
        )
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if action:
        conditions.append(AuditLog.action == action)
    if resource_id:
        conditions.append(AuditLog.resource_id == resource_id)
    if start_at:
        conditions.append(AuditLog.created_at >= start_at)
    if end_at:
        conditions.append(AuditLog.created_at <= end_at)

    base = select(AuditLog).where(*conditions)
    total = int(
        (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    result = await db.execute(
        base.order_by(AuditLog.created_at.desc())
        .offset((max(page, 1) - 1) * page_size)
        .limit(page_size)
    )
    return list(result.scalars()), total
