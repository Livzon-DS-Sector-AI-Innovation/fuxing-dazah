"""工单图片 API 路由."""

import os
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.exceptions import AppException, NotFoundException
from app.core.response import success_response
from app.modules.equipment import repository as repo
from app.modules.equipment import service
from app.modules.equipment.schemas import WorkOrderImageResponse

router = APIRouter()


def _require_user(current_user: CurrentUser) -> uuid.UUID:
    if not current_user:
        raise AppException(message="需要登录才能执行此操作", status_code=401)
    return current_user.id


@router.post("/{work_order_id}/images", summary="上传工单图片")
async def upload_work_order_images(
    work_order_id: uuid.UUID,
    files: list[UploadFile] = File(..., description="图片文件"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    _require_user(current_user)
    images = await service.upload_images(db, work_order_id, files)
    return success_response(
        data=[WorkOrderImageResponse.model_validate(img) for img in images]
    )


@router.get("/{work_order_id}/images", summary="获取工单图片列表")
async def list_work_order_images(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    images = await service.get_work_order_images(db, work_order_id)
    return success_response(
        data=[WorkOrderImageResponse.model_validate(img) for img in images]
    )


@router.get("/{work_order_id}/images/{image_id}/file", summary="查看工单图片文件")
async def serve_work_order_image(
    work_order_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    image = await repo.get_image_by_id(db, image_id)
    if not image or str(image.work_order_id) != str(work_order_id):
        raise NotFoundException("图片", str(image_id))
    if not os.path.exists(image.file_path):
        raise NotFoundException("图片文件")
    return FileResponse(image.file_path)


@router.delete("/{work_order_id}/images/{image_id}", summary="删除工单图片")
async def remove_work_order_image(
    work_order_id: uuid.UUID,
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    _require_user(current_user)
    await service.delete_work_order_image(db, image_id)
    return success_response(message="图片已删除")
