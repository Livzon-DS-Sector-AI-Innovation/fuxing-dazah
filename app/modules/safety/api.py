"""Safety API routes — AI vision model support."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.schemas import (
    AccidentCreate,
    AccidentResponse,
    AccidentUpdate,
    AIWorkflowConfigCreate,
    AIWorkflowConfigResponse,
    AIWorkflowConfigUpdate,
    APICallConfigCreate,
    APICallConfigResponse,
    APICallConfigUpdate,
    ApproveEhsChangeRequest,
    CloseEhsChangeRequest,
    CompleteRectificationRequest,
    ConfirmCheckRequest,
    ContractorCreate,
    ContractorResponse,
    ContractorUpdate,
    ContractorWorkRecordCreate,
    ContractorWorkRecordResponse,
    ContractorWorkRecordUpdate,
    DailyRiskReportCreate,
    DailyRiskReportResponse,
    DailyRiskReportUpdate,
    EhsChangeCreate,
    EhsChangeResponse,
    EhsChangeUpdate,
    EvaluateWorkRecordRequest,
    ExtendDeadlineRequest,
    HazardIdentificationCreate,
    HazardIdentificationResponse,
    HazardIdentificationReview,
    HazardIdentificationRunScript,
    HazardIdentificationUpdate,
    HazardLedgerExportRequest,
    HazardReportCreate,
    HazardReportResponse,
    HazardReportRunAIRequest,
    HazardReportUpdate,
    HazardRiskOption,
    LedgerExportRequest,
    OhHazardMonitorCreate,
    OhHazardMonitorResponse,
    OhHazardMonitorUpdate,
    OhHealthExamCreate,
    OhHealthExamResponse,
    OhHealthExamUpdate,
    OperationRegulationCreate,
    OperationRegulationResponse,
    OperationRegulationUpdate,
    RectificationReplyRequest,
    RegulationRevisionCreate,
    RegulationRevisionResponse,
    RegulationRevisionUpdate,
    SafetyCheckCreate,
    SafetyCheckResponse,
    SafetyCheckUpdate,
    SafetyKnowledgeArticleCreate,
    SafetyKnowledgeArticleResponse,
    SafetyKnowledgeArticleUpdate,
    SafetyTrainingCreate,
    SafetyTrainingResponse,
    SafetyTrainingUpdate,
    SetCriticalRequest,
    SetExamConclusionRequest,
    SpecialOperationLedgerStats,
    SpecialOperationPermitCreate,
    SpecialOperationPermitResponse,
    SpecialOperationPermitUpdate,
    SpecialOperationPersonnelCreate,
    SpecialOperationPersonnelResponse,
    SpecialOperationPersonnelUpdate,
    SpecialOperationReportCreate,
    SpecialOperationReportResponse,
    SpecialOperationReportUpdate,
    TrainingRecordCreate,
    TrainingRecordResponse,
    TrainingRecordUpdate,
    VerifyLevelRequest,
    VerifyMonitorRequest,
)
from app.modules.safety.service import (
    ConfigService,
    DailyRiskReportService,
    EhsChangeService,
    KnowledgeService,
    OhHazardMonitorService,
    OhHealthExamService,
    RegulationService,
    SafetyService,
    SpecialOperationReportService,
    SpecialOperationService,
)

router = APIRouter()


# ==================== 安全检查 Routes ====================


@router.get("/checks", response_model=ApiResponse, summary="获取安全检查列表")
async def get_checks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    check_type: str | None = None,
    department: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全检查列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_checks(skip, page_size, status, check_type, department)
    return ApiResponse(
        data=[SafetyCheckResponse.model_validate(c) for c in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/checks/{check_id}", response_model=ApiResponse, summary="获取安全检查详情")
async def get_check(
    check_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全检查详情"""
    service = SafetyService(db)
    item = await service.get_check(check_id)
    if not item:
        return ApiResponse(code=404, message="检查记录不存在")
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@router.post("/checks", response_model=ApiResponse, summary="创建安全检查")
async def create_check(
    data: SafetyCheckCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全检查"""
    service = SafetyService(db)
    item = await service.create_check(data)
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@router.put("/checks/{check_id}", response_model=ApiResponse, summary="更新安全检查")
async def update_check(
    check_id: uuid.UUID,
    data: SafetyCheckUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全检查"""
    service = SafetyService(db)
    item = await service.update_check(check_id, data)
    if not item:
        return ApiResponse(code=404, message="检查记录不存在")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@router.post("/checks/{check_id}/submit", response_model=ApiResponse, summary="提交安全检查")
async def submit_check(
    check_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交安全检查（草稿→已提交）"""
    service = SafetyService(db)
    item = await service.submit_check(check_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@router.post("/checks/{check_id}/review", response_model=ApiResponse, summary="审核安全检查")
async def review_check(
    check_id: uuid.UUID,
    result: str = Query(..., description="审核结果: qualified/unqualified"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审核安全检查"""
    service = SafetyService(db)
    item = await service.review_check(check_id, result)
    if not item:
        return ApiResponse(code=400, message="无法审核，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@router.post("/checks/{check_id}/confirm", response_model=ApiResponse, summary="确认检查")
async def confirm_check(
    check_id: uuid.UUID,
    data: ConfirmCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """确认安全检查（role=inspector 检查人员确认 / role=safety_officer 安全办确认）"""
    service = SafetyService(db)
    item = await service.confirm_check(check_id, data.role)
    if not item:
        return ApiResponse(code=400, message="确认失败")
    await db.commit()
    return ApiResponse(data=SafetyCheckResponse.model_validate(item))


@router.delete("/checks/{check_id}", response_model=ApiResponse, summary="删除安全检查")
async def delete_check(
    check_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全检查"""
    service = SafetyService(db)
    result = await service.delete_check(check_id)
    if not result:
        return ApiResponse(code=404, message="检查记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 隐患排查 Routes ====================


@router.get("/hazards", response_model=ApiResponse, summary="获取隐患列表")
async def get_hazards(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    hazard_type: str | None = None,
    hazard_level: str | None = None,
    hazard_category: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取隐患列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_hazards(
        skip, page_size, status, hazard_type, hazard_level, hazard_category, department, keyword
    )
    return ApiResponse(
        data=[HazardReportResponse.model_validate(h) for h in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/hazards/{hazard_id}", response_model=ApiResponse, summary="获取隐患详情")
async def get_hazard(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取隐患详情"""
    service = SafetyService(db)
    item = await service.get_hazard(hazard_id)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post("/hazards", response_model=ApiResponse, summary="创建隐患")
async def create_hazard(
    data: HazardReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建隐患"""
    service = SafetyService(db)
    item = await service.create_hazard(data)
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.put("/hazards/{hazard_id}", response_model=ApiResponse, summary="更新隐患")
async def update_hazard(
    hazard_id: uuid.UUID,
    data: HazardReportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新隐患"""
    service = SafetyService(db)
    item = await service.update_hazard(hazard_id, data)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/upload-photo",
    response_model=ApiResponse,
    summary="上传隐患图片",
)
async def upload_hazard_photo(
    hazard_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传隐患缺陷图片，追加到 defect_photos JSON 数组"""
    import os

    upload_dir = os.path.join("uploads", "safety", "hazard")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or ".png")[1]
    safe_name = f"hazard_{hazard_id}_{int(datetime.now().timestamp())}{file_ext}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    service = SafetyService(db)
    item = await service.upload_hazard_photo(hazard_id, file.filename or "unknown", file_path)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/upload-rectification-photo",
    response_model=ApiResponse,
    summary="上传整改图片",
)
async def upload_rectification_photo(
    hazard_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传整改后图片，追加到 rectification_photos JSON 数组"""
    import os

    upload_dir = os.path.join("uploads", "safety", "hazard")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or ".png")[1]
    safe_name = f"rectification_{hazard_id}_{int(datetime.now().timestamp())}{file_ext}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    service = SafetyService(db)
    item = await service.upload_rectification_photo(hazard_id, file_path)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/rectification/start",
    response_model=ApiResponse,
    summary="开始整改",
)
async def start_rectification(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始整改"""
    service = SafetyService(db)
    item = await service.start_rectification(hazard_id)
    if not item:
        return ApiResponse(code=400, message="无法开始整改，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/rectification/complete",
    response_model=ApiResponse,
    summary="完成整改",
)
async def complete_rectification(
    hazard_id: uuid.UUID,
    data: CompleteRectificationRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成整改（可选填写实际完成时间、整改后图片、纠正预防措施）"""
    service = SafetyService(db)
    item = await service.complete_rectification(
        hazard_id,
        actual_completion_date=data.actual_completion_date if data else None,
        rectification_photos=data.rectification_photos if data else None,
        corrective_preventive_measures=data.corrective_preventive_measures if data else None,
    )
    if not item:
        return ApiResponse(code=400, message="无法完成整改，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/extend",
    response_model=ApiResponse,
    summary="延期整改",
)
async def extend_deadline(
    hazard_id: uuid.UUID,
    data: ExtendDeadlineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """申请延期整改"""
    service = SafetyService(db)
    item = await service.extend_deadline(hazard_id, data.extended_deadline)
    if not item:
        return ApiResponse(code=400, message="无法延期，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/rectification/reply",
    response_model=ApiResponse,
    summary="整改回复",
)
async def reply_rectification(
    hazard_id: uuid.UUID,
    data: RectificationReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """责任人提交整改回复，rectification_status: in_progress → replied"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.reply_rectification(
        hazard_id,
        reply_content=data.reply_content,
        rectification_photos=data.rectification_photos,
        user_id=user_id,
        user_name=user_name,
    )
    if not item:
        return ApiResponse(code=400, message="无法回复，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/rectification/verify-level",
    response_model=ApiResponse,
    summary="三级复核",
)
async def verify_level(
    hazard_id: uuid.UUID,
    data: VerifyLevelRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """三级复核确认：1=一级(部门负责人), 2=二级(分管领导), 3=三级(隐患发现人)"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.verify_level(
        hazard_id,
        level=data.level,
        action=data.action,
        opinion=data.opinion,
        user_id=user_id,
        user_name=user_name,
    )
    if not item:
        return ApiResponse(code=400, message="无法复核，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/rectification/rework",
    response_model=ApiResponse,
    summary="重新整改",
)
async def rework_rectification(
    hazard_id: uuid.UUID,
    data: RectificationReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """复核驳回后重新整改，rejected → replied，重置所有复核级别"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.rework_rectification(
        hazard_id,
        reply_content=data.reply_content,
        rectification_photos=data.rectification_photos,
        user_id=user_id,
        user_name=user_name,
    )
    if not item:
        return ApiResponse(code=400, message="无法重新整改，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.delete("/hazards/{hazard_id}", response_model=ApiResponse, summary="删除隐患")
async def delete_hazard(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除隐患"""
    service = SafetyService(db)
    result = await service.delete_hazard(hazard_id)
    if not result:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post(
    "/hazards/{hazard_id}/ai/run/{script_number}",
    response_model=ApiResponse,
    summary="执行隐患AI工作流",
)
async def run_hazard_ai(
    hazard_id: uuid.UUID,
    script_number: int,
    data: HazardReportRunAIRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """执行隐患AI工作流脚本。AI从已有数据库数据读取上下文，无需额外传入参数。"""
    service = SafetyService(db)
    item = await service.run_hazard_ai_script(hazard_id, script_number)
    if item is None:
        return ApiResponse(code=400, message="无法执行AI工作流，当前状态不允许或前置步骤未完成")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@router.post(
    "/hazards/{hazard_id}/ai/review/{script_number}",
    response_model=ApiResponse,
    summary="审核隐患AI输出",
)
async def review_hazard_ai(
    hazard_id: uuid.UUID,
    script_number: int,
    action: str = Query(..., description="审核动作：approved(通过) 或 rejected(驳回)"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审核隐患AI工作流输出（通过/驳回）。"""
    if action not in ("approved", "rejected"):
        return ApiResponse(code=400, message="action 参数必须是 approved 或 rejected")
    service = SafetyService(db)
    item = await service.review_hazard_ai_script(hazard_id, script_number, action)
    if item is None:
        return ApiResponse(code=400, message="无法审核，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


# ==================== 事故管理 Routes ====================


@router.get("/accidents", response_model=ApiResponse, summary="获取事故列表")
async def get_accidents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    accident_type: str | None = None,
    accident_level: str | None = None,
    department: str | None = Query(None, description="部门"),
    date_from: str | None = Query(None, description="发生时间起 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="发生时间止 (YYYY-MM-DD)"),
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取事故列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_accidents(
        skip, page_size, status, accident_type, accident_level,
        department,
        dt.fromisoformat(date_from) if date_from else None,
        dt.fromisoformat(date_to) if date_to else None,
        keyword,
    )
    return ApiResponse(
        data=[AccidentResponse.model_validate(a) for a in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/accidents/{accident_id}", response_model=ApiResponse, summary="获取事故详情")
async def get_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取事故详情"""
    service = SafetyService(db)
    item = await service.get_accident(accident_id)
    if not item:
        return ApiResponse(code=404, message="事故不存在")
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.post("/accidents", response_model=ApiResponse, summary="创建事故")
async def create_accident(
    data: AccidentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建事故"""
    service = SafetyService(db)
    item = await service.create_accident(data)
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.put("/accidents/{accident_id}", response_model=ApiResponse, summary="更新事故")
async def update_accident(
    accident_id: uuid.UUID,
    data: AccidentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新事故"""
    service = SafetyService(db)
    item = await service.update_accident(accident_id, data)
    if not item:
        return ApiResponse(code=404, message="事故不存在")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.post(
    "/accidents/{accident_id}/investigate",
    response_model=ApiResponse,
    summary="开始调查事故",
)
async def investigate_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始调查事故"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.investigate_accident(accident_id, user_id, user_name)
    if not item:
        return ApiResponse(code=400, message="无法开始调查，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.post(
    "/accidents/{accident_id}/resolve",
    response_model=ApiResponse,
    summary="完成调查事故",
)
async def resolve_accident(
    accident_id: uuid.UUID,
    direct_cause: str = Query(..., description="直接原因"),
    root_cause: str = Query(..., description="根本原因"),
    handling_measures: str = Query(..., description="处理措施"),
    corrective_actions: str | None = Query(None, description="纠正预防措施"),
    investigation_findings: str | None = Query(None, description="调查发现"),
    investigation_method: str | None = Query(None, description="调查方法"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成调查事故"""
    service = SafetyService(db)
    item = await service.resolve_accident(
        accident_id, direct_cause, root_cause, handling_measures, corrective_actions,
        investigation_findings, investigation_method,
    )
    if not item:
        return ApiResponse(code=400, message="无法完成调查，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.post(
    "/accidents/{accident_id}/start-capa",
    response_model=ApiResponse,
    summary="启动CAPA",
)
async def start_capa(
    accident_id: uuid.UUID,
    corrective_action_deadline: str = Query(..., description="CAPA截止日期 (YYYY-MM-DD)"),
    corrective_action_responsible: str = Query(..., description="CAPA责任人"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """启动CAPA: investigated → capa_in_progress"""
    service = SafetyService(db)
    item = await service.start_capa(
        accident_id,
        dt.fromisoformat(corrective_action_deadline),
        corrective_action_responsible,
    )
    if not item:
        return ApiResponse(code=400, message="无法启动CAPA，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.post(
    "/accidents/{accident_id}/verify-capa",
    response_model=ApiResponse,
    summary="验证CAPA并关闭事故",
)
async def verify_capa(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """验证CAPA并关闭事故: capa_in_progress → closed"""
    service = SafetyService(db)
    user_id = current_user.id if current_user else None
    user_name = current_user.name if current_user else None
    item = await service.verify_capa(accident_id, user_id, user_name)
    if not item:
        return ApiResponse(code=400, message="无法验证CAPA，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.post(
    "/accidents/{accident_id}/close",
    response_model=ApiResponse,
    summary="直接关闭事故",
)
async def close_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """直接关闭事故（无CAPA时）"""
    service = SafetyService(db)
    item = await service.close_accident(accident_id)
    if not item:
        return ApiResponse(code=400, message="无法关闭，当前状态不允许")
    await db.commit()
    return ApiResponse(data=AccidentResponse.model_validate(item))


@router.delete("/accidents/{accident_id}", response_model=ApiResponse, summary="删除事故")
async def delete_accident(
    accident_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除事故"""
    service = SafetyService(db)
    result = await service.delete_accident(accident_id)
    if not result:
        return ApiResponse(code=404, message="事故不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 承包商管理 Routes ====================


@router.get("/contractors", response_model=ApiResponse, summary="获取承包商列表")
async def get_contractors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    qualification_type: str | None = None,
    training_status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取承包商列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_contractors(
        skip, page_size, status, qualification_type, training_status, keyword,
    )
    return ApiResponse(
        data=[ContractorResponse.model_validate(c) for c in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/contractors/{contractor_id}", response_model=ApiResponse, summary="获取承包商详情")
async def get_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取承包商详情（含施工记录）"""
    service = SafetyService(db)
    item = await service.get_contractor(contractor_id)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    return ApiResponse(data=ContractorResponse.model_validate(item))


@router.post("/contractors", response_model=ApiResponse, summary="创建承包商")
async def create_contractor(
    data: ContractorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建承包商"""
    service = SafetyService(db)
    item = await service.create_contractor(data)
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@router.put("/contractors/{contractor_id}", response_model=ApiResponse, summary="更新承包商")
async def update_contractor(
    contractor_id: uuid.UUID,
    data: ContractorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新承包商"""
    service = SafetyService(db)
    item = await service.update_contractor(contractor_id, data)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@router.delete("/contractors/{contractor_id}", response_model=ApiResponse, summary="删除承包商")
async def delete_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除承包商（软删除）"""
    service = SafetyService(db)
    result = await service.delete_contractor(contractor_id)
    if not result:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post("/contractors/{contractor_id}/blacklist", response_model=ApiResponse, summary="加入黑名单")
async def blacklist_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """将承包商加入黑名单"""
    service = SafetyService(db)
    item = await service.blacklist_contractor(contractor_id)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@router.post("/contractors/{contractor_id}/activate", response_model=ApiResponse, summary="激活承包商")
async def activate_contractor(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """激活承包商（从停用或黑名单恢复）"""
    service = SafetyService(db)
    item = await service.activate_contractor(contractor_id)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


@router.post(
    "/contractors/{contractor_id}/update-training",
    response_model=ApiResponse,
    summary="更新培训状态",
)
async def update_contractor_training(
    contractor_id: uuid.UUID,
    training_status: str = Query(..., description="培训状态: untrained/in_progress/passed/expired"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新承包商培训状态"""
    service = SafetyService(db)
    item = await service.update_contractor_training(contractor_id, training_status)
    if not item:
        return ApiResponse(code=404, message="承包商不存在")
    await db.commit()
    return ApiResponse(data=ContractorResponse.model_validate(item))


# ── 施工记录子表 ──


@router.get(
    "/contractors/{contractor_id}/work-records",
    response_model=ApiResponse,
    summary="获取承包商施工记录",
)
async def get_work_records(
    contractor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取承包商的施工记录列表"""
    service = SafetyService(db)
    items = await service.get_work_records(contractor_id)
    return ApiResponse(data=[ContractorWorkRecordResponse.model_validate(r) for r in items])


@router.post(
    "/contractors/{contractor_id}/work-records",
    response_model=ApiResponse,
    summary="创建施工记录",
)
async def create_work_record(
    contractor_id: uuid.UUID,
    data: ContractorWorkRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建承包商的施工记录"""
    service = SafetyService(db)
    item = await service.create_work_record(contractor_id, data)
    await db.commit()
    return ApiResponse(data=ContractorWorkRecordResponse.model_validate(item))


@router.put(
    "/contractors/{contractor_id}/work-records/{record_id}",
    response_model=ApiResponse,
    summary="更新施工记录",
)
async def update_work_record(
    contractor_id: uuid.UUID,
    record_id: uuid.UUID,
    data: ContractorWorkRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新施工记录"""
    service = SafetyService(db)
    item = await service.update_work_record(record_id, data)
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=ContractorWorkRecordResponse.model_validate(item))


@router.delete(
    "/contractors/{contractor_id}/work-records/{record_id}",
    response_model=ApiResponse,
    summary="删除施工记录",
)
async def delete_work_record(
    contractor_id: uuid.UUID,
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除施工记录（软删除）"""
    service = SafetyService(db)
    result = await service.delete_work_record(record_id)
    if not result:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post(
    "/contractors/{contractor_id}/work-records/{record_id}/evaluate",
    response_model=ApiResponse,
    summary="评价施工记录",
)
async def evaluate_work_record(
    contractor_id: uuid.UUID,
    record_id: uuid.UUID,
    data: EvaluateWorkRecordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """评价施工记录"""
    service = SafetyService(db)
    item = await service.evaluate_work_record(
        record_id, data.score, data.comments, data.evaluator,
    )
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=ContractorWorkRecordResponse.model_validate(item))


# ==================== 安全培训 Routes ====================


@router.get("/trainings", response_model=ApiResponse, summary="获取安全培训列表")
async def get_trainings(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    training_type: str | None = None,
    department: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全培训列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_trainings(skip, page_size, status, training_type, department)
    return ApiResponse(
        data=[SafetyTrainingResponse.model_validate(t) for t in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/trainings/{training_id}", response_model=ApiResponse, summary="获取安全培训详情")
async def get_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全培训详情"""
    service = SafetyService(db)
    item = await service.get_training(training_id)
    if not item:
        return ApiResponse(code=404, message="培训不存在")
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@router.post("/trainings", response_model=ApiResponse, summary="创建安全培训")
async def create_training(
    data: SafetyTrainingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全培训"""
    service = SafetyService(db)
    item = await service.create_training(data)
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@router.put("/trainings/{training_id}", response_model=ApiResponse, summary="更新安全培训")
async def update_training(
    training_id: uuid.UUID,
    data: SafetyTrainingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全培训"""
    service = SafetyService(db)
    item = await service.update_training(training_id, data)
    if not item:
        return ApiResponse(code=404, message="培训不存在")
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@router.post("/trainings/{training_id}/start", response_model=ApiResponse, summary="开始培训")
async def start_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始培训（草稿→进行中）"""
    service = SafetyService(db)
    item = await service.start_training(training_id)
    if not item:
        return ApiResponse(code=400, message="无法开始培训，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@router.post("/trainings/{training_id}/complete", response_model=ApiResponse, summary="完成培训")
async def complete_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成培训"""
    service = SafetyService(db)
    item = await service.complete_training(training_id)
    if not item:
        return ApiResponse(code=400, message="无法完成培训，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyTrainingResponse.model_validate(item))


@router.delete("/trainings/{training_id}", response_model=ApiResponse, summary="删除安全培训")
async def delete_training(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全培训"""
    service = SafetyService(db)
    result = await service.delete_training(training_id)
    if not result:
        return ApiResponse(code=404, message="培训不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 培训记录 Routes ====================


@router.get(
    "/trainings/{training_id}/records",
    response_model=ApiResponse,
    summary="获取培训签到记录列表",
)
async def get_training_records(
    training_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取培训签到记录列表"""
    service = SafetyService(db)
    items = await service.get_training_records(training_id)
    return ApiResponse(data=[TrainingRecordResponse.model_validate(r) for r in items])


@router.post(
    "/trainings/{training_id}/records",
    response_model=ApiResponse,
    summary="添加培训签到记录",
)
async def create_training_record(
    training_id: uuid.UUID,
    data: TrainingRecordCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """添加培训签到记录"""
    service = SafetyService(db)
    data.training_id = training_id
    item = await service.create_training_record(data)
    await db.commit()
    return ApiResponse(data=TrainingRecordResponse.model_validate(item))


@router.put(
    "/training-records/{record_id}",
    response_model=ApiResponse,
    summary="更新培训签到记录",
)
async def update_training_record(
    record_id: uuid.UUID,
    data: TrainingRecordUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新培训签到记录"""
    service = SafetyService(db)
    item = await service.update_training_record(record_id, data)
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=TrainingRecordResponse.model_validate(item))


@router.delete(
    "/training-records/{record_id}",
    response_model=ApiResponse,
    summary="删除培训签到记录",
)
async def delete_training_record(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除培训签到记录"""
    service = SafetyService(db)
    result = await service.delete_training_record(record_id)
    if not result:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 培训证书接口 ====================


@router.get("/training-certificates", response_model=ApiResponse, summary="获取证书列表")
async def get_training_certificates(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    certificate_status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取所有培训证书列表（含即将到期/已过期筛选）"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_training_certificates(
        skip, page_size, certificate_status, keyword,
    )
    return ApiResponse(
        data=[TrainingRecordResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get("/training-certificates/expiring", response_model=ApiResponse, summary="获取即将到期证书")
async def get_expiring_certificates(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取30天内即将到期的证书"""
    service = SafetyService(db)
    items = await service.get_expiring_certificates()
    return ApiResponse(data=[TrainingRecordResponse.model_validate(r) for r in items])


# ==================== 枚举数据接口 ====================


@router.get("/enums", response_model=ApiResponse, summary="获取枚举值列表")
async def get_enums(
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全模块的所有枚举值选项"""
    from app.modules.safety.schemas import (
        ABNORMALITY_STATUS_OPTIONS,
        ACCIDENT_LEVEL_OPTIONS,
        ACCIDENT_STATUS_OPTIONS,
        ACCIDENT_TYPE_OPTIONS,
        ACTION_ITEM_STATUS_OPTIONS,
        APPROVAL_DECISION_OPTIONS,
        CHANGE_DURATION_OPTIONS,
        CHANGE_GRADE_OPTIONS,
        CHANGE_TYPE_OPTIONS,
        CHECK_TYPE_OPTIONS,
        COMPLETION_METHOD_OPTIONS,
        CONTRACTOR_STATUS_OPTIONS,
        CONTRACTOR_TRAINING_STATUS_OPTIONS,
        DETECTION_TYPE_OPTIONS,
        EHS_CHANGE_STATUS_OPTIONS,
        EXAM_CONCLUSION_OPTIONS,
        EXAM_STATUS_OPTIONS,
        EXAM_TYPE_OPTIONS,
        HAZARD_CATEGORY_OPTIONS,
        HAZARD_FACTOR_CATEGORY_OPTIONS,
        HAZARD_LEVEL_OPTIONS,
        HAZARD_TYPE_OPTIONS,
        INJURY_SEVERITY_OPTIONS,
        KNOWLEDGE_CATEGORY_OPTIONS,
        MONITOR_STATUS_OPTIONS,
        OEL_COMPLIANCE_STATUS_OPTIONS,
        OPERATION_LEVEL_OPTIONS,
        OPERATION_TYPE_OPTIONS,
        PERMIT_STATUS_OPTIONS,
        PERSONNEL_STATUS_OPTIONS,
        PSSR_RESULT_OPTIONS,
        REPORT_STATUS_OPTIONS,
        REVIEW_OPINION_OPTIONS,
        REVISION_SCOPE_OPTIONS,
        REVISION_TYPE_OPTIONS,
        RISK_ASSESSMENT_METHOD_OPTIONS,
        RISK_LEVEL_OPTIONS,
        TRAINING_MODE_OPTIONS,
        TRAINING_TYPE_OPTIONS,
    )

    return ApiResponse(
        data={
            "check_types": CHECK_TYPE_OPTIONS,
            "hazard_types": HAZARD_TYPE_OPTIONS,
            "hazard_levels": HAZARD_LEVEL_OPTIONS,
            "hazard_categories": HAZARD_CATEGORY_OPTIONS,
            "accident_types": ACCIDENT_TYPE_OPTIONS,
            "accident_levels": ACCIDENT_LEVEL_OPTIONS,
            "accident_statuses": ACCIDENT_STATUS_OPTIONS,
            "injury_severities": INJURY_SEVERITY_OPTIONS,
            "training_types": TRAINING_TYPE_OPTIONS,
            "training_modes": TRAINING_MODE_OPTIONS,
            "revision_types": REVISION_TYPE_OPTIONS,
            "revision_scopes": REVISION_SCOPE_OPTIONS,
            "review_opinions": REVIEW_OPINION_OPTIONS,
            "operation_types": OPERATION_TYPE_OPTIONS,
            "operation_levels": OPERATION_LEVEL_OPTIONS,
            "personnel_statuses": PERSONNEL_STATUS_OPTIONS,
            "permit_statuses": PERMIT_STATUS_OPTIONS,
            "completion_methods": COMPLETION_METHOD_OPTIONS,
            "knowledge_categories": KNOWLEDGE_CATEGORY_OPTIONS,
            "report_statuses": REPORT_STATUS_OPTIONS,
            "contractor_statuses": CONTRACTOR_STATUS_OPTIONS,
            "qualification_types": QUALIFICATION_TYPE_OPTIONS,
            "qualification_levels": QUALIFICATION_LEVEL_OPTIONS,
            "contractor_training_statuses": CONTRACTOR_TRAINING_STATUS_OPTIONS,
            "work_record_statuses": WORK_RECORD_STATUS_OPTIONS,
            "ehs_change_types": CHANGE_TYPE_OPTIONS,
            "ehs_change_grades": CHANGE_GRADE_OPTIONS,
            "ehs_change_durations": CHANGE_DURATION_OPTIONS,
            "ehs_change_statuses": EHS_CHANGE_STATUS_OPTIONS,
            "risk_levels": RISK_LEVEL_OPTIONS,
            "risk_assessment_methods": RISK_ASSESSMENT_METHOD_OPTIONS,
            "approval_decisions": APPROVAL_DECISION_OPTIONS,
            "action_item_statuses": ACTION_ITEM_STATUS_OPTIONS,
            "pssr_results": PSSR_RESULT_OPTIONS,
            "oh_detection_types": DETECTION_TYPE_OPTIONS,
            "oh_hazard_factor_categories": HAZARD_FACTOR_CATEGORY_OPTIONS,
            "oh_oel_compliance_statuses": OEL_COMPLIANCE_STATUS_OPTIONS,
            "oh_monitor_statuses": MONITOR_STATUS_OPTIONS,
            "oh_exam_types": EXAM_TYPE_OPTIONS,
            "oh_exam_conclusions": EXAM_CONCLUSION_OPTIONS,
            "oh_exam_statuses": EXAM_STATUS_OPTIONS,
            "oh_abnormality_statuses": ABNORMALITY_STATUS_OPTIONS,
        }
    )


# ==================== 危险源辨识 Routes ====================


@router.get(
    "/hazard-identifications",
    response_model=ApiResponse,
    summary="获取危险源辨识列表",
)
async def get_hazard_identifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    department: str | None = None,
    overall_status: str | None = None,
    ai_node_progress: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取危险源辨识列表"""
    service = SafetyService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_hazard_identifications(
        skip, page_size, department, overall_status, ai_node_progress, keyword
    )
    return ApiResponse(
        data=[HazardIdentificationResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/hazard-identifications/risk-options",
    response_model=ApiResponse,
    summary="获取危险源风险选项（常规作业报备用）",
)
async def get_hazard_risk_options(
    department: str | None = Query(None, description="部门筛选"),
    keyword: str | None = Query(None, description="搜索关键字（编号/部门/岗位）"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """返回风险等级为 level_1/level_2 且 overall_status=completed 的危险源辨识项"""
    service = DailyRiskReportService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_hazard_risk_options(department, keyword, skip, page_size)
    return ApiResponse(
        data=[HazardRiskOption.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/hazard-identifications/{hid}",
    response_model=ApiResponse,
    summary="获取危险源辨识详情",
)
async def get_hazard_identification(
    hid: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取危险源辨识详情"""
    service = SafetyService(db)
    item = await service.get_hazard_identification(hid)
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.post(
    "/hazard-identifications",
    response_model=ApiResponse,
    summary="创建危险源辨识记录",
)
async def create_hazard_identification(
    data: HazardIdentificationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建危险源辨识记录（填写基础信息）"""
    service = SafetyService(db)
    item = await service.create_hazard_identification(data)
    await db.commit()
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.put(
    "/hazard-identifications/{hid}",
    response_model=ApiResponse,
    summary="更新危险源辨识记录",
)
async def update_hazard_identification(
    hid: uuid.UUID,
    data: HazardIdentificationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新危险源辨识记录（人工编辑字段）"""
    service = SafetyService(db)
    item = await service.update_hazard_identification(hid, data)
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.post(
    "/hazard-identifications/{hid}/submit",
    response_model=ApiResponse,
    summary="提交基础信息，进入AI流程",
)
async def submit_hazard_identification(
    hid: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交基础信息 → 进入待AI解析附件阶段"""
    service = SafetyService(db)
    item = await service.submit_hazard_identification(hid)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.post(
    "/hazard-identifications/{hid}/run-script",
    response_model=ApiResponse,
    summary="执行AI脚本",
)
async def run_hazard_script(
    hid: uuid.UUID,
    data: HazardIdentificationRunScript,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """执行指定编号的AI脚本（脚本1-7）"""
    service = SafetyService(db)
    item = await service.run_script(hid, data.script_number, data.ai_output)
    if not item:
        return ApiResponse(code=400, message="无法执行脚本，当前状态不允许或条件不满足")
    await db.commit()
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.post(
    "/hazard-identifications/{hid}/review",
    response_model=ApiResponse,
    summary="审核脚本输出",
)
async def review_hazard_script(
    hid: uuid.UUID,
    data: HazardIdentificationReview,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审核确认或驳回AI脚本输出结果"""
    service = SafetyService(db)
    item = await service.review_script(hid, data.script_number, data.action)
    if not item:
        return ApiResponse(code=400, message="无法审核，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.post(
    "/hazard-identifications/{hid}/upload",
    response_model=ApiResponse,
    summary="上传岗位资料附件",
)
async def upload_hazard_attachment(
    hid: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传危险源辨识的岗位资料附件"""
    # 保存到本地 uploads/safety/hazard 目录
    import os

    upload_dir = os.path.join("uploads", "safety", "hazard")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or ".bin")[1]
    safe_name = f"{hid}_{int(datetime.now().timestamp())}{file_ext}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    service = SafetyService(db)
    item = await service.upload_attachment(
        hid, file.filename or "unknown", file_path
    )
    if not item:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(data=HazardIdentificationResponse.model_validate(item))


@router.delete(
    "/hazard-identifications/{hid}",
    response_model=ApiResponse,
    summary="删除危险源辨识记录",
)
async def delete_hazard_identification(
    hid: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除危险源辨识记录"""
    service = SafetyService(db)
    result = await service.delete_hazard_identification(hid)
    if not result:
        return ApiResponse(code=404, message="记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── 危险源辨识台账 AI 导出 ──


@router.post(
    "/hazard-identifications/parse-query",
    response_model=ApiResponse,
    summary="AI 解析危险源辨识台账自然语言筛选条件",
)
async def parse_hazard_ledger_query(
    data: HazardLedgerExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """使用 AI 将自然语言查询解析为结构化的危险源辨识台账筛选条件"""
    service = SafetyService(db)
    if not data.natural_query:
        return ApiResponse(code=400, message="请提供自然语言查询")
    result = await service.parse_hazard_export_query(data.natural_query)
    return ApiResponse(data=result)


@router.post(
    "/hazard-identifications/export-pdf",
    summary="导出危险源辨识台账 PDF",
)
async def export_hazard_ledger_pdf(
    data: HazardLedgerExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """导出危险源辨识台账为 PDF 文件，支持 AI 自然语言筛选"""
    from datetime import datetime as dt_module

    from fastapi.responses import Response

    service = SafetyService(db)

    # 如果有自然语言查询，先用 AI 解析
    filters: dict = {}
    if data.natural_query:
        parsed = await service.parse_hazard_export_query(data.natural_query)
        filters = {k: v for k, v in parsed.items() if k != "explanation"}
    else:
        filters = {
            k: v for k, v in {
                "department": data.department,
                "position": data.position,
                "risk_level": data.risk_level,
                "date_from": data.date_from,
                "date_to": data.date_to,
                "keyword": data.keyword,
            }.items() if v is not None
        }

    pdf_bytes = await service.export_hazard_ledger_pdf(**filters)

    filename = f"危险源辨识台账_{dt_module.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(len(pdf_bytes)),
        },
    )


# ==================== 安全操作规程 Routes ====================


@router.get("/regulations", response_model=ApiResponse, summary="获取安全操作规程列表")
async def get_regulations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    position: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全操作规程列表，支持按岗位和关键词筛选"""
    service = RegulationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_regulations(skip, page_size, position, keyword)
    return ApiResponse(
        data=[OperationRegulationResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/regulations/{regulation_id}",
    response_model=ApiResponse,
    summary="获取安全操作规程详情",
)
async def get_regulation(
    regulation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全操作规程详情，包含修订记录"""
    service = RegulationService(db)
    item = await service.get_regulation(regulation_id)
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


@router.post("/regulations", response_model=ApiResponse, summary="创建安全操作规程")
async def create_regulation(
    data: OperationRegulationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全操作规程"""
    service = RegulationService(db)
    item = await service.create_regulation(data)
    await db.commit()
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


@router.put(
    "/regulations/{regulation_id}",
    response_model=ApiResponse,
    summary="更新安全操作规程",
)
async def update_regulation(
    regulation_id: uuid.UUID,
    data: OperationRegulationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全操作规程"""
    service = RegulationService(db)
    item = await service.update_regulation(regulation_id, data)
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


@router.delete(
    "/regulations/{regulation_id}",
    response_model=ApiResponse,
    summary="删除安全操作规程",
)
async def delete_regulation(
    regulation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全操作规程"""
    service = RegulationService(db)
    result = await service.delete_regulation(regulation_id)
    if not result:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post(
    "/regulations/{regulation_id}/upload",
    response_model=ApiResponse,
    summary="上传操规文档",
)
async def upload_regulation_document(
    regulation_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传操规文档并更新操规记录"""
    import os

    upload_dir = os.path.join("uploads", "safety", "regulations")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or ".md")[1]
    safe_name = f"{regulation_id}_{int(datetime.now().timestamp())}{file_ext}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    service = RegulationService(db)
    item = await service.upload_regulation_document(
        regulation_id, file.filename or "unknown", file_path
    )
    if not item:
        return ApiResponse(code=404, message="操规不存在")
    await db.commit()
    return ApiResponse(data=OperationRegulationResponse.model_validate(item))


# ==================== 操规修订记录 Routes ====================


@router.get("/revisions", response_model=ApiResponse, summary="获取修订记录列表")
async def get_revisions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    regulation_id: uuid.UUID | None = None,
    revision_type: str | None = None,
    review_opinion: str | None = None,
    revision_scope: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取修订记录列表，支持多条件筛选"""
    service = RegulationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_revisions(
        skip, page_size, regulation_id, revision_type, review_opinion, revision_scope
    )
    return ApiResponse(
        data=[RegulationRevisionResponse.model_validate(r) for r in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/revisions/{revision_id}",
    response_model=ApiResponse,
    summary="获取修订记录详情",
)
async def get_revision(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取修订记录详情，包含关联的危险源辨识记录"""
    service = RegulationService(db)
    item = await service.get_revision(revision_id)
    if not item:
        return ApiResponse(code=404, message="修订记录不存在")
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


@router.post("/revisions", response_model=ApiResponse, summary="创建修订记录")
async def create_revision(
    data: RegulationRevisionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建修订记录，自动从操规表获取旧文档链接"""
    service = RegulationService(db)
    item = await service.create_revision(data)
    if not item:
        return ApiResponse(code=404, message="关联的操规不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


@router.put(
    "/revisions/{revision_id}",
    response_model=ApiResponse,
    summary="更新修订记录",
)
async def update_revision(
    revision_id: uuid.UUID,
    data: RegulationRevisionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新修订记录"""
    service = RegulationService(db)
    item = await service.update_revision(revision_id, data)
    if not item:
        return ApiResponse(code=404, message="修订记录不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


@router.delete(
    "/revisions/{revision_id}",
    response_model=ApiResponse,
    summary="删除修订记录",
)
async def delete_revision(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除修订记录"""
    service = RegulationService(db)
    result = await service.delete_revision(revision_id)
    if not result:
        return ApiResponse(code=404, message="修订记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── 人工修订 ──


@router.post(
    "/revisions/{revision_id}/manual-complete",
    response_model=ApiResponse,
    summary="完成人工修订",
)
async def manual_revision_complete(
    revision_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传修订后的文档，完成人工修订流程：
    1. 保存新文档到 uploads/
    2. 更新修订记录（新文档链接 + 审核通过）
    3. 同步更新操规表文档链接
    """
    import os

    upload_dir = os.path.join("uploads", "safety", "regulations")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or ".md")[1]
    safe_name = f"revision_{revision_id}_{int(datetime.now().timestamp())}{file_ext}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    service = RegulationService(db)
    item = await service.manual_revision_complete(
        revision_id, file_path, file.filename
    )
    if not item:
        return ApiResponse(code=400, message="无法完成修订，当前状态不允许或修订类型不是人工修订")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


# ── AI 修订 ──


@router.post(
    "/revisions/{revision_id}/ai-generate",
    response_model=ApiResponse,
    summary="AI生成修订版本",
)
async def ai_revision_generate(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """AI根据修订意见生成修订后的操规文档（返回供用户确认，不持久化）"""
    service = RegulationService(db)
    result = await service.ai_revision_generate(revision_id)
    if not result:
        return ApiResponse(code=400, message="无法生成，修订类型不是AI修订或修订记录不存在")
    return ApiResponse(data=result)


@router.post(
    "/revisions/{revision_id}/ai-confirm",
    response_model=ApiResponse,
    summary="确认AI修订版本",
)
async def ai_revision_confirm(
    revision_id: uuid.UUID,
    generated_content: str = Query(..., description="AI生成的修订后完整内容"),
    document_name: str | None = Query(None, description="文档名称（可选）"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """用户确认AI生成的修订内容后，保存文档并更新所有关联记录"""
    service = RegulationService(db)
    item = await service.ai_revision_confirm(
        revision_id, generated_content, document_name
    )
    if not item:
        return ApiResponse(code=400, message="无法确认，修订类型不是AI修订或修订记录不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


# ── 修订范围识别 ──


@router.post(
    "/revisions/{revision_id}/identify-scope",
    response_model=ApiResponse,
    summary="AI识别修订范围",
)
async def identify_revision_scope(
    revision_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """AI分析修订意见，识别修订范围（工艺/安全要求）。
    若识别出工艺变更，自动触发危险源辨识修订流程。
    """
    service = RegulationService(db)
    item = await service.identify_revision_scope(revision_id)
    if not item:
        return ApiResponse(code=404, message="修订记录不存在")
    await db.commit()
    return ApiResponse(data=RegulationRevisionResponse.model_validate(item))


# ==================== AI 工作流配置 Routes ====================


@router.get(
    "/ai-workflow-configs",
    response_model=ApiResponse,
    summary="获取 AI 工作流配置列表",
)
async def get_ai_workflow_configs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=500, description="每页条数"),
    module_code: str | None = Query(None, description="模块代码"),
    is_enabled: bool | None = Query(None, description="是否启用"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取 AI 工作流配置列表，可按模块代码过滤"""
    service = ConfigService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ai_workflow_configs(
        skip, page_size, module_code, is_enabled
    )
    return ApiResponse(
        data=[AIWorkflowConfigResponse.model_validate(item) for item in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/ai-workflow-configs/{config_id}",
    response_model=ApiResponse,
    summary="获取 AI 工作流配置详情",
)
async def get_ai_workflow_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取单个 AI 工作流配置详情"""
    service = ConfigService(db)
    item = await service.get_ai_workflow_config(config_id)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    return ApiResponse(data=AIWorkflowConfigResponse.model_validate(item))


@router.post(
    "/ai-workflow-configs",
    response_model=ApiResponse,
    summary="创建 AI 工作流配置",
)
async def create_ai_workflow_config(
    data: AIWorkflowConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建新的 AI 工作流配置"""
    service = ConfigService(db)
    item = await service.create_ai_workflow_config(data)
    await db.commit()
    return ApiResponse(data=AIWorkflowConfigResponse.model_validate(item))


@router.put(
    "/ai-workflow-configs/{config_id}",
    response_model=ApiResponse,
    summary="更新 AI 工作流配置",
)
async def update_ai_workflow_config(
    config_id: uuid.UUID,
    data: AIWorkflowConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新 AI 工作流配置"""
    service = ConfigService(db)
    item = await service.update_ai_workflow_config(config_id, data)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(data=AIWorkflowConfigResponse.model_validate(item))


@router.delete(
    "/ai-workflow-configs/{config_id}",
    response_model=ApiResponse,
    summary="删除 AI 工作流配置",
)
async def delete_ai_workflow_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除 AI 工作流配置"""
    service = ConfigService(db)
    result = await service.delete_ai_workflow_config(config_id)
    if not result:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== API 调用配置 Routes ====================


@router.get(
    "/api-call-configs",
    response_model=ApiResponse,
    summary="获取 API 调用配置列表",
)
async def get_api_call_configs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=500, description="每页条数"),
    is_active: bool | None = Query(None, description="是否激活"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取 API 调用配置列表"""
    service = ConfigService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_api_call_configs(skip, page_size, is_active)

    db_configs = [APICallConfigResponse.model_validate(item) for item in items]
    return ApiResponse(
        data=db_configs,
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/api-call-configs/{config_id}",
    response_model=ApiResponse,
    summary="获取 API 调用配置详情",
)
async def get_api_call_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取单个 API 调用配置详情"""
    service = ConfigService(db)
    item = await service.get_api_call_config(config_id)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    return ApiResponse(data=APICallConfigResponse.model_validate(item))


@router.post(
    "/api-call-configs",
    response_model=ApiResponse,
    summary="创建 API 调用配置",
)
async def create_api_call_config(
    data: APICallConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建新的 API 调用配置（如标记为激活则自动停用其他配置）"""
    service = ConfigService(db)
    item = await service.create_api_call_config(data)
    await db.commit()
    return ApiResponse(data=APICallConfigResponse.model_validate(item))


@router.put(
    "/api-call-configs/{config_id}",
    response_model=ApiResponse,
    summary="更新 API 调用配置",
)
async def update_api_call_config(
    config_id: uuid.UUID,
    data: APICallConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新 API 调用配置"""
    service = ConfigService(db)
    item = await service.update_api_call_config(config_id, data)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(data=APICallConfigResponse.model_validate(item))


@router.post(
    "/api-call-configs/{config_id}/activate",
    response_model=ApiResponse,
    summary="激活 API 调用配置",
)
async def activate_api_call_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """激活指定的 API 调用配置（自动停用其他配置）"""
    service = ConfigService(db)
    item = await service.activate_api_call_config(config_id)
    if not item:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(data=APICallConfigResponse.model_validate(item))


@router.delete(
    "/api-call-configs/{config_id}",
    response_model=ApiResponse,
    summary="删除 API 调用配置",
)
async def delete_api_call_config(
    config_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除 API 调用配置"""
    service = ConfigService(db)
    result = await service.delete_api_call_config(config_id)
    if not result:
        return ApiResponse(code=404, message="配置不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 特殊作业人员资质 Routes ====================


@router.get(
    "/special-operation-personnel",
    response_model=ApiResponse,
    summary="获取特殊作业人员资质列表",
)
async def get_special_operation_personnel(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    certificate_type: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业人员资质列表"""
    service = SpecialOperationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_personnel(
        skip, page_size, status, certificate_type, department, keyword
    )
    return ApiResponse(
        data=[SpecialOperationPersonnelResponse.model_validate(p) for p in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post(
    "/special-operation-personnel",
    response_model=ApiResponse,
    summary="创建特殊作业人员资质",
)
async def create_special_operation_personnel(
    data: SpecialOperationPersonnelCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建特殊作业人员资质"""
    service = SpecialOperationService(db)
    item = await service.create_personnel(data)
    await db.commit()
    return ApiResponse(data=SpecialOperationPersonnelResponse.model_validate(item))


@router.get(
    "/special-operation-personnel/{personnel_id}",
    response_model=ApiResponse,
    summary="获取特殊作业人员资质详情",
)
async def get_special_operation_personnel_detail(
    personnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业人员资质详情"""
    service = SpecialOperationService(db)
    item = await service.get_personnel_by_id(personnel_id)
    if not item:
        return ApiResponse(code=404, message="人员资质不存在")
    return ApiResponse(data=SpecialOperationPersonnelResponse.model_validate(item))


@router.put(
    "/special-operation-personnel/{personnel_id}",
    response_model=ApiResponse,
    summary="更新特殊作业人员资质",
)
async def update_special_operation_personnel(
    personnel_id: uuid.UUID,
    data: SpecialOperationPersonnelUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新特殊作业人员资质"""
    service = SpecialOperationService(db)
    item = await service.update_personnel(personnel_id, data)
    if not item:
        return ApiResponse(code=404, message="人员资质不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationPersonnelResponse.model_validate(item))


@router.delete(
    "/special-operation-personnel/{personnel_id}",
    response_model=ApiResponse,
    summary="删除特殊作业人员资质",
)
async def delete_special_operation_personnel(
    personnel_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除特殊作业人员资质"""
    service = SpecialOperationService(db)
    result = await service.delete_personnel(personnel_id)
    if not result:
        return ApiResponse(code=404, message="人员资质不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 特殊作业票 Routes ====================


@router.get(
    "/special-operation-permits",
    response_model=ApiResponse,
    summary="获取特殊作业票列表",
)
async def get_special_operation_permits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    operation_type: str | None = None,
    operation_level: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业票列表"""
    service = SpecialOperationService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_permits(
        skip, page_size, status, operation_type, operation_level, keyword
    )
    return ApiResponse(
        data=[SpecialOperationPermitResponse.model_validate(p) for p in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post(
    "/special-operation-permits",
    response_model=ApiResponse,
    summary="创建特殊作业票",
)
async def create_special_operation_permit(
    data: SpecialOperationPermitCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建特殊作业票"""
    service = SpecialOperationService(db)
    item = await service.create_permit(data)
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.get(
    "/special-operation-permits/{permit_id}",
    response_model=ApiResponse,
    summary="获取特殊作业票详情",
)
async def get_special_operation_permit(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业票详情"""
    service = SpecialOperationService(db)
    item = await service.get_permit(permit_id)
    if not item:
        return ApiResponse(code=404, message="作业票不存在")
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.put(
    "/special-operation-permits/{permit_id}",
    response_model=ApiResponse,
    summary="更新特殊作业票",
)
async def update_special_operation_permit(
    permit_id: uuid.UUID,
    data: SpecialOperationPermitUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新特殊作业票"""
    service = SpecialOperationService(db)
    item = await service.update_permit(permit_id, data)
    if not item:
        return ApiResponse(code=404, message="作业票不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.delete(
    "/special-operation-permits/{permit_id}",
    response_model=ApiResponse,
    summary="删除特殊作业票",
)
async def delete_special_operation_permit(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除特殊作业票"""
    service = SpecialOperationService(db)
    result = await service.delete_permit(permit_id)
    if not result:
        return ApiResponse(code=404, message="作业票不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ==================== 特殊作业票工作流 Routes ====================


@router.post(
    "/special-operation-permits/{permit_id}/submit",
    response_model=ApiResponse,
    summary="提交作业票",
)
async def submit_special_operation_permit(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交作业票（草稿→已提交）"""
    service = SpecialOperationService(db)
    item = await service.submit_permit(permit_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.post(
    "/special-operation-permits/{permit_id}/approve",
    response_model=ApiResponse,
    summary="审批作业票",
)
async def approve_special_operation_permit(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批作业票（已提交→已审批）"""
    service = SpecialOperationService(db)
    item = await service.approve_permit(permit_id)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.post(
    "/special-operation-permits/{permit_id}/reject",
    response_model=ApiResponse,
    summary="驳回作业票",
)
async def reject_special_operation_permit(
    permit_id: uuid.UUID,
    reason: str = Query(..., description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回作业票（已提交→已驳回）"""
    service = SpecialOperationService(db)
    item = await service.reject_permit(permit_id, reason)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.post(
    "/special-operation-permits/{permit_id}/start",
    response_model=ApiResponse,
    summary="开始作业",
)
async def start_special_operation_permit(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始作业（已审批→作业中）"""
    service = SpecialOperationService(db)
    item = await service.start_permit(permit_id)
    if not item:
        return ApiResponse(code=400, message="无法开始作业，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.post(
    "/special-operation-permits/{permit_id}/complete",
    response_model=ApiResponse,
    summary="完工验收",
)
async def complete_special_operation_permit(
    permit_id: uuid.UUID,
    method: str = Query(..., description="完工方式: normal/early_termination"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完工验收（作业中→已完工）"""
    service = SpecialOperationService(db)
    item = await service.complete_permit(permit_id, method)
    if not item:
        return ApiResponse(code=400, message="无法完工，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


@router.post(
    "/special-operation-permits/{permit_id}/archive",
    response_model=ApiResponse,
    summary="归档作业票",
)
async def archive_special_operation_permit(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """归档作业票（已完工→已归档）"""
    service = SpecialOperationService(db)
    item = await service.archive_permit(permit_id)
    if not item:
        return ApiResponse(code=400, message="无法归档，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationPermitResponse.model_validate(item))


# ==================== 安全知识库 Routes ====================


@router.get("/knowledge-articles", response_model=ApiResponse, summary="获取安全知识库文章列表")
async def get_knowledge_articles(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全知识库文章列表"""
    service = KnowledgeService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_articles(skip, page_size, category, status, keyword)
    return ApiResponse(
        data=[SafetyKnowledgeArticleResponse.model_validate(a) for a in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/knowledge-articles", response_model=ApiResponse, summary="创建安全知识库文章")
async def create_knowledge_article(
    data: SafetyKnowledgeArticleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建安全知识库文章"""
    service = KnowledgeService(db)
    item = await service.create_article(data)
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@router.get("/knowledge-articles/{article_id}", response_model=ApiResponse, summary="获取安全知识库文章详情")
async def get_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取安全知识库文章详情"""
    service = KnowledgeService(db)
    item = await service.get_article(article_id)
    if not item:
        return ApiResponse(code=404, message="文章不存在")
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@router.put("/knowledge-articles/{article_id}", response_model=ApiResponse, summary="更新安全知识库文章")
async def update_knowledge_article(
    article_id: uuid.UUID,
    data: SafetyKnowledgeArticleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新安全知识库文章"""
    service = KnowledgeService(db)
    item = await service.update_article(article_id, data)
    if not item:
        return ApiResponse(code=404, message="文章不存在")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@router.delete("/knowledge-articles/{article_id}", response_model=ApiResponse, summary="删除安全知识库文章")
async def delete_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除安全知识库文章"""
    service = KnowledgeService(db)
    result = await service.delete_article(article_id)
    if not result:
        return ApiResponse(code=404, message="文章不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post("/knowledge-articles/{article_id}/publish", response_model=ApiResponse, summary="发布知识库文章")
async def publish_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """发布文章（草稿→已发布）"""
    service = KnowledgeService(db)
    item = await service.publish_article(article_id)
    if not item:
        return ApiResponse(code=400, message="无法发布，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@router.post("/knowledge-articles/{article_id}/archive", response_model=ApiResponse, summary="归档知识库文章")
async def archive_knowledge_article(
    article_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """归档文章（已发布→已归档）"""
    service = KnowledgeService(db)
    item = await service.archive_article(article_id)
    if not item:
        return ApiResponse(code=400, message="无法归档，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


@router.post("/knowledge-articles/{article_id}/upload", response_model=ApiResponse, summary="上传知识库文章附件")
async def upload_knowledge_article_attachment(
    article_id: uuid.UUID,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """上传知识库文章附件"""
    import os

    upload_dir = os.path.join("uploads", "safety", "knowledge")
    os.makedirs(upload_dir, exist_ok=True)

    file_ext = os.path.splitext(file.filename or ".bin")[1]
    safe_name = f"{article_id}_{int(datetime.now().timestamp())}{file_ext}"
    file_path = os.path.join(upload_dir, safe_name)

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    service = KnowledgeService(db)
    from app.modules.safety.repository import SafetyRepository
    repo = SafetyRepository(db)
    item = await repo.update_knowledge_article(
        article_id,
        {
            "attachment_path": file_path,
            "attachment_original_name": file.filename or "unknown",
        },
    )
    if not item:
        return ApiResponse(code=404, message="文章不存在")
    await db.commit()
    return ApiResponse(data=SafetyKnowledgeArticleResponse.model_validate(item))


# ==================== 八大特殊作业报备 Routes ====================


@router.get("/special-operation-reports", response_model=ApiResponse, summary="获取特殊作业报备列表")
async def get_special_operation_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    operation_type: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业报备列表"""
    service = SpecialOperationReportService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_reports(skip, page_size, status, operation_type, department, keyword)
    return ApiResponse(
        data=[SpecialOperationReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/special-operation-reports", response_model=ApiResponse, summary="创建特殊作业报备")
async def create_special_operation_report(
    data: SpecialOperationReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建特殊作业报备"""
    service = SpecialOperationReportService(db)
    item = await service.create_report(data)
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@router.get("/special-operation-reports/{report_id}", response_model=ApiResponse, summary="获取特殊作业报备详情")
async def get_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业报备详情"""
    service = SpecialOperationReportService(db)
    item = await service.get_report(report_id)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@router.put("/special-operation-reports/{report_id}", response_model=ApiResponse, summary="更新特殊作业报备")
async def update_special_operation_report(
    report_id: uuid.UUID,
    data: SpecialOperationReportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新特殊作业报备"""
    service = SpecialOperationReportService(db)
    item = await service.update_report(report_id, data)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@router.delete("/special-operation-reports/{report_id}", response_model=ApiResponse, summary="删除特殊作业报备")
async def delete_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除特殊作业报备（软删除）"""
    service = SpecialOperationReportService(db)
    ok = await service.delete_report(report_id)
    if not ok:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post("/special-operation-reports/{report_id}/submit", response_model=ApiResponse, summary="提交特殊作业报备")
async def submit_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交报备（草稿→已提交）"""
    service = SpecialOperationReportService(db)
    item = await service.submit_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@router.post("/special-operation-reports/{report_id}/approve", response_model=ApiResponse, summary="审批特殊作业报备")
async def approve_special_operation_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批通过报备（已提交→已审批）"""
    service = SpecialOperationReportService(db)
    item = await service.approve_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@router.post("/special-operation-reports/{report_id}/reject", response_model=ApiResponse, summary="驳回特殊作业报备")
async def reject_special_operation_report(
    report_id: uuid.UUID,
    reason: str = Query(..., description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回报备（已提交→已驳回）"""
    service = SpecialOperationReportService(db)
    item = await service.reject_report(report_id, reason)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


@router.put(
    "/special-operation-reports/{report_id}/critical",
    response_model=ApiResponse,
    summary="手动设置关键作业标记",
)
async def set_special_operation_report_critical(
    report_id: uuid.UUID,
    data: SetCriticalRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动修改特殊作业报备的关键作业标记"""
    service = SpecialOperationReportService(db)
    updated_by = current_user.name if current_user else None
    item = await service.set_critical_manual(
        report_id, data.is_critical, data.reason, updated_by
    )
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(data=SpecialOperationReportResponse.model_validate(item))


# ==================== 特殊作业台账 Routes ====================


@router.get(
    "/special-operation-ledger",
    response_model=ApiResponse,
    summary="获取特殊作业台账列表",
)
async def get_special_operation_ledger(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    operation_type: str | None = None,
    operation_level: str | None = None,
    risk_level: str | None = None,
    department: str | None = None,
    date_from: str | None = Query(None, description="计划开始日期起 (YYYY-MM-DD)"),
    date_to: str | None = Query(None, description="计划结束日期止 (YYYY-MM-DD)"),
    keyword: str | None = None,
    is_critical: bool | None = Query(None, description="是否关键作业"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取特殊作业台账列表（审批中 + 已审批的报备记录）"""
    service = SpecialOperationReportService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ledger(
        skip=skip,
        limit=page_size,
        operation_type=operation_type,
        operation_level=operation_level,
        risk_level=risk_level,
        department=department,
        date_from=date_from,
        date_to=date_to,
        keyword=keyword,
        is_critical=is_critical,
    )
    return ApiResponse(
        data=[SpecialOperationReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.get(
    "/special-operation-ledger/stats",
    response_model=ApiResponse,
    summary="获取特殊作业台账统计",
)
async def get_special_operation_ledger_stats(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """按作业类型统计台账数量和关键作业数量"""
    service = SpecialOperationReportService(db)
    stats = await service.get_ledger_stats()
    return ApiResponse(
        data=[SpecialOperationLedgerStats(**s) for s in stats]
    )


@router.post(
    "/special-operation-ledger/parse-query",
    response_model=ApiResponse,
    summary="AI 解析自然语言筛选条件",
)
async def parse_ledger_query(
    data: LedgerExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """使用 AI 将自然语言查询解析为结构化的台账筛选条件"""
    service = SpecialOperationReportService(db)
    if not data.natural_query:
        return ApiResponse(code=400, message="请提供自然语言查询")
    result = await service.parse_natural_query(data.natural_query)
    return ApiResponse(data=result)


@router.post(
    "/special-operation-ledger/export",
    summary="导出特殊作业台账 Excel",
)
async def export_special_operation_ledger(
    data: LedgerExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """导出特殊作业台账为 Excel 文件，支持 AI 自然语言筛选"""
    from fastapi.responses import Response

    service = SpecialOperationReportService(db)

    # 如果有自然语言查询，先用 AI 解析
    filters: dict = {}
    if data.natural_query:
        parsed = await service.parse_natural_query(data.natural_query)
        filters = {k: v for k, v in parsed.items() if k != "explanation"}
    else:
        filters = {
            k: v for k, v in {
                "operation_type": data.operation_type,
                "operation_level": data.operation_level,
                "risk_level": data.risk_level,
                "department": data.department,
                "date_from": data.date_from,
                "date_to": data.date_to,
                "keyword": data.keyword,
                "is_critical": data.is_critical,
            }.items() if v is not None
        }

    excel_bytes = await service.export_ledger_excel(**filters)

    filename = f"特殊作业台账_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


# ==================== 每日风险作业报备 Routes ====================


@router.get("/daily-risk-reports", response_model=ApiResponse, summary="获取每日风险作业报备列表")
async def get_daily_risk_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    department: str | None = None,
    report_date: str | None = Query(None, description="报备日期 (YYYY-MM-DD)"),
    keyword: str | None = None,
    report_type: str | None = Query(None, description="报备类型: regular/non_regular"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取每日风险作业报备列表"""
    service = DailyRiskReportService(db)
    skip = (page - 1) * page_size
    parsed_date = None
    if report_date:
        from datetime import datetime as dt
        parsed_date = dt.fromisoformat(report_date)
    items, total = await service.get_reports(skip, page_size, status, department, parsed_date, keyword, report_type)
    return ApiResponse(
        data=[DailyRiskReportResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/daily-risk-reports", response_model=ApiResponse, summary="创建每日风险作业报备")
async def create_daily_risk_report(
    data: DailyRiskReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建每日风险作业报备"""
    service = DailyRiskReportService(db)
    item = await service.create_report(data)
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@router.get("/daily-risk-reports/{report_id}", response_model=ApiResponse, summary="获取每日风险作业报备详情")
async def get_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取每日风险作业报备详情"""
    service = DailyRiskReportService(db)
    item = await service.get_report(report_id)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@router.put("/daily-risk-reports/{report_id}", response_model=ApiResponse, summary="更新每日风险作业报备")
async def update_daily_risk_report(
    report_id: uuid.UUID,
    data: DailyRiskReportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新每日风险作业报备"""
    service = DailyRiskReportService(db)
    item = await service.update_report(report_id, data)
    if not item:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@router.delete("/daily-risk-reports/{report_id}", response_model=ApiResponse, summary="删除每日风险作业报备")
async def delete_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除每日风险作业报备（软删除）"""
    service = DailyRiskReportService(db)
    ok = await service.delete_report(report_id)
    if not ok:
        return ApiResponse(code=404, message="报备不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@router.post("/daily-risk-reports/{report_id}/submit", response_model=ApiResponse, summary="提交每日风险作业报备")
async def submit_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交报备（草稿→已提交）"""
    service = DailyRiskReportService(db)
    item = await service.submit_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@router.post("/daily-risk-reports/{report_id}/approve", response_model=ApiResponse, summary="审批每日风险作业报备")
async def approve_daily_risk_report(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批通过报备（已提交→已审批）"""
    service = DailyRiskReportService(db)
    item = await service.approve_report(report_id)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


@router.post("/daily-risk-reports/{report_id}/reject", response_model=ApiResponse, summary="驳回每日风险作业报备")
async def reject_daily_risk_report(
    report_id: uuid.UUID,
    reason: str = Query(..., description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回报备（已提交→已驳回）"""
    service = DailyRiskReportService(db)
    item = await service.reject_report(report_id, reason)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=DailyRiskReportResponse.model_validate(item))


# ==================== EHS变更管理 (MOC) Routes ====================


@router.get("/ehs-changes", response_model=ApiResponse, summary="获取EHS变更列表")
async def get_ehs_changes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    change_type: str | None = None,
    change_grade: str | None = None,
    change_duration: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取EHS变更列表，支持多条件筛选"""
    service = EhsChangeService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_ehs_changes(
        skip, page_size, status, change_type, change_grade, change_duration, department, keyword
    )
    return ApiResponse(
        data=[EhsChangeResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/ehs-changes", response_model=ApiResponse, summary="创建EHS变更")
async def create_ehs_change(
    data: EhsChangeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建EHS变更申请"""
    service = EhsChangeService(db)
    item = await service.create_ehs_change(data)
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.get("/ehs-changes/{change_id}", response_model=ApiResponse, summary="获取EHS变更详情")
async def get_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取EHS变更详情"""
    service = EhsChangeService(db)
    item = await service.get_ehs_change(change_id)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.put("/ehs-changes/{change_id}", response_model=ApiResponse, summary="更新EHS变更")
async def update_ehs_change(
    change_id: uuid.UUID,
    data: EhsChangeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新EHS变更"""
    service = EhsChangeService(db)
    item = await service.update_ehs_change(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.delete("/ehs-changes/{change_id}", response_model=ApiResponse, summary="删除EHS变更")
async def delete_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除EHS变更（软删除）"""
    service = EhsChangeService(db)
    ok = await service.delete_ehs_change(change_id)
    if not ok:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── EHS变更 工作流 Routes ──


@router.post("/ehs-changes/{change_id}/submit", response_model=ApiResponse, summary="提交EHS变更")
async def submit_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交变更（草稿→审核中；紧急变更自动批准）"""
    service = EhsChangeService(db)
    item = await service.submit_change(change_id)
    if not item:
        return ApiResponse(code=400, message="无法提交，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.post("/ehs-changes/{change_id}/approve", response_model=ApiResponse, summary="审批EHS变更")
async def approve_ehs_change(
    change_id: uuid.UUID,
    data: ApproveEhsChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """审批变更（审核中→已批准/已驳回）"""
    service = EhsChangeService(db)
    item = await service.approve_change(change_id, data.decision, data.comments)
    if not item:
        return ApiResponse(code=400, message="无法审批，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.post("/ehs-changes/{change_id}/reject", response_model=ApiResponse, summary="驳回EHS变更")
async def reject_ehs_change(
    change_id: uuid.UUID,
    comments: str | None = Query(None, description="驳回原因"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """驳回变更（审核中→已驳回）"""
    service = EhsChangeService(db)
    item = await service.reject_change(change_id, comments)
    if not item:
        return ApiResponse(code=400, message="无法驳回，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.post("/ehs-changes/{change_id}/start-implementation", response_model=ApiResponse, summary="开始实施EHS变更")
async def start_implementation_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始实施变更（已批准→实施中）"""
    service = EhsChangeService(db)
    item = await service.start_implementation(change_id)
    if not item:
        return ApiResponse(code=400, message="无法开始实施，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.post("/ehs-changes/{change_id}/commission", response_model=ApiResponse, summary="投用EHS变更")
async def commission_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """投用变更（实施中→已投用）"""
    service = EhsChangeService(db)
    item = await service.commission_change(change_id)
    if not item:
        return ApiResponse(code=400, message="无法投用，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.post("/ehs-changes/{change_id}/close", response_model=ApiResponse, summary="关闭EHS变更")
async def close_ehs_change(
    change_id: uuid.UUID,
    data: CloseEhsChangeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """关闭变更（已投用→已关闭）"""
    service = EhsChangeService(db)
    item = await service.close_change(
        change_id, data.closed_by, data.temp_expiry_date, data.restored_date
    )
    if not item:
        return ApiResponse(code=400, message="无法关闭，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.post("/ehs-changes/{change_id}/cancel", response_model=ApiResponse, summary="取消EHS变更")
async def cancel_ehs_change(
    change_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """取消变更（草稿→已关闭）"""
    service = EhsChangeService(db)
    item = await service.cancel_change(change_id)
    if not item:
        return ApiResponse(code=400, message="无法取消，当前状态不允许")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


# ── EHS变更 JSON子记录操作 Routes ──


@router.post("/ehs-changes/{change_id}/risk-assessments", response_model=ApiResponse, summary="添加风险评估记录")
async def add_risk_assessment_ehs_change(
    change_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加风险评估记录到变更"""
    service = EhsChangeService(db)
    item = await service.add_risk_assessment(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.put("/ehs-changes/{change_id}/action-items/{index}", response_model=ApiResponse, summary="更新行动项状态")
async def update_action_item_ehs_change(
    change_id: uuid.UUID,
    index: int,
    status: str = Query(..., description="状态: pending/in_progress/completed"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新行动项状态"""
    service = EhsChangeService(db)
    item = await service.update_action_item(change_id, index, status)
    if not item:
        return ApiResponse(code=400, message="无法更新，变更不存在或索引无效")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.put("/ehs-changes/{change_id}/pssr-checklist", response_model=ApiResponse, summary="更新PSSR检查清单")
async def update_pssr_checklist_ehs_change(
    change_id: uuid.UUID,
    data: list[dict],
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新PSSR检查清单"""
    service = EhsChangeService(db)
    item = await service.update_pssr_checklist(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


@router.put("/ehs-changes/{change_id}/verification", response_model=ApiResponse, summary="提交变更验证数据")
async def submit_verification_ehs_change(
    change_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """提交变更验证数据"""
    service = EhsChangeService(db)
    item = await service.submit_verification(change_id, data)
    if not item:
        return ApiResponse(code=404, message="变更不存在")
    await db.commit()
    return ApiResponse(data=EhsChangeResponse.model_validate(item))


# ==================== 职业危害因素监测 Routes ====================


@router.get("/oh-hazard-monitors", response_model=ApiResponse, summary="获取职业危害因素监测列表")
async def get_oh_hazard_monitors(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    detection_type: str | None = None,
    workplace: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业危害因素监测列表，支持多条件筛选"""
    service = OhHazardMonitorService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_monitors(
        skip, page_size, status, detection_type, workplace, keyword
    )
    return ApiResponse(
        data=[OhHazardMonitorResponse.model_validate(i) for i in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@router.post("/oh-hazard-monitors", response_model=ApiResponse, summary="创建职业危害因素监测")
async def create_oh_hazard_monitor(
    data: OhHazardMonitorCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建职业危害因素监测记录"""
    service = OhHazardMonitorService(db)
    item = await service.create_monitor(data)
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.get("/oh-hazard-monitors/{monitor_id}", response_model=ApiResponse, summary="获取职业危害因素监测详情")
async def get_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取职业危害因素监测详情"""
    service = OhHazardMonitorService(db)
    item = await service.get_monitor(monitor_id)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.put("/oh-hazard-monitors/{monitor_id}", response_model=ApiResponse, summary="更新职业危害因素监测")
async def update_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    data: OhHazardMonitorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新职业危害因素监测"""
    service = OhHazardMonitorService(db)
    item = await service.update_monitor(monitor_id, data)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.delete("/oh-hazard-monitors/{monitor_id}", response_model=ApiResponse, summary="删除职业危害因素监测")
async def delete_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除职业危害因素监测（软删除）"""
    service = OhHazardMonitorService(db)
    ok = await service.delete_monitor(monitor_id)
    if not ok:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ── Monitor Workflow ──


@router.post("/oh-hazard-monitors/{monitor_id}/start", response_model=ApiResponse, summary="开始监测")
async def start_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """开始监测（草稿→检测中）"""
    service = OhHazardMonitorService(db)
    item = await service.start_monitoring(monitor_id)
    if not item:
        return ApiResponse(code=400, message="无法开始监测，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.post("/oh-hazard-monitors/{monitor_id}/complete", response_model=ApiResponse, summary="完成监测")
async def complete_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """完成监测（检测中→已完成），自动计算OEL合规状态"""
    service = OhHazardMonitorService(db)
    item = await service.complete_monitoring(monitor_id)
    if not item:
        return ApiResponse(code=400, message="无法完成监测，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.post("/oh-hazard-monitors/{monitor_id}/verify", response_model=ApiResponse, summary="验证监测")
async def verify_oh_hazard_monitor(
    monitor_id: uuid.UUID,
    data: VerifyMonitorRequest,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """验证监测（已完成→已验证）"""
    service = OhHazardMonitorService(db)
    item = await service.verify_monitoring(monitor_id, data.verified_by, data.comments)
    if not item:
        return ApiResponse(code=400, message="无法验证，当前状态不允许")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


# ── Monitor JSON Sub-records ──


@router.post("/oh-hazard-monitors/{monitor_id}/detection-results", response_model=ApiResponse, summary="添加检测结果")
async def add_detection_result(
    monitor_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加检测结果到监测记录"""
    service = OhHazardMonitorService(db)
    item = await service.add_detection_result(monitor_id, data)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.put("/oh-hazard-monitors/{monitor_id}/detection-results/{index}", response_model=ApiResponse, summary="更新检测结果")
async def update_detection_result(
    monitor_id: uuid.UUID,
    index: int,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新指定索引的检测结果"""
    service = OhHazardMonitorService(db)
    item = await service.update_detection_result(monitor_id, index, data)
    if not item:
        return ApiResponse(code=400, message="无法更新，监测记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.delete("/oh-hazard-monitors/{monitor_id}/detection-results/{index}", response_model=ApiResponse, summary="删除检测结果")
async def delete_detection_result(
    monitor_id: uuid.UUID,
    index: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除指定索引的检测结果"""
    service = OhHazardMonitorService(db)
    item = await service.remove_detection_result(monitor_id, index)
    if not item:
        return ApiResponse(code=400, message="无法删除，监测记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.post("/oh-hazard-monitors/{monitor_id}/abnormality-records", response_model=ApiResponse, summary="添加异常处置记录")
async def add_monitor_abnormality_record(
    monitor_id: uuid.UUID,
    data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """追加异常处置记录到监测"""
    service = OhHazardMonitorService(db)
    item = await service.add_abnormality_record(monitor_id, data)
    if not item:
        return ApiResponse(code=404, message="监测记录不存在")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


@router.put("/oh-hazard-monitors/{monitor_id}/abnormality-records/{index}", response_model=ApiResponse, summary="更新异常处置状态")
async def update_monitor_abnormality_status(
    monitor_id: uuid.UUID,
    index: int,
    status: str = Query(..., description="状态: open/investigating/corrected/closed"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新异常处置记录状态"""
    service = OhHazardMonitorService(db)
    item = await service.update_abnormality_record_status(monitor_id, index, status)
    if not item:
        return ApiResponse(code=400, message="无法更新，监测记录不存在或索引无效")
    await db.commit()
    return ApiResponse(data=OhHazardMonitorResponse.model_validate(item))


# ==================== 职业健康体检 Routes ====================


@router.get("/oh-health-exams", response_model=ApiResponse, summary="获取职业健康体检列表")
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


@router.post("/oh-health-exams", response_model=ApiResponse, summary="创建职业健康体检")
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


@router.get("/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="获取职业健康体检详情")
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


@router.put("/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="更新职业健康体检")
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


@router.delete("/oh-health-exams/{exam_id}", response_model=ApiResponse, summary="删除职业健康体检")
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


@router.post("/oh-health-exams/{exam_id}/start", response_model=ApiResponse, summary="开始体检")
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


@router.post("/oh-health-exams/{exam_id}/complete", response_model=ApiResponse, summary="完成体检")
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


@router.post("/oh-health-exams/{exam_id}/archive", response_model=ApiResponse, summary="归档体检")
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


@router.post("/oh-health-exams/{exam_id}/exam-items", response_model=ApiResponse, summary="添加体检项目")
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


@router.put("/oh-health-exams/{exam_id}/exam-items/{index}", response_model=ApiResponse, summary="更新体检项目")
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


@router.delete("/oh-health-exams/{exam_id}/exam-items/{index}", response_model=ApiResponse, summary="删除体检项目")
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


@router.put("/oh-health-exams/{exam_id}/conclusion", response_model=ApiResponse, summary="设置体检结论")
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


@router.post("/oh-health-exams/{exam_id}/abnormality-records", response_model=ApiResponse, summary="添加体检异常处置记录")
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


@router.put("/oh-health-exams/{exam_id}/abnormality-records/{index}", response_model=ApiResponse, summary="更新体检异常处置状态")
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
