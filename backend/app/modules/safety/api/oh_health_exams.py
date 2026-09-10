"""Safety API — oh_health_exams endpoints（职业健康体检，保留 /oh-health-exams 前缀兼容）。

对齐 backend-design.md §6.1：
- 静态路径（/stats）先于 /{id}；
- 响应统一 ApiResponse（code=200 成功；业务失败 code=404/400 且 HTTP 200）；
- 全部写操作走 _audit（service 内）。
"""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    OH_AI_CONCLUSION_OPTIONS,
    OH_AI_PARSE_STATUS_OPTIONS,
    OH_EXAM_STATUS_OPTIONS,
    OH_EXAM_TYPE_OPTIONS,
    OhAiConclusion,
    OhAiParseStatus,
    OhExamStatus,
    OhExamType,
    OhFollowupResponse,
    OhHealthExamCreate,
    OhHealthExamDetail,
    OhHealthExamResponse,
    OhHealthExamUpdate,
    OhStats,
    OverrideConclusionRequest,
)
from app.modules.safety.service import OhArchiveService, OhHealthExamService
from app.modules.safety.service.oh_archive import (
    OH_UPLOAD_ALLOWED_EXTS,
    OH_UPLOAD_MAX_SIZE,
)

oh_health_exams_router = APIRouter()


@oh_health_exams_router.get(
    "/oh-health-exams", response_model=ApiResponse, summary="获取职业健康体检列表"
)
async def get_oh_health_exams(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: OhExamStatus | None = Query(None, description="机器状态"),
    exam_type: OhExamType | None = Query(None, description="体检类型"),
    department: str | None = Query(None, description="部门"),
    ai_conclusion: OhAiConclusion | None = Query(None, description="AI 结论分类"),
    ai_parse_status: OhAiParseStatus | None = Query(None, description="AI 解析状态"),
    keyword: str | None = Query(None, description="关键词（体检号/姓名/部门/身份证）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业健康体检列表，支持多条件筛选 + 分页"""
    service = OhHealthExamService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_exams(
        skip=skip,
        limit=page_size,
        status=status.value if status else None,
        exam_type=exam_type.value if exam_type else None,
        department=department,
        ai_conclusion=ai_conclusion.value if ai_conclusion else None,
        ai_parse_status=ai_parse_status.value if ai_parse_status else None,
        keyword=keyword,
    )
    return ApiResponse(
        data=[OhHealthExamResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@oh_health_exams_router.get(
    "/oh-health-exams/enums", response_model=ApiResponse, summary="获取职业健康体检枚举选项"
)
async def get_oh_health_exam_enums(
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """体检相关枚举选项（前端下拉复用）"""
    return ApiResponse(data={
        "exam_type": OH_EXAM_TYPE_OPTIONS,
        "status": OH_EXAM_STATUS_OPTIONS,
        "ai_conclusion": OH_AI_CONCLUSION_OPTIONS,
        "ai_parse_status": OH_AI_PARSE_STATUS_OPTIONS,
    })


@oh_health_exams_router.get(
    "/oh-health-exams/stats", response_model=ApiResponse, summary="职业健康体检统计"
)
async def get_oh_health_exam_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """体检统计仪表盘（total/abnormal/contraindicated/pending_parse + by_category）"""
    service = OhHealthExamService(db)
    stats = await service.get_stats()
    return ApiResponse(data=OhStats(**stats))


@oh_health_exams_router.post(
    "/oh-health-exams", response_model=ApiResponse, summary="创建职业健康体检"
)
async def create_oh_health_exam(
    data: OhHealthExamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建职业健康体检记录（联动人员汇总表 last_exam_*）"""
    service = OhHealthExamService(db)
    item = await service.create_exam(data, user_id=current_user.id if current_user else None)
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.get(
    "/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="获取职业健康体检详情"
)
async def get_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取体检详情（含 ai_parse_result + 异常随访展开）"""
    service = OhHealthExamService(db)
    item = await service.get_exam(exam_id)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    followups = await service.get_followups(exam_id)
    detail = OhHealthExamDetail.model_validate(item)
    detail.followups = [OhFollowupResponse.model_validate(f) for f in followups]
    return ApiResponse(data=detail)


@oh_health_exams_router.put(
    "/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="更新职业健康体检"
)
async def update_oh_health_exam(
    exam_id: uuid.UUID,
    data: OhHealthExamUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新职业健康体检（联动人员汇总表 last_exam_*）"""
    service = OhHealthExamService(db)
    item = await service.update_exam(exam_id, data, user_id=current_user.id if current_user else None)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.delete(
    "/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="删除职业健康体检"
)
async def delete_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除职业健康体检（软删除，清 exam_no/feishu_record_id 唯一键）"""
    service = OhHealthExamService(db)
    ok = await service.delete_exam(exam_id, user_id=current_user.id if current_user else None)
    if not ok:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@oh_health_exams_router.post(
    "/oh-health-exams/{exam_id}/parse", response_model=ApiResponse, summary="手动触发/重试 AI 解析"
)
async def parse_oh_health_exam(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发/重试体检报告 AI 解析（channel=web；主体 ticket 04 实现）"""
    service = OhHealthExamService(db)
    item = await service.run_ai_parse(exam_id, channel="web")
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.post(
    "/oh-health-exams/{exam_id}/override-conclusion",
    response_model=ApiResponse,
    summary="人工覆盖体检结论（留痕）",
)
async def override_oh_health_exam_conclusion(
    exam_id: uuid.UUID,
    data: OverrideConclusionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """人工覆盖 AI 结论（写 ai_conclusion + override_conclusion，notes 追加留痕）"""
    service = OhHealthExamService(db)
    item = await service.override_conclusion(
        exam_id,
        override_conclusion=data.override_conclusion,
        notes=data.notes,
        user_id=current_user.id if current_user else None,
        user_name=current_user.name if current_user else None,
    )
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    await db.commit()
    return ApiResponse(data=OhHealthExamResponse.model_validate(item))


@oh_health_exams_router.get(
    "/oh-health-exams/{exam_id}/followups",
    response_model=ApiResponse,
    summary="该体检的异常随访列表",
)
async def get_oh_health_exam_followups(
    exam_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """该体检的异常随访列表"""
    service = OhHealthExamService(db)
    item = await service.get_exam(exam_id)
    if not item:
        return ApiResponse(code=404, message="体检记录不存在")
    followups = await service.get_followups(exam_id)
    return ApiResponse(data=[OhFollowupResponse.model_validate(f) for f in followups])


@oh_health_exams_router.post(
    "/oh-health-exams/{exam_id}/upload-report",
    response_model=ApiResponse,
    summary="上传体检报告（L2：归档到 Bitable，AI 解析自动触发）",
)
async def upload_oh_health_exam_report(
    exam_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """L2 Web 上传体检报告（PDF/图片）归档（设计 §13.6.2 L2）。

    - 校验：体检记录存在且非软删；文件类型仅 PDF/图片；大小 ≤50MB；
    - 保存临时文件 → OhArchiveService.upload_to_exam 上传 Bitable「体检报告附件」；
    - 上传后不手动触发 AI——由镜像链路（Bitable changed → 平台下载 → AI①解析 →
      完整回填）自然触发（单一路径，设计 §13.6.2/A4）；
    - 返回附件元数据 + 「已上传，AI 解析进行中」语义。
    """
    service = OhHealthExamService(db)
    exam = await service.get_exam(exam_id)
    if not exam:
        return ApiResponse(code=404, message="体检记录不存在")

    file_name = (file.filename or "").strip() or "upload.bin"
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in OH_UPLOAD_ALLOWED_EXTS:
        return ApiResponse(
            code=400,
            message=(
                f"不支持的文件格式: {file_ext or '无扩展名'}，"
                f"仅支持 {'/'.join(sorted(OH_UPLOAD_ALLOWED_EXTS))}"
            ),
        )
    content = await file.read()
    if len(content) > OH_UPLOAD_MAX_SIZE:
        return ApiResponse(code=400, message="文件大小超过 50MB 限制")

    import time as _time

    safe_name = os.path.basename(file_name.replace("\\", "/"))
    tmp_dir = os.path.join("uploads", "safety", "oh_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"oh_{exam_id}_{int(_time.time())}_{safe_name}")
    with open(tmp_path, "wb") as f:
        f.write(content)
    try:
        archive = OhArchiveService(db)
        meta = await archive.upload_to_exam(exam_id, tmp_path, file_name)
    except ValueError as exc:
        return ApiResponse(code=404, message=str(exc))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    if meta is None:
        return ApiResponse(
            code=500,
            message="体检报告上传失败（飞书 Bitable 不可用或未配置，请稍后重试）",
        )
    return ApiResponse(data=meta, message="体检报告已上传，AI 解析进行中")
