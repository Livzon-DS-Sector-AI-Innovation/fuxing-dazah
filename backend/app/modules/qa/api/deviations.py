"""QA 偏差管理 HTTP API：偏差台账 / 分阶段详情 / CAPA。

挂在 QA 模块路由下（``/api/v1/qa/deviations``、``/api/v1/qa/capas``）。
读取放行偏差/CAPA 专用读码或模块通配读码 ``qa:*:read``；写入各自独立。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.qa import file_service
from app.modules.qa.schemas import (
    CapaActionPatch,
    CapaCreate,
    CapaTransitionIn,
    CapaUpdate,
    DeviationCreate,
    DeviationExtendIn,
    DeviationTransitionIn,
    DeviationUpdate,
)
from app.modules.qa.service import deviation as service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()

_deviation_read = require_permission("qa:deviation:read", "qa:*:read")
_deviation_create = require_permission("qa:deviation:create")
_deviation_update = require_permission("qa:deviation:update")
_capa_read = require_permission("qa:capa:read", "qa:*:read")
_capa_create = require_permission("qa:capa:create")
_capa_update = require_permission("qa:capa:update")


# ───────────────────────── 偏差 ─────────────────────────


@router.get("/deviations", summary="偏差台账")
async def list_deviations(
    user: User = Depends(_deviation_read),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(default=None, max_length=200),
    status: str | None = None,
    classification: str | None = None,
    root_cause_category: str | None = None,
    department_name: str | None = None,
    is_repeat: bool | None = None,
    overdue_only: bool = False,
    discovery_from: date | None = None,
    discovery_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    items, total = await service.list_deviation_page(
        db,
        keyword=keyword,
        status=status,
        classification=classification,
        root_cause_category=root_cause_category,
        department_name=department_name,
        is_repeat=is_repeat,
        overdue_only=overdue_only,
        discovery_from=discovery_from,
        discovery_to=discovery_to,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.get("/deviations/summary", summary="偏差状态统计")
async def deviation_summary(
    user: User = Depends(_deviation_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(await service.deviation_status_summary(db))


@router.post("/deviations", summary="登记偏差", status_code=201)
async def create_deviation(
    payload: DeviationCreate,
    user: User = Depends(_deviation_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.create_deviation(db, payload, user)
    return success_response(await service.deviation_detail(db, row.id), status_code=201)


@router.get("/deviations/{deviation_id}", summary="偏差详情")
async def get_deviation(
    deviation_id: uuid.UUID,
    user: User = Depends(_deviation_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(await service.deviation_detail(db, deviation_id))


@router.put("/deviations/{deviation_id}", summary="编辑偏差（按阶段）")
async def update_deviation(
    deviation_id: uuid.UUID,
    payload: DeviationUpdate,
    user: User = Depends(_deviation_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.update_deviation(db, deviation_id, payload, user)
    return success_response(await service.deviation_detail(db, deviation_id))


@router.post("/deviations/{deviation_id}/transition", summary="推进偏差状态")
async def transition_deviation(
    deviation_id: uuid.UUID,
    payload: DeviationTransitionIn,
    user: User = Depends(_deviation_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.transition_deviation(db, deviation_id, payload, user)
    return success_response(await service.deviation_detail(db, deviation_id))


@router.post("/deviations/{deviation_id}/extend", summary="延长关闭期限")
async def extend_deviation(
    deviation_id: uuid.UUID,
    payload: DeviationExtendIn,
    user: User = Depends(_deviation_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.extend_deviation(db, deviation_id, payload, user)
    return success_response(await service.deviation_detail(db, deviation_id))


@router.delete("/deviations/{deviation_id}", summary="删除登记中的偏差")
async def delete_deviation(
    deviation_id: uuid.UUID,
    user: User = Depends(_deviation_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_deviation(db, deviation_id, user)
    return success_response({"id": str(deviation_id)})


@router.post(
    "/deviations/{deviation_id}/attachments", summary="上传偏差附件", status_code=201
)
async def upload_attachment(
    deviation_id: uuid.UUID,
    file: UploadFile = File(...),
    user: User = Depends(_deviation_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    data = await file.read(service.ATTACHMENT_MAX_SIZE + 1)
    row = await service.add_attachment(
        db,
        deviation_id,
        filename=file.filename,
        content_type=file.content_type,
        data=data,
        user=user,
    )
    return success_response(service.attachment_to_dict(row), status_code=201)


@router.get(
    "/deviations/{deviation_id}/attachments/{attachment_id}/content",
    summary="下载偏差附件",
)
async def download_attachment(
    deviation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user: User = Depends(_deviation_read),
    db: AsyncSession = Depends(get_db),
    download: bool = False,
) -> StreamingResponse:
    attachment, data, mime = await service.read_attachment(
        db, deviation_id, attachment_id
    )
    # 批记录复印件/COA 等证据的预览与下载要留审计痕迹（与 files.py 同口径）。
    await service._audit(
        db,
        action="download" if download else "preview",
        user=user,
        resource_type="deviation_attachment",
        resource_id=attachment.id,
        extra={"deviation_id": str(deviation_id)},
    )
    # PDF 与图片可内联预览，其余一律下载；inline_media_type 已排除 HTML/SVG。
    inline = file_service.inline_media_type(mime)
    disposition = "inline" if inline and not download else "attachment"
    headers = {
        "Content-Disposition": file_service.content_disposition(
            disposition, attachment.file_name
        ),
        "X-Content-SHA256": attachment.sha256,
    }
    return StreamingResponse(iter([data]), media_type=mime, headers=headers)


@router.delete(
    "/deviations/{deviation_id}/attachments/{attachment_id}", summary="删除偏差附件"
)
async def delete_attachment(
    deviation_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user: User = Depends(_deviation_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.delete_attachment(db, deviation_id, attachment_id, user)
    return success_response({"id": str(attachment_id)})


# ───────────────────────── CAPA ─────────────────────────


@router.get("/capas", summary="CAPA 台账")
async def list_capas(
    user: User = Depends(_capa_read),
    db: AsyncSession = Depends(get_db),
    keyword: str | None = Query(default=None, max_length=200),
    status: str | None = None,
    severity: str | None = None,
    deviation_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    items, total = await service.list_capa_page(
        db,
        keyword=keyword,
        status=status,
        severity=severity,
        deviation_id=deviation_id,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.get("/capas/summary", summary="CAPA 状态统计")
async def capa_summary(
    user: User = Depends(_capa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(await service.capa_status_summary(db))


@router.post("/capas", summary="发起 CAPA", status_code=201)
async def create_capa(
    payload: CapaCreate,
    user: User = Depends(_capa_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.create_capa(db, payload, user)
    return success_response(await service.capa_detail(db, row.id), status_code=201)


@router.get("/capas/{capa_id}", summary="CAPA 详情")
async def get_capa(
    capa_id: uuid.UUID,
    user: User = Depends(_capa_read),
    db: AsyncSession = Depends(get_db),
) -> Any:
    return success_response(await service.capa_detail(db, capa_id))


@router.put("/capas/{capa_id}", summary="编辑 CAPA")
async def update_capa(
    capa_id: uuid.UUID,
    payload: CapaUpdate,
    user: User = Depends(_capa_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.update_capa(db, capa_id, payload, user)
    return success_response(await service.capa_detail(db, capa_id))


@router.patch("/capas/{capa_id}/actions/{action_id}", summary="更新单条 CAPA 措施")
async def patch_capa_action(
    capa_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: CapaActionPatch,
    user: User = Depends(_capa_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.patch_capa_action(db, capa_id, action_id, payload, user)
    return success_response(await service.capa_detail(db, capa_id))


@router.post("/capas/{capa_id}/transition", summary="推进 CAPA 状态")
async def transition_capa(
    capa_id: uuid.UUID,
    payload: CapaTransitionIn,
    user: User = Depends(_capa_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.transition_capa(db, capa_id, payload, user)
    return success_response(await service.capa_detail(db, capa_id))
