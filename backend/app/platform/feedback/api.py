"""系统反馈 HTTP 路由。

- 提交 / 我的反馈 / 为自己的反馈上传截图：任何登录用户（``require_user``）
- 全部列表 / 待处理计数 / 标记已处理：``system:feedback:manage``（超管默认拥有，
  也可单独授予其他角色；权限声明见 app/platform/permission/registry.py）
- 截图读取/删除的「本人或管理员」判断在 service 层完成（本人没有权限码）
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.core import file_storage
from app.core.database import get_db
from app.core.exceptions import AppException
from app.core.response import paginated_response, success_response
from app.platform.feedback import service
from app.platform.feedback.models import Feedback, FeedbackAttachment, FeedbackType
from app.platform.feedback.schemas import (
    FeedbackAttachmentOut,
    FeedbackCreate,
    FeedbackHandledIn,
    FeedbackOut,
    FeedbackPendingCountOut,
)
from app.platform.feedback.service import MANAGE_PERMISSION
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission, require_user

router = APIRouter()


def _out(
    feedback: Feedback, attachments: Sequence[FeedbackAttachment] = ()
) -> dict[str, object]:
    out = FeedbackOut.model_validate(feedback)
    out.attachments = [FeedbackAttachmentOut.model_validate(a) for a in attachments]
    return out.model_dump(mode="json")


async def _outs(db: AsyncSession, feedbacks: Sequence[Feedback]) -> list[dict[str, object]]:
    grouped = await service.attachments_for(db, feedbacks)
    return [_out(f, grouped.get(f.id, [])) for f in feedbacks]


def _attachment_out(attachment: FeedbackAttachment) -> dict[str, object]:
    return FeedbackAttachmentOut.model_validate(attachment).model_dump(mode="json")


@router.post("", summary="提交系统反馈")
async def submit_feedback(
    payload: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> JSONResponse:
    feedback = await service.submit_feedback(db, user, payload)
    return success_response(_out(feedback), status_code=201)


@router.get("/mine", summary="我的反馈")
async def list_my_feedbacks(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> JSONResponse:
    items, total = await service.list_my_feedbacks(
        db, user, page=page, page_size=page_size
    )
    return paginated_response(await _outs(db, items), page, page_size, total)


@router.get("/pending-count", summary="待处理反馈数量（管理）")
async def pending_count(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_permission(MANAGE_PERMISSION)),
) -> JSONResponse:
    pending = await service.pending_count(db)
    return success_response(
        FeedbackPendingCountOut(pending=pending).model_dump(mode="json")
    )


@router.get("", summary="反馈列表（管理）")
async def list_feedbacks(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_permission(MANAGE_PERMISSION)),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    is_handled: bool | None = Query(None),
    type: FeedbackType | None = Query(None),
) -> JSONResponse:
    items, total = await service.list_feedbacks(
        db,
        page=page,
        page_size=page_size,
        is_handled=is_handled,
        feedback_type=type,
    )
    return paginated_response(await _outs(db, items), page, page_size, total)


@router.patch("/{feedback_id}/handled", summary="标记/取消已处理（管理）")
async def set_handled(
    feedback_id: uuid.UUID,
    payload: FeedbackHandledIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_permission(MANAGE_PERMISSION)),
) -> JSONResponse:
    feedback = await service.set_handled(db, admin, feedback_id, payload.is_handled)
    grouped = await service.attachments_for(db, [feedback])
    return success_response(_out(feedback, grouped.get(feedback.id, [])))


# ───────────────────────── 截图附件 ─────────────────────────


@router.post(
    "/{feedback_id}/attachments", summary="上传反馈截图（仅提交人本人）", status_code=201
)
async def upload_attachment(
    feedback_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> JSONResponse:
    try:
        # Starlette 在进入处理函数前就把 multipart 落到临时文件；这里限制单个
        # part 的大小，避免超大请求写满磁盘（与 meter 上传接口同一写法）。
        form = await request.form(max_part_size=service.ATTACHMENT_MAX_SIZE)
    except HTTPException as exc:
        # 解析层拦下的超限 part 统一成业务 422 文案
        if exc.status_code != 400:
            raise
        limit_mb = service.ATTACHMENT_MAX_SIZE // (1024 * 1024)
        raise AppException(
            status_code=422, message=f"附件大小不能超过 {limit_mb}MB"
        ) from exc
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise AppException(status_code=422, message="缺少 file 参数")
    # 多读 1 字节即可判定超限，不把超大文件整个读进内存
    data = await file.read(service.ATTACHMENT_MAX_SIZE + 1)
    attachment = await service.add_attachment(
        db,
        user,
        feedback_id,
        filename=file.filename,
        data=data,
    )
    return success_response(_attachment_out(attachment), status_code=201)


@router.get(
    "/{feedback_id}/attachments/{attachment_id}/content",
    summary="读取反馈截图（本人或管理员）",
)
async def read_attachment(
    feedback_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> StreamingResponse:
    attachment, data = await service.read_attachment(db, user, feedback_id, attachment_id)
    # 只收图片，正常都能内联；白名单仍兜底防止异常 MIME 被浏览器当脚本执行
    inline = file_storage.inline_media_type(attachment.mime_type)
    headers = {
        "Content-Disposition": file_storage.content_disposition(
            "inline" if inline else "attachment", attachment.file_name
        ),
        "X-Content-SHA256": attachment.sha256,
    }
    return StreamingResponse(iter([data]), media_type=attachment.mime_type, headers=headers)


@router.delete(
    "/{feedback_id}/attachments/{attachment_id}",
    summary="删除反馈截图（本人未处理前，或管理员）",
)
async def delete_attachment(
    feedback_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_user),
) -> JSONResponse:
    await service.delete_attachment(db, user, feedback_id, attachment_id)
    return success_response({"id": str(attachment_id)})
