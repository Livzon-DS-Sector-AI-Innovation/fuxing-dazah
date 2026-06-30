"""Safety API — hazards endpoints."""

import asyncio
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.core.storage import is_enabled as minio_enabled
from app.core.storage import upload_object
from app.modules.safety.schemas import (
    DepartmentLeaderResponse,
    DepartmentSafetyOfficerResponse,
    HazardReportCreate,
    HazardReportResponse,
    HazardReportUpdate,
    HazardStatsResponse,
    RectificationReplyRequest,
    VerifyLevelRequest,
)
from app.modules.safety.service import (
    HazardService,
)
from app.modules.safety.service.hazard import (
    _send_rectification_notification,
    _send_verify_notification,
)

hazards_router = APIRouter()


@hazards_router.get("/hazards", response_model=ApiResponse, summary="获取隐患列表")
async def get_hazards(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    status: str | None = None,
    rectification_status: str | None = None,
    hazard_type: str | None = None,
    hazard_level: str | None = None,
    hazard_category: str | None = None,
    inspection_category: str | None = None,
    department: str | None = None,
    keyword: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取隐患列表"""
    service = HazardService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_hazards(
        skip, page_size, status, rectification_status, hazard_type, hazard_level,
        hazard_category, inspection_category, department, keyword,
    )
    return ApiResponse(
        data=[HazardReportResponse.model_validate(h) for h in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@hazards_router.get("/hazards/stats", response_model=ApiResponse, summary="获取隐患统计数据")
async def get_hazard_stats(
    db: AsyncSession = Depends(get_db),
):
    """获取隐患全局统计数据（不受分页/筛选影响，用于统计药丸展示）。"""
    service = HazardService(db)
    stats = await service.get_hazard_stats()
    return ApiResponse(data=HazardStatsResponse(**stats))


@hazards_router.get("/hazards/department-leader", response_model=ApiResponse, summary="查询部门负责人")
async def get_department_leader(
    department_name: str = Query(..., min_length=1, description="部门名称"),
    db: AsyncSession = Depends(get_db),
):
    """根据部门名称查询部门负责人姓名。

    优先精确匹配，找不到时自动模糊匹配。
    数据来源：identity.departments 和 identity.users（每日同步自飞书）。
    """
    from app.modules.safety.feishu import IdentityResolver

    resolver = IdentityResolver(db)
    person = await resolver.resolve_department_leader(department_name)
    if person is None:
        return ApiResponse(code=404, message=f"未找到部门 '{department_name}' 或其负责人")
    return ApiResponse(data=DepartmentLeaderResponse(
        department=person.department or department_name,
        leader_name=person.name,
        leader_id=person.id or None,
    ))


@hazards_router.get("/hazards/department-safety-officer", response_model=ApiResponse, summary="查询部门分管安全员")
async def get_department_safety_officer(
    department_name: str = Query(..., min_length=1, description="部门名称"),
    db: AsyncSession = Depends(get_db),
):
    """根据部门名称查询分管安全员姓名。

    数据来源：DEPARTMENT_CONFIG（人工维护），仅返回已配置安全员的部门。
    未配置安全员的部门返回 404。
    """
    from app.modules.safety.feishu import IdentityResolver

    resolver = IdentityResolver(db)
    person = await resolver.resolve_safety_officer(department_name)
    if person is None:
        return ApiResponse(code=404, message=f"未找到部门 '{department_name}' 的安全员")
    return ApiResponse(data=DepartmentSafetyOfficerResponse(
        department=person.department or department_name,
        safety_officer_name=person.name,
        safety_officer_id=person.id or None,
    ))


@hazards_router.get("/hazards/{hazard_id}", response_model=ApiResponse, summary="获取隐患详情")
async def get_hazard(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取隐患详情"""
    service = HazardService(db)
    item = await service.get_hazard(hazard_id)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post("/hazards", response_model=ApiResponse, summary="创建隐患")
async def create_hazard(
    data: HazardReportCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """创建隐患（AI 识别不在此处执行——调用方应在图片上传完成后通过
    POST /hazards/{id}/ai/run/1 手动触发，与 Bitable 同步流程对齐）。"""
    service = HazardService(db)
    item = await service.create_hazard(data, auto_run_ai=False)
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.put("/hazards/{hazard_id}", response_model=ApiResponse, summary="更新隐患")
async def update_hazard(
    hazard_id: uuid.UUID,
    data: HazardReportUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新隐患"""
    service = HazardService(db)
    item = await service.update_hazard(hazard_id, data)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post(
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

    file_ext = os.path.splitext(file.filename or ".png")[1]
    safe_name = f"hazard_{hazard_id}_{int(datetime.now().timestamp())}{file_ext}"
    content = await file.read()

    if minio_enabled():
        object_key = f"hazard/{safe_name}"
        upload_object("safety", object_key, content, len(content), file.content_type or "image/jpeg")
        stored_path = object_key
    else:
        upload_dir = os.path.join("uploads", "safety", "hazard")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)
        # Store path relative to uploads/ to avoid double-prefix when serving
        # (serve_file joins with ./uploads/ → ./uploads/safety/hazard/file.jpg)
        stored_path = os.path.join("safety", "hazard", safe_name)

    service = HazardService(db)
    item = await service.upload_hazard_photo(hazard_id, file.filename or "unknown", stored_path)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post(
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

    file_ext = os.path.splitext(file.filename or ".png")[1]
    safe_name = f"rectification_{hazard_id}_{int(datetime.now().timestamp())}{file_ext}"
    content = await file.read()

    if minio_enabled():
        object_key = f"hazard/{safe_name}"
        upload_object("safety", object_key, content, len(content), file.content_type or "image/jpeg")
        stored_path = object_key
    else:
        upload_dir = os.path.join("uploads", "safety", "hazard")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, safe_name)
        with open(file_path, "wb") as f:
            f.write(content)
        # Store path relative to uploads/ to avoid double-prefix when serving
        stored_path = os.path.join("safety", "hazard", safe_name)

    service = HazardService(db)
    item = await service.upload_rectification_photo(hazard_id, stored_path)
    if not item:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post(
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
    service = HazardService(db)
    item = await service.start_rectification(hazard_id)
    if not item:
        return ApiResponse(code=400, message="无法开始整改，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post(
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
    """责任人提交整改回复（含纠正预防措施），rectification_status: in_progress → replied"""
    service = HazardService(db)
    item = await service.reply_rectification(
        hazard_id,
        reply_content=data.reply_content,
        rectification_photos=data.rectification_photos,
        corrective_preventive_measures=data.corrective_preventive_measures,
        rectification_reply=data.rectification_reply,
        actual_completion_date=data.actual_completion_date,
    )
    if not item:
        return ApiResponse(code=400, message="无法回复，当前状态不允许")
    await db.commit()
    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post(
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
    service = HazardService(db)
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


@hazards_router.post(
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
    service = HazardService(db)
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


@hazards_router.delete("/hazards/{hazard_id}", response_model=ApiResponse, summary="删除隐患")
async def delete_hazard(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """删除隐患"""
    service = HazardService(db)
    result = await service.delete_hazard(hazard_id)
    if not result:
        return ApiResponse(code=404, message="隐患不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


@hazards_router.post(
    "/hazards/{hazard_id}/ai/run/{script_number}",
    response_model=ApiResponse,
    summary="执行隐患AI工作流",
)
async def run_hazard_ai(
    hazard_id: uuid.UUID,
    script_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """执行隐患AI工作流脚本。AI从已有数据库数据读取上下文，无需额外传入参数。

    没有 body 参数——FastAPI 不会解析请求 body，避免空 body + JSON Content-Type 触发 422。
    """
    service = HazardService(db)
    item = await service.run_hazard_ai_script(hazard_id, script_number)
    if item is None:
        return ApiResponse(code=400, message="无法执行AI工作流，当前状态不允许或前置步骤未完成")
    await db.commit()

    # AI 识别完成后异步通知责任人整改（与 Bitable 同步流程对齐：
    # _create_hazard_from_bitable → AI 完成 → _send_rectification_notification）
    if script_number == 1 and item and not item.ai_error_message:
        asyncio.create_task(_send_rectification_notification(item))

    return ApiResponse(data=HazardReportResponse.model_validate(item))


@hazards_router.post(
    "/hazards/{hazard_id}/rectification/notify-reviewer",
    response_model=ApiResponse,
    summary="飞书通知当前复核人",
)
async def notify_reviewer(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发飞书通知，提醒当前复核阶段的责任人进行复核。

    根据隐患当前状态自动判断复核级别：
    - 待部门负责人复核（level 1）→ 通知部门负责人
    - 待分管领导复核（level 2）→ 通知分管领导
    - 待检查人员复核（level 3）→ 通知检查人员
    """
    service = HazardService(db)
    hazard = await service.repo.get_hazard_by_id(hazard_id)
    if not hazard:
        return ApiResponse(code=404, message="隐患不存在")

    # 判断当前复核级别（与前端 currentLevel 逻辑一致）
    rstatus = hazard.rectification_status
    is_general = hazard.hazard_level == "general"
    v1 = hazard.verify_level_1_status
    v2 = hazard.verify_level_2_status
    v3 = hazard.verify_level_3_status
    v1_done = v1 in ("approved", "rejected")
    v2_done = v2 in ("approved", "rejected")
    v3_done = v3 in ("approved", "rejected")

    current_level = None
    if rstatus and rstatus not in ("pending", "in_progress"):
        if not v1_done:
            current_level = 1
        elif not is_general and not v2_done:
            current_level = 2
        elif not v3_done:
            current_level = 3

    if current_level is None:
        return ApiResponse(code=400, message="当前无需复核，无法发送通知")

    level_labels = {1: "部门负责人", 2: "分管领导", 3: "检查人员"}

    # 异步发送飞书通知，不阻塞响应
    asyncio.create_task(_send_verify_notification(hazard, current_level))

    return ApiResponse(
        message=f"已向{level_labels[current_level]}发送飞书通知",
        data={"level": current_level, "level_label": level_labels[current_level]},
    )


@hazards_router.post(
    "/hazards/{hazard_id}/rectification/review",
    response_model=ApiResponse,
    summary="触发整改回复 AI 初审",
)
async def trigger_rectification_review(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发整改回复 AI 初审（异步执行，不阻塞响应）。

    适用场景：
    - AI 初审失败后重试
    - 前端手动触发重新审查
    """
    service = HazardService(db)
    hazard = await service.repo.get_hazard_by_id(hazard_id)
    if not hazard:
        return ApiResponse(code=404, message="隐患不存在")

    if hazard.rectification_status not in ("replied",):
        return ApiResponse(
            code=400,
            message="当前整改状态不允许触发 AI 初审，仅「已回复」状态可触发",
        )

    # 异步执行，不阻塞 HTTP 响应
    asyncio.create_task(service.run_rectification_review(hazard_id))

    return ApiResponse(message="AI 初审已触发，正在异步处理中")


@hazards_router.post(
    "/hazards/{hazard_id}/rectification/notify-rectification",
    response_model=ApiResponse,
    summary="飞书通知整改责任人",
)
async def notify_rectification(
    hazard_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动触发飞书通知，提醒整改责任人进行整改回复。"""
    service = HazardService(db)
    hazard = await service.repo.get_hazard_by_id(hazard_id)
    if not hazard:
        return ApiResponse(code=404, message="隐患不存在")

    # 异步发送飞书通知，不阻塞响应
    asyncio.create_task(_send_rectification_notification(hazard))

    return ApiResponse(
        message="已向整改责任人发送飞书通知",
        data={"target": hazard.rectification_responsible_person_name or "未知"},
    )


@hazards_router.get(
    "/hazards/catch-up/diagnose",
    response_model=ApiResponse,
    summary="Bitable 漏单诊断",
)
async def diagnose_bitable_catch_up(
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """诊断 Bitable 多维表格中是否有在 WebSocket 断线期间被遗漏的记录。

    使用飞书 Bitable 系统字段「修改时间」做精准增量查询：
    - 获取本地最新记录的 updated_at 作为时间下界
    - 查询 Bitable 中 last_modified_time > 此值的记录
    - 按 feishu_record_id 比对，找出本地不存在的记录

    纯查询操作，不修改数据库或 Bitable 中的任何数据。

    返回字段：
    - cutoff_time: 时间下界（ISO 格式）
    - bitable_matched: 查询窗口内 Bitable 返回的记录总数
    - local_total: 本地已关联 feishu_record_id 的记录数
    - missed: 漏单数（Bitable 有但本地没有），-1 表示诊断失败
    - existing: 两边都存在的记录数
    - missed_records: 漏单详情（最多 50 条，含 record_id + 关键字段）
    """
    from app.modules.safety.feishu.catch_up import diagnose_missed_records

    result = await diagnose_missed_records(db)
    return ApiResponse(data=result)

