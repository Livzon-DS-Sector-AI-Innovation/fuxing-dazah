"""应急演练管理 API — 列表 / AI 方案生成 / 隐患追踪。

直读模式（SAFETY_EMERGENCY_DRILL_DIRECT_ENABLED）：主表列表/统计/详情走 Bitable
直读，meta 带 mode=direct + elapsed_ms；详情与写/关联端点 id 参数接受 UUID|recXXX
双态（contractor_admission 同款）。采集表三端点维持平台 PG（spec D2：解析态只在
平台库）。事件链路（归集+评估 AI 触发）不受本开关影响。
"""

import time
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
from app.modules.safety.service.emergency_drill import (
    EmergencyDrillService,
    _parse_uuid,
)

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
    from app.modules.safety.service.emergency_drill_direct import (
        config as direct_config,
    )

    direct = direct_config.direct_enabled()
    t0 = time.perf_counter()
    items, total = await service.list_records(
        skip, page_size,
        department=department,
        drill_type=drill_type,
        status=status,
        keyword=keyword,
        stage=stage,
    )
    meta: dict = {"page": page, "page_size": page_size, "total": total}
    if direct:
        meta["mode"] = "direct"
        meta["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return ApiResponse(
        data=[DrillRecordResponse.model_validate(r) for r in items],
        meta=meta,
    )


@emergency_drills_router.get(
    "/emergency-drills/stats", response_model=ApiResponse,
    summary="统计仪表盘",
)
async def get_stats(
    db: AsyncSession = Depends(get_db),
):
    service = EmergencyDrillService(db)
    from app.modules.safety.service.emergency_drill_direct import (
        config as direct_config,
    )

    direct = direct_config.direct_enabled()
    t0 = time.perf_counter()
    stats = await service.get_stats()
    meta: dict | None = None
    if direct:
        meta = {"mode": "direct", "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    return ApiResponse(data=DrillStatsResponse.model_validate(stats), meta=meta)


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
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """id 双态：UUID（旧链接）或 recXXX（直读），contractor_admission 同款。"""
    service = EmergencyDrillService(db)
    record = await service.resolve_record(record_id)
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
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """基于计划阶段字段（关键词），RAG + DeepSeek 生成标准化演练方案。"""
    service = EmergencyDrillService(db)
    record = await service.resolve_pg_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    try:
        doc = await service.generate_drill_plan(record.id)
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
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """id 双态。UUID 直用（未知 id 维持既有 200 空列表行为）；recXXX 解析回平台行。"""
    service = EmergencyDrillService(db)
    rid = _parse_uuid(record_id)
    if rid is None:
        record = await service.resolve_pg_record(record_id)
        if record is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        rid = record.id
    docs = await service.get_documents(rid)
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
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """将演练问题拆分为隐患记录并建立追踪关联。"""
    service = EmergencyDrillService(db)
    record = await service.resolve_pg_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    if not record.issues or not record.issues.strip():
        return ApiResponse(code=400, message="演练问题为空", data=None)
    try:
        created = await service.create_hazards_from_issues(record.id)
        return ApiResponse(data=created, message=f"已创建 {len(created)} 条隐患记录")
    except Exception as e:
        return ApiResponse(code=500, message=f"创建隐患失败: {e}", data=None)


@emergency_drills_router.post(
    "/emergency-drills/{record_id}/generate-eval",
    response_model=ApiResponse,
    summary="AI 生成演练评估表",
)
async def generate_drill_eval(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """基于演练记录表 AI 生成评估表 docx，回写「演练评估表（AI）」并回填复核字段。"""
    service = EmergencyDrillService(db)
    record = await service.resolve_pg_record(record_id)
    if record is None:
        return ApiResponse(code=404, message="记录不存在", data=None)
    if not record.drill_record_file:
        return ApiResponse(code=400, message="请先上传演练记录表", data=None)
    try:
        from app.modules.safety.service.drill_eval import generate_eval_form

        doc = await generate_eval_form(db, record.id, source="manual")
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
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """id 双态。UUID 直用（未知 id 维持既有 200 空列表行为）；recXXX 解析回平台行。"""
    service = EmergencyDrillService(db)
    rid = _parse_uuid(record_id)
    if rid is None:
        record = await service.resolve_pg_record(record_id)
        if record is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        rid = record.id
    hazards = await service.get_hazard_links(rid)
    return ApiResponse(data=hazards)


@emergency_drills_router.post(
    "/emergency-drills/{record_id}/check-complete",
    response_model=ApiResponse,
    summary="检查并自动完成",
)
async def check_complete(
    record_id: str,
    db: AsyncSession = Depends(get_db),
):
    """检查关联隐患是否全部关闭，是则自动将状态标记为已完成。"""
    service = EmergencyDrillService(db)
    rid = _parse_uuid(record_id)
    if rid is None:
        record = await service.resolve_pg_record(record_id)
        if record is None:
            return ApiResponse(code=404, message="记录不存在", data=None)
        rid = record.id
    completed = await service.check_and_complete(rid)
    return ApiResponse(
        data={"completed": completed},
        message="已标记为已完成" if completed else "尚有隐患未关闭",
    )
