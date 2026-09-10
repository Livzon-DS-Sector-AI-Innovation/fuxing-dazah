"""应急演练管理 API — 列表 / AI 方案生成 / 隐患追踪。"""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import ApiResponse
from app.modules.safety.schemas.emergency_drills import (
    DRILL_TYPE_OPTIONS,
    STATUS_OPTIONS,
    CollectionRecordResponse,
    DrillDocumentResponse,
    DrillRecordResponse,
    DrillStatsResponse,
)
from app.modules.safety.service.emergency_drill import EmergencyDrillService

emergency_drills_router = APIRouter()


@emergency_drills_router.get(
    "/emergency-drills/enums", response_model=ApiResponse,
    summary="获取枚举选项",
)
async def get_enums():
    return ApiResponse(data={
        "drill_types": DRILL_TYPE_OPTIONS,
        "status_options": STATUS_OPTIONS,
    })


@emergency_drills_router.get(
    "/emergency-drills", response_model=ApiResponse,
    summary="演练记录列表",
)
async def list_drill_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    department: str | None = Query(None, description="部门筛选"),
    drill_type: str | None = Query(None, description="演练类型筛选"),
    status: str | None = Query(None, description="复核状态筛选"),
    keyword: str | None = Query(None, description="关键词搜索"),
    stage: str | None = Query(None, description="环节: plan/execution/review"),
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_records(
        skip, page_size,
        department=department,
        drill_type=drill_type,
        status=status,
        keyword=keyword,
        stage=stage,
    )
    return ApiResponse(
        data=[DrillRecordResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@emergency_drills_router.get(
    "/emergency-drills/stats", response_model=ApiResponse,
    summary="统计仪表盘",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    stats = await service.get_stats()
    return ApiResponse(data=DrillStatsResponse.model_validate(stats))


# ══════════════════════════════════════════════════════
# 演练计划收录
# ══════════════════════════════════════════════════════


@emergency_drills_router.get(
    "/emergency-drills/collection", response_model=ApiResponse,
    summary="收录记录列表",
)
async def list_collection_records(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    parse_status: str | None = Query(None, description="解析状态: pending/parsed/failed"),
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    skip = (page - 1) * page_size
    items, total = await service.list_collection_records(
        skip, page_size, parse_status=parse_status,
    )
    return ApiResponse(
        data=[CollectionRecordResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@emergency_drills_router.get(
    "/emergency-drills/collection/{record_id}", response_model=ApiResponse,
    summary="收录记录详情",
)
async def get_collection_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    record = await service.get_collection_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    return ApiResponse(data=CollectionRecordResponse.model_validate(record))


@emergency_drills_router.get(
    "/emergency-drills/collection-stats", response_model=ApiResponse,
    summary="收录统计",
)
async def get_collection_stats(
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    stats = await service.get_collection_stats()
    return ApiResponse(data=stats)


@emergency_drills_router.get(
    "/emergency-drills/{record_id}", response_model=ApiResponse,
    summary="演练记录详情",
)
async def get_drill_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    record = await service.get_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    return ApiResponse(data=DrillRecordResponse.model_validate(record))


# ══════════════════════════════════════════════════════
# AI 方案生成
# ══════════════════════════════════════════════════════


@emergency_drills_router.post(
    "/emergency-drills/{record_id}/generate-plan",
    response_model=ApiResponse,
    summary="AI 生成演练方案",
)
async def generate_drill_plan(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """基于计划阶段字段（关键词），RAG + DeepSeek 生成标准化演练方案。"""
    service = EmergencyDrillService(db)
    record = await service.get_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    try:
        doc = await service.generate_drill_plan(record_id)
        if doc is None:
            return ApiResponse(code=500, message="方案生成失败", data=None)
        return ApiResponse(
            data=DrillDocumentResponse.model_validate(doc),
            message="方案生成成功",
        )
    except Exception as e:
        return ApiResponse(code=500, message=f"方案生成失败: {e}", data=None)


@emergency_drills_router.get(
    "/emergency-drills/{record_id}/documents",
    response_model=ApiResponse,
    summary="获取 AI 生成的方案文档",
)
async def get_documents(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    docs = await service.get_documents(record_id)
    return ApiResponse(data=[DrillDocumentResponse.model_validate(d) for d in docs])


# ══════════════════════════════════════════════════════
# 隐患追踪
# ══════════════════════════════════════════════════════


@emergency_drills_router.post(
    "/emergency-drills/{record_id}/create-hazards",
    response_model=ApiResponse,
    summary="演练问题 → 隐患记录",
)
async def create_hazards(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """将演练问题拆分为隐患记录并建立追踪关联。"""
    service = EmergencyDrillService(db)
    record = await service.get_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    if not record.issues or not record.issues.strip():
        return ApiResponse(code=400, message="演练问题为空", data=None)
    try:
        created = await service.create_hazards_from_issues(record_id)
        return ApiResponse(data=created, message=f"已创建 {len(created)} 条隐患记录")
    except Exception as e:
        return ApiResponse(code=500, message=f"创建隐患失败: {e}", data=None)


@emergency_drills_router.post(
    "/emergency-drills/{record_id}/generate-eval",
    response_model=ApiResponse,
    summary="AI 生成演练评估表",
)
async def generate_drill_eval(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """基于演练记录表 AI 生成评估表 docx，回写「演练评估表（AI）」并回填复核字段。"""
    service = EmergencyDrillService(db)
    record = await service.get_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    if not record.drill_record_file:
        return ApiResponse(code=400, message="请先上传演练记录表", data=None)
    try:
        from app.modules.safety.service.drill_eval import generate_eval_form

        doc = await generate_eval_form(db, record_id, source="manual")
        if doc is None:
            return ApiResponse(code=500, message="评估表生成失败", data=None)
        return ApiResponse(
            data=DrillDocumentResponse.model_validate(doc),
            message="评估表生成成功",
        )
    except Exception as e:
        return ApiResponse(code=500, message=f"评估表生成失败: {e}", data=None)


@emergency_drills_router.get(
    "/emergency-drills/{record_id}/hazards",
    response_model=ApiResponse,
    summary="查询关联隐患",
)
async def get_hazards(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    hazards = await service.get_hazard_links(record_id)
    return ApiResponse(data=hazards)


@emergency_drills_router.post(
    "/emergency-drills/{record_id}/check-complete",
    response_model=ApiResponse,
    summary="检查并自动完成",
)
async def check_complete(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """检查关联隐患是否全部关闭，是则自动将状态标记为已完成。"""
    service = EmergencyDrillService(db)
    completed = await service.check_and_complete(record_id)
    return ApiResponse(
        data={"completed": completed},
        message="已标记为已完成" if completed else "尚有隐患未关闭",
    )
