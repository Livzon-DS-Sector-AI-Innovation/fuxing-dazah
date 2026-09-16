"""仓储 Agent Web 快速登记路由（分期B Ticket 07）。

上传单据图片 → 识别建稿（复用既有 pipeline，source=web）→ 确认/提交
（复用 confirm.handle_action，与飞书卡片动作同一套校验链与提交通道）。
"""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent.confirm import handle_action
from app.modules.warehouse.agent.llm_client import WarehouseLLMError
from app.modules.warehouse.agent.pipeline import (
    align_receipt,
    create_receipt_draft,
    mark_aligned,
    recognize_receipt,
)
from app.modules.warehouse.ai_audit.context import warehouse_audit_scope
from app.modules.warehouse.ai_config.exceptions import ScenarioDisabledError
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()

UPLOAD_DIR = Path("uploads/agent")
UPLOAD_NAME_RE = re.compile(r"^[a-f0-9-]+\.(jpg|jpeg|png|webp)$")
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class RecognitionRequest(BaseModel):
    upload_id: str = Field(min_length=1, max_length=80, description="上传返回的图片引用")


class DraftConfirmRequest(BaseModel):
    action: str = Field(pattern="^(confirm|cancel)$", description="confirm 确认 / cancel 取消")


def _web_open_id(user: User) -> str:
    return f"web:{user.id}"


def _resolve_upload_path(upload_id: str) -> Path | None:
    if not UPLOAD_NAME_RE.match(upload_id):
        return None
    path = UPLOAD_DIR / upload_id
    return path if path.exists() else None


@router.post("/agent/uploads", status_code=201, summary="上传单据图片（快速登记）")
async def upload_receipt_image(
    file: UploadFile = File(...),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "仅支持 jpg/png/webp 图片"},
        )
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "图片不能超过 10MB"},
        )
    ext = ALLOWED_CONTENT_TYPES[content_type]
    upload_id = str(uuid.uuid4()) + ext
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / upload_id).write_bytes(data)
    return JSONResponse(
        status_code=201,
        content={
            "code": 201,
            "message": "success",
            "data": {"upload_id": upload_id},
        },
    )


@router.get("/agent/uploads/{upload_id}", summary="获取已上传的单据图片")
async def get_uploaded_image(
    upload_id: str,
    user: User = Depends(require_permission("warehouse:stock:read")),
) -> Response:
    path = _resolve_upload_path(upload_id)
    if path is None:
        return JSONResponse(status_code=404, content={"code": 404, "message": "图片不存在"})
    media_type = "image/webp" if upload_id.endswith(".webp") else ("image/png" if upload_id.endswith(".png") else "image/jpeg")
    return FileResponse(path, media_type=media_type)


@router.post("/agent/recognition", status_code=201, summary="识别单据并创建草稿（Web 来源）")
async def recognize_uploaded_receipt(
    payload: RecognitionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    path = _resolve_upload_path(payload.upload_id)
    if path is None:
        return JSONResponse(status_code=404, content={"code": 404, "message": "图片不存在或已清理"})

    import asyncio
    image_b64 = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
    content_type = "image/png" if payload.upload_id.endswith(".png") else "image/jpeg"
    open_id = _web_open_id(user)
    try:
        with warehouse_audit_scope(
            "receipt_recognition",
            trace_id=str(uuid.uuid4()),
            resource="web_recognition",
            user_open_id=open_id,
            channel="web",
        ):
            recognized = await recognize_receipt(image_b64, content_type)
            aligned = await align_receipt(recognized)
            draft = await create_receipt_draft(
                db,
                recognized=recognized,
                image_file_token=f"web:{payload.upload_id}",
                open_id=open_id,
                chat_id=None,
            )
            draft.source = "web"
            await mark_aligned(db, draft, aligned)
            await db.commit()
    except ScenarioDisabledError:
        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "单据识别暂时不可用（已熔断），请稍后再试"},
        )
    except WarehouseLLMError:
        return JSONResponse(
            status_code=502,
            content={"code": 502, "message": "识别服务暂不可用，请稍后再试"},
        )

    return JSONResponse(
        status_code=201,
        content={
            "code": 201,
            "message": "success",
            "data": {
                "draft_id": str(draft.id),
                "draft_no": draft.draft_no,
                "status": draft.status,
                "recognized": draft.recognized,
                "aligned": draft.aligned,
            },
        },
    )


@router.get("/agent/drafts/{draft_id}", summary="草稿详情（确认页用）")
async def get_web_draft(
    draft_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    try:
        draft_uuid = uuid.UUID(draft_id)
    except ValueError:
        return JSONResponse(status_code=422, content={"code": 422, "message": "非法草稿 ID"})
    draft = await agent_repository.get_agent_draft(db, draft_uuid)
    if draft is None or draft.source != "web" or draft.created_by_open_id != _web_open_id(user):
        return JSONResponse(status_code=404, content={"code": 404, "message": "草稿不存在"})
    return JSONResponse(
        status_code=200,
        content={
            "code": 200,
            "message": "success",
            "data": {
                "draft_id": str(draft.id),
                "draft_no": draft.draft_no,
                "status": draft.status,
                "scene": draft.scene,
                "source_image": draft.source_image,
                "recognized": draft.recognized,
                "aligned": draft.aligned
            },
        },
    )


@router.post("/agent/drafts/{draft_id}/confirm", summary="确认/取消草稿（Web 确认页）")
async def confirm_web_draft(
    draft_id: str,
    payload: DraftConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    try:
        draft_uuid = uuid.UUID(draft_id)
    except ValueError:
        return JSONResponse(status_code=422, content={"code": 422, "message": "非法草稿 ID"})
    draft = await agent_repository.get_agent_draft(db, draft_uuid)
    if draft is None or draft.source != "web" or draft.created_by_open_id != _web_open_id(user):
        return JSONResponse(status_code=404, content={"code": 404, "message": "草稿不存在"})

    # Web 确认页替代飞书确认卡片：aligned → pending_confirm 的迁移在本路由完成
    # （飞书侧该迁移由 send_confirm_card 承担），否则 handle_action 会因
    # 状态非 pending_confirm 直接拒绝，确认链断裂。
    if payload.action == "confirm" and draft.status == "aligned":
        draft.status = "pending_confirm"
        await db.flush()

    outcome = await handle_action(
        db,
        value={
            "action": payload.action,
            "scene": draft.scene,
            "draft_id": str(draft.id),
        },
        operator_open_id=_web_open_id(user),
    )
    fresh = await agent_repository.get_agent_draft(db, draft_uuid)
    return JSONResponse(
        status_code=200,
        content={
            "code": 200 if outcome.ok else 400,
            "message": outcome.message or ("success" if outcome.ok else "处理失败"),
            "data": {
                "ok": outcome.ok,
                "status": outcome.status,
                "draft_status": fresh.status if fresh else None,
            },
        },
    )
