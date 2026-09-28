"""仓储 Agent Web 快速登记路由（分期B Ticket 07）。

上传单据图片 → 识别建稿（复用既有 pipeline，source=web）→ 确认/提交
（复用 confirm.handle_action，与飞书卡片动作同一套校验链与提交通道）。

2026-09-28 识别完善 B 项：
- 识别端点接成品分支（classify_document 路由，与飞书 gateway 同款）：
  成品入库单 → recognize_finished_receipt + 成品名录对齐 → scene=
  finished_receipt 草稿——Web 端从此也能识别登记成品入库；
- 新增 PATCH /agent/drafts/{id}/fields：确认页表单直改字段/行（写
  aligned working set，与飞书对话 update_draft 同一取值口径），修正确认
  不再依赖逐字段对话。
"""

from __future__ import annotations

import base64
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.warehouse.agent import repository as agent_repository
from app.modules.warehouse.agent.confirm import handle_action
from app.modules.warehouse.agent.llm_client import WarehouseLLMError
from app.modules.warehouse.agent.pipeline import (
    DOC_TYPE_FINISHED,
    FINISHED_RECEIPT_SCENE,
    align_finished_receipt,
    align_receipt,
    classify_document,
    create_receipt_draft,
    mark_aligned,
    mark_finished_aligned,
    recognize_finished_receipt,
    recognize_receipt,
)
from app.modules.warehouse.agent.tools.draft_update import map_fields
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


class DraftFieldsUpdateRequest(BaseModel):
    """确认页表单直改 payload：fields 标量键值对 + rows 成品多行行集（可选）。"""

    fields: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] | None = None


# 成品行集可编辑键与行级必填（识别 rows 同契约）
_ROW_EDITABLE_KEYS: tuple[str, ...] = (
    "product_name",
    "product_batch_no",
    "quantity",
    "unit",
    "spec",
    "produced_at",
    "expiry",
    "remark",
)
_ROW_REQUIRED_KEYS: tuple[str, ...] = ("product_name", "product_batch_no", "quantity", "unit")

# 可修改状态（与 draft_update.MUTABLE_STATUSES 同口径）
_WEB_MUTABLE_STATUSES: tuple[str, ...] = ("aligned", "pending_confirm")


def _normalize_rows_payload(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """网页行编辑 payload → 规范行集（4 必填齐全 + 数量可数字化），非法抛 ValueError。"""
    normalized: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("行格式不正确（须为对象）")
        row = {
            key: str(item[key]).strip()
            for key in _ROW_EDITABLE_KEYS
            if item.get(key) is not None and str(item[key]).strip()
        }
        missing = [key for key in _ROW_REQUIRED_KEYS if not row.get(key)]
        if missing:
            raise ValueError(f"行缺少必填字段: {'、'.join(missing)}")
        try:
            float(str(row["quantity"]).replace(",", ""))
        except ValueError:
            raise ValueError(f"行数量不是数字: {row['quantity']}") from None
        normalized.append(row)
    return normalized


def _first_group_total(rows: list[dict[str, str]]) -> float | None:
    """首组（产品, 批号, 单位）数量合计——aligned.scalar quantity 同步值
    （recognizer.build_finished_receipt 主行归组总和同口径，防网页行编辑后
    旧标量覆盖新行集）。"""
    total: float | None = None
    group_key: tuple[str, str, str] | None = None
    for row in rows:
        try:
            num = float(str(row.get("quantity")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        key = (
            str(row.get("product_name", "")),
            str(row.get("product_batch_no", "")),
            str(row.get("unit", "")),
        )
        if group_key is None:
            group_key = key
            total = 0.0
        if key == group_key:
            total = (total or 0.0) + num
    return total


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
            # 单据分类路由（与飞书 gateway 同款）：成品入库单走成品识别
            # 分支（独立审计作用域——嵌套安全，contextvars set/reset）；
            # 分类失败/原辅料单回落既有链路（零回归）
            doc_type = await classify_document(image_b64, content_type)
            if doc_type == DOC_TYPE_FINISHED:
                with warehouse_audit_scope(
                    "finished_receipt_recognition",
                    trace_id=str(uuid.uuid4()),
                    user_open_id=open_id,
                    channel="web",
                ):
                    recognized = await recognize_finished_receipt(image_b64, content_type)
                    aligned_finished = await align_finished_receipt(recognized)
                    draft = await create_receipt_draft(
                        db,
                        recognized=recognized,
                        image_file_token=f"web:{payload.upload_id}",
                        open_id=open_id,
                        chat_id=None,
                        scene=FINISHED_RECEIPT_SCENE,
                    )
                    draft.source = "web"
                    await mark_finished_aligned(db, draft, aligned_finished)
            else:
                recognized_raw = await recognize_receipt(image_b64, content_type)
                aligned_raw = await align_receipt(recognized_raw)
                draft = await create_receipt_draft(
                    db,
                    recognized=recognized_raw,
                    image_file_token=f"web:{payload.upload_id}",
                    open_id=open_id,
                    chat_id=None,
                )
                draft.source = "web"
                await mark_aligned(db, draft, aligned_raw)
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
                "scene": draft.scene,
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


@router.patch("/agent/drafts/{draft_id}/fields", summary="修改草稿字段/行（Web 确认页表单）")
async def update_web_draft_fields(
    draft_id: str,
    payload: DraftFieldsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("warehouse:movement:create")),
) -> JSONResponse:
    """确认页表单直改（2026-09-28 B 项）：字段/行写入 aligned working set。

    与飞书对话 update_draft 同一取值口径（aligned 覆盖 recognized、submit
    aligned 优先），修正确认不再依赖逐字段对话。改过的字段同步清掉对应
    识别警示；rows 提供时整体替换 aligned["rows"] 并把 scalar quantity
    同步为首组合计。仅 web 来源草稿本人可改（与确认端点同鉴权口径）。
    """
    try:
        draft_uuid = uuid.UUID(draft_id)
    except ValueError:
        return JSONResponse(status_code=422, content={"code": 422, "message": "非法草稿 ID"})
    draft = await agent_repository.get_agent_draft(db, draft_uuid)
    if draft is None or draft.source != "web" or draft.created_by_open_id != _web_open_id(user):
        return JSONResponse(status_code=404, content={"code": 404, "message": "草稿不存在"})
    if draft.status not in _WEB_MUTABLE_STATUSES:
        return JSONResponse(
            status_code=422,
            content={
                "code": 422,
                "message": f"草稿当前状态 {draft.status}，不可修改（已确认/已取消/已过期请重新上传识别）",
            },
        )
    if draft.expires_at is not None and draft.expires_at < datetime.now(UTC):
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "草稿已过期，请重新上传识别"},
        )
    if payload.rows is None and not payload.fields:
        return JSONResponse(status_code=422, content={"code": 422, "message": "没有可应用的修改"})

    mapped, unknown = map_fields(payload.fields)
    if unknown:
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": f"不支持的字段: {'、'.join(unknown)}"},
        )

    rows_payload: list[dict[str, str]] | None = None
    if payload.rows is not None:
        try:
            rows_payload = _normalize_rows_payload(payload.rows)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"code": 422, "message": str(exc)})

    aligned = dict(draft.aligned or {})
    aligned.update(mapped)
    warnings = aligned.get("warnings")
    if isinstance(warnings, dict) and warnings:
        for key in mapped:
            warnings.pop(key, None)
        aligned["warnings"] = warnings
    if rows_payload is not None:
        aligned["rows"] = rows_payload
        total = _first_group_total(rows_payload)
        if total is not None:
            aligned["quantity"] = int(total) if float(total).is_integer() else total
    draft.aligned = aligned  # JSONB 重新赋值才触发 UPDATE
    await agent_repository.insert_agent_audit(
        db,
        tool_name="web_draft_update",
        args_summary={
            "draft_no": draft.draft_no,
            "fields": sorted(mapped),
            "rows": None if rows_payload is None else len(rows_payload),
        },
        result_status="ok",
        draft_id=draft.id,
    )
    await db.commit()

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
                "recognized": draft.recognized,
                "aligned": draft.aligned,
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
