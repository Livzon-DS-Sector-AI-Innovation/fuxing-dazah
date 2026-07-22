"""Safety API — oh_health_exams endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    OhHealthExamCreate,
    OhHealthExamResponse,
    OhHealthExamUpdate,
    SetExamConclusionRequest,
)
from app.modules.safety.service import (
    OhHealthExamService,
)

oh_health_exams_router = APIRouter()


@oh_health_exams_router.get("/oh-health-exams", response_model=ApiResponse, summary="获取职业健康体检列表")
async def get_oh_health_exams(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    exam_type: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业健康体检列表，支持多条件筛选"""
    service = OhHealthExamService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_exams(
        skip, page_size, status, exam_type, department, keyword
    )
    return ApiResponse(
        data=[OhHealthExamResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_health_exams_router.post("/oh-health-exams", response_model=ApiResponse, summary="创建职业健康体检")
async def create_oh_health_exam(
    data: OhHealthExamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建职业健康体检记录"""
    service = OhHealthExamService(db)
    item = await service.create_exam(data)
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.get("/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="获取职业健康体检详情")
async def get_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业健康体检详情"""
    service = OhHealthExamService(db)
    item = await service.get_exam(exam_id)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.put("/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="更新职业健康体检")
async def update_oh_health_exam(
    exam_id: uuid.UUID,
    data: OhHealthExamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新职业健康体检"""
    service = OhHealthExamService(db)
    item = await service.update_exam(exam_id, data)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.delete("/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="删除职业健康体检")
async def delete_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除职业健康体检（软删除）"""
    service = OhHealthExamService(db)
    ok = await service.delete_exam(exam_id)
    if not ok:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── Exam Workflow ──


@oh_health_exams_router.post("/oh-health-exams/{exam_id}/start", response_model=ApiResponse, summary="开始体检")
async def start_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始体检（已安排→体检中）"""
    service = OhHealthExamService(db)
    item = await service.start_exam(exam_id)
    if not item:
        return ApiResponse(code=400, message="无法开始体检，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.post("/oh-health-exams/{exam_id}/complete", response_model=ApiResponse, summary="完成体检")
async def complete_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成体检（体检中→已完成）"""
    service = OhHealthExamService(db)
    item = await service.complete_exam(exam_id)
    if not item:
        return ApiResponse(code=400, message="无法完成体检，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.post("/oh-health-exams/{exam_id}/archive", response_model=ApiResponse, summary="归档体检")
async def archive_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """归档体检（已完成→已归档）"""
    service = OhHealthExamService(db)
    item = await service.archive_exam(exam_id)
    if not item:
        return ApiResponse(code=400, message="无法归档，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


# ── Exam JSON Sub-records ──


@oh_health_exams_router.post("/oh-health-exams/{exam_id}/exam-items", response_model=ApiResponse, summary="添加体检项目")
async def add_exam_item(
    exam_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加体检项目到体检记录"""
    service = OhHealthExamService(db)
    item = await service.add_exam_item(exam_id, data)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.put("/oh-health-exams/{exam_id}/exam-items/{index}", response_model=ApiResponse, summary="更新体检项目")
async def update_exam_item(
    exam_id: uuid.UUID,
    index: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新指定索引的体检项目"""
    service = OhHealthExamService(db)
    item = await service.update_exam_item(exam_id, index, data)
    if not item:
        return ApiResponse(code=400, message="无法更新，体检记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.delete("/oh-health-exams/{exam_id}/exam-items/{index}", response_model=ApiResponse, summary="删除体检项目")
async def delete_exam_item(
    exam_id: uuid.UUID,
    index: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除指定索引的体检项目"""
    service = OhHealthExamService(db)
    item = await service.remove_exam_item(exam_id, index)
    if not item:
        return ApiResponse(code=400, message="无法删除，体检记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.put("/oh-health-exams/{exam_id}/conclusion", response_model=ApiResponse, summary="设置体检结论")
async def set_exam_conclusion(
    exam_id: uuid.UUID,
    data: SetExamConclusionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """设置体检结论（异常结论自动创建处置记录）"""
    service = OhHealthExamService(db)
    item = await service.set_conclusion(exam_id, data.conclusion, data.remarks)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.post("/oh-health-exams/{exam_id}/abnormality-records", response_model=ApiResponse, summary="添加体检异常处置记录")
async def add_exam_abnormality_record(
    exam_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加异常处置记录到体检"""
    service = OhHealthExamService(db)
    item = await service.add_abnormality_record(exam_id, data)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.put("/oh-health-exams/{exam_id}/abnormality-records/{index}", response_model=ApiResponse, summary="更新体检异常处置状态")
async def update_exam_abnormality_status(
    exam_id: uuid.UUID,
    index: int,
    status: str = Query(..., description="状态: open/investigating/corrected/closed"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新体检异常处置记录状态"""
    service = OhHealthExamService(db)
    item = await service.update_abnormality_record_status(exam_id, index, status)
    if not item:
        return ApiResponse(code=400, message="无法更新，体检记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


