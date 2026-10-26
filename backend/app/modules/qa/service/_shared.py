"""QA 服务层公共辅助：文本归一化、必填校验、审计与部门校验。"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
)
from app.modules.qa import (
    file_service as file_service,  # 显式再导出，供 api 层与测试补丁使用
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

logger = logging.getLogger(__name__)


def normalize_code(value: str) -> str:
    return " ".join(value.strip().upper().split())


def normalize_text(value: str) -> str:
    return " ".join(value.strip().upper().split())


def _require_text(value: Any, label: str) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        raise AppException(status_code=422, message=f"{label}不能为空")
    return text_value


def _actor_id(user: User | None) -> uuid.UUID | None:
    return user.id if user is not None else None


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    user: User | None,
    resource_type: str,
    resource_id: uuid.UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    await record_audit_log(
        db,
        action=action,
        user=user,
        user_id=_actor_id(user),
        resource_type=f"qa.{resource_type}",
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        extra=extra,
    )


async def _validate_department(
    db: AsyncSession,
    department_id: str | None,
    department_name: str | None,
) -> tuple[str | None, str | None]:
    if not department_id:
        if department_name and department_name.strip():
            raise AppException(
                status_code=422, message="责任部门必须使用有效的飞书部门 ID"
            )
        return None, None
    from app.platform.identity.public_api import get_department_brief

    department = await get_department_brief(db, department_id)
    if department is None or not department.is_active:
        raise AppException(status_code=422, message="责任部门不存在或已停用")
    return department.feishu_department_id, department.name


async def _resolve_department_patch(
    db: AsyncSession,
    *,
    current_id: str | None,
    current_name: str | None,
    data: dict[str, Any],
) -> tuple[str | None, str | None]:
    """解析主数据/文件台账的部门部分更新并重新取得名称快照。"""
    id_present = "responsible_department_id" in data
    name_present = "responsible_department_name_snapshot" in data
    if id_present:
        return await _validate_department(
            db,
            data.get("responsible_department_id"),
            data.get("responsible_department_name_snapshot"),
        )
    if name_present:
        if current_id:
            return await _validate_department(db, current_id, None)
        if data.get("responsible_department_name_snapshot"):
            raise AppException(
                status_code=422, message="责任部门必须使用有效的飞书部门 ID"
            )
        return None, None
    return current_id, current_name
