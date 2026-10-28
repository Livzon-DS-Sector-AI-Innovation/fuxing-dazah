"""系统反馈业务编排：提交、列表、标记已处理、截图附件与审计。"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import file_storage
from app.core.exceptions import AppException, ForbiddenException, NotFoundException
from app.platform.audit.service import record_audit_log
from app.platform.feedback import repository
from app.platform.feedback.models import Feedback, FeedbackAttachment, FeedbackType
from app.platform.feedback.schemas import FeedbackCreate
from app.platform.identity.models import User
from app.platform.permission import deps as permission_deps

# 平台权限码，声明于 app/platform/permission/registry.py；超管默认拥有
MANAGE_PERMISSION = "system:feedback:manage"

# 截图附件：仅图片、单张 5MB、每条 3 张
ATTACHMENT_MAX_COUNT = 3
ATTACHMENT_MAX_SIZE = 5 * 1024 * 1024
_IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
_STORAGE_MODULE = "feedback"


async def submit_feedback(
    db: AsyncSession, user: User, data: FeedbackCreate
) -> Feedback:
    """提交反馈：快照提交人姓名/部门并写审计。INSERT 走 RETURNING，flush 后即可返回。"""
    feedback = Feedback(
        type=data.type.value,
        content=data.content,
        page_path=data.page_path,
        submitter_name=user.name,
        submitter_department=user.department,
        created_by=user.id,
    )
    await repository.create(db, feedback)
    await record_audit_log(
        db,
        action="feedback.submit",
        user=user,
        resource_type="feedback",
        resource_id=feedback.id,
        new_value={"type": feedback.type, "content": feedback.content},
    )
    return feedback


async def set_handled(
    db: AsyncSession, admin: User, feedback_id: uuid.UUID, is_handled: bool
) -> Feedback:
    """标记/取消「已处理」，记录处理人快照与时间。"""
    feedback = await repository.get_by_id(db, feedback_id)
    if feedback is None:
        raise NotFoundException("反馈", str(feedback_id))

    previous = feedback.is_handled
    feedback.is_handled = is_handled
    feedback.updated_by = admin.id
    if is_handled:
        feedback.handled_by = admin.id
        feedback.handled_by_name = admin.name
        feedback.handled_at = datetime.now(UTC)
    else:
        feedback.handled_by = None
        feedback.handled_by_name = None
        feedback.handled_at = None
    await db.flush()

    # UPDATE 不走 RETURNING，onupdate 的 updated_at 不会回填到内存对象；
    # 重新查询让过期属性在 session 内加载，避免响应序列化时触发 MissingGreenlet。
    refreshed = await repository.get_by_id(db, feedback_id)
    if refreshed is None:
        raise NotFoundException("反馈", str(feedback_id))

    await record_audit_log(
        db,
        action="feedback.mark_handled" if is_handled else "feedback.unmark_handled",
        user=admin,
        resource_type="feedback",
        resource_id=feedback_id,
        old_value={"is_handled": previous},
        new_value={"is_handled": is_handled},
    )
    return refreshed


async def list_feedbacks(
    db: AsyncSession,
    *,
    page: int,
    page_size: int,
    is_handled: bool | None = None,
    feedback_type: FeedbackType | None = None,
) -> tuple[list[Feedback], int]:
    return await repository.list_paginated(
        db,
        page=page,
        page_size=page_size,
        is_handled=is_handled,
        feedback_type=feedback_type,
    )


async def list_my_feedbacks(
    db: AsyncSession, user: User, *, page: int, page_size: int
) -> tuple[list[Feedback], int]:
    return await repository.list_paginated(
        db, page=page, page_size=page_size, created_by=user.id
    )


async def pending_count(db: AsyncSession) -> int:
    return await repository.count_pending(db)


async def attachments_for(
    db: AsyncSession, feedbacks: Sequence[Feedback]
) -> dict[uuid.UUID, list[FeedbackAttachment]]:
    return await repository.list_attachments_for(db, [f.id for f in feedbacks])


# ───────────────────────── 截图附件 ─────────────────────────


async def _get_feedback(
    db: AsyncSession, feedback_id: uuid.UUID, *, for_update: bool = False
) -> Feedback:
    feedback = await repository.get_by_id(db, feedback_id, for_update=for_update)
    if feedback is None:
        raise NotFoundException("反馈", str(feedback_id))
    return feedback


async def _can_manage(db: AsyncSession, user: User) -> bool:
    # 以模块属性方式调用，测试 patch deps.get_user_permissions 才能生效
    perms = await permission_deps.get_user_permissions(str(user.id), db)
    return MANAGE_PERMISSION in perms


def _ensure_unhandled(feedback: Feedback) -> None:
    if feedback.is_handled:
        raise AppException(status_code=409, message="反馈已处理，不能再修改截图")


async def add_attachment(
    db: AsyncSession,
    user: User,
    feedback_id: uuid.UUID,
    *,
    filename: str | None,
    data: bytes,
) -> FeedbackAttachment:
    """提交人本人在反馈未处理前上传截图；对象先落存储，落库/审计失败则清理孤儿对象。"""
    feedback = await _get_feedback(db, feedback_id, for_update=True)
    if feedback.created_by != user.id:
        raise ForbiddenException("只能为自己提交的反馈上传截图")
    _ensure_unhandled(feedback)
    if await repository.count_attachments(db, feedback.id) >= ATTACHMENT_MAX_COUNT:
        raise AppException(
            status_code=422, message=f"每条反馈最多 {ATTACHMENT_MAX_COUNT} 张截图"
        )
    safe_name, extension, mime = file_storage.validate_upload(
        filename,
        data,
        allowed=_IMAGE_MIME,
        max_size=ATTACHMENT_MAX_SIZE,
        kind_label="PNG、JPG、WEBP、GIF",
        default_name="screenshot",
    )
    key = f"feedback/{feedback.id}/{uuid.uuid4().hex}.{extension}"
    try:
        # MinIO/本地写盘是阻塞调用，放进线程池避免占住事件循环
        await asyncio.to_thread(
            file_storage.store_object, _STORAGE_MODULE, key, data, mime
        )
        attachment = FeedbackAttachment(
            feedback_id=feedback.id,
            file_name=safe_name,
            storage_key=key,
            mime_type=mime,
            file_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            uploaded_by_name=user.name,
            created_by=user.id,
            updated_by=user.id,
        )
        await repository.add_attachment(db, attachment)
        await record_audit_log(
            db,
            action="feedback.attachment_add",
            user=user,
            resource_type="feedback",
            resource_id=feedback.id,
            new_value={
                "attachment_id": str(attachment.id),
                "file_name": safe_name,
                "sha256": attachment.sha256,
            },
        )
    except Exception:
        # 写入半途失败、落库失败或审计失败都会回滚事务；同时清掉孤儿对象。
        await asyncio.to_thread(
            file_storage.cleanup_object, _STORAGE_MODULE, key
        )
        raise
    return attachment


async def read_attachment(
    db: AsyncSession, user: User, feedback_id: uuid.UUID, attachment_id: uuid.UUID
) -> tuple[FeedbackAttachment, bytes]:
    """提交人本人或持管理权限者可读；读取不记审计（截图低敏，避免噪音）。"""
    feedback = await _get_feedback(db, feedback_id)
    if feedback.created_by != user.id and not await _can_manage(db, user):
        raise ForbiddenException("无权查看该反馈的截图")
    attachment = await repository.get_attachment(db, feedback.id, attachment_id)
    if attachment is None:
        raise NotFoundException("截图", str(attachment_id))
    stored = await asyncio.to_thread(
        file_storage.read_object, _STORAGE_MODULE, attachment.storage_key
    )
    if stored is None:
        raise NotFoundException("截图文件", attachment.file_name)
    return attachment, stored[0]


async def delete_attachment(
    db: AsyncSession, user: User, feedback_id: uuid.UUID, attachment_id: uuid.UUID
) -> None:
    """本人在未处理前可删；管理员随时可删（处置误传的敏感内容）。"""
    feedback = await _get_feedback(db, feedback_id, for_update=True)
    is_manager = await _can_manage(db, user)
    if feedback.created_by != user.id and not is_manager:
        raise ForbiddenException("无权删除该反馈的截图")
    if not is_manager:
        _ensure_unhandled(feedback)
    attachment = await repository.get_attachment(db, feedback.id, attachment_id)
    if attachment is None:
        raise NotFoundException("截图", str(attachment_id))

    attachment.is_deleted = True
    attachment.updated_by = user.id
    await db.flush()
    await asyncio.to_thread(
        file_storage.delete_object, _STORAGE_MODULE, attachment.storage_key
    )
    await record_audit_log(
        db,
        action="feedback.attachment_delete",
        user=user,
        resource_type="feedback",
        resource_id=feedback.id,
        old_value={
            "attachment_id": str(attachment.id),
            "file_name": attachment.file_name,
        },
    )
