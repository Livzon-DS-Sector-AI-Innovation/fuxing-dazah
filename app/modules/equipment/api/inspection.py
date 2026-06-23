"""巡检 API 路由."""

import os
import uuid
from io import BytesIO

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser
from app.core.exceptions import AppException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.equipment import repository as repo
from app.modules.equipment.schemas.inspection import (
    EquipmentCheckResult,
    InspectionAIAnalyzeRequest,
    InspectionAIItemResult,
    InspectionPhotoResponse,
    InspectionRecordResponse,
    InspectionRouteCreate,
    InspectionRouteDetailResponse,
    InspectionRouteResponse,
    InspectionRouteUpdate,
    InspectionScheduleCreate,
    InspectionScheduleResponse,
    InspectionScheduleUpdate,
    InspectionTaskClose,
    InspectionTaskCreate,
    InspectionTaskDetailResponse,
    InspectionTaskResponse,
    RouteCheckSubmit,
    RouteEquipmentTemplateResponse,
    RouteLocationEquipmentResponse,
    RouteLocationResponse,
    RouteLocationsBatch,
)
from app.modules.equipment.service import inspection as inspection_svc

router = APIRouter()


def _require_user(current_user: CurrentUser) -> uuid.UUID:
    if not current_user:
        raise AppException(message="需要登录才能执行此操作", status_code=401)
    return current_user.id


def _task_to_response(task) -> InspectionTaskResponse:
    """将 ORM InspectionTask 转为响应对象，填充关联名称。
    要求调用方已通过 selectinload 预加载 route/equipment/template 关系。"""
    resp = InspectionTaskResponse.model_validate(task)
    if task.equipment_ids:
        resp.equipment_count = len(task.equipment_ids)
    elif task.route and task.route.locations_rel:
        count = 0
        for loc in task.route.locations_rel:
            count += len(loc.equipments or [])
        resp.equipment_count = count
    if task.route:
        resp.route_name = task.route.name
    if task.equipment:
        resp.equipment_name = task.equipment.name
        resp.equipment_no = task.equipment.equipment_no
    if hasattr(task, "assignee") and task.assignee:
        resp.assignee_name = task.assignee.name
    return resp


async def _enrich_multi_device_names(
    db: AsyncSession, responses: list[InspectionTaskResponse]
) -> None:
    """为多设备任务（无 route、无单 equipment）补充 equipment_name 显示名"""
    # 收集需要查询设备名称的任务
    need_enrich: list[InspectionTaskResponse] = []
    all_eq_ids: set[uuid.UUID] = set()
    for resp in responses:
        if (
            not resp.equipment_name
            and resp.equipment_ids
            and len(resp.equipment_ids) > 0
        ):
            need_enrich.append(resp)
            for eid in resp.equipment_ids:
                all_eq_ids.add(eid)

    if not need_enrich:
        return

    name_map = await repo.get_equipment_names_by_ids(
        db, list(all_eq_ids)
    )
    for resp in need_enrich:
        names = [
            name_map.get(eid, str(eid)[:8] + "…")
            for eid in (resp.equipment_ids or [])
            if eid is not None
        ]
        if names:
            resp.equipment_name = "、".join(names[:3])
            if len(names) > 3:
                resp.equipment_name += f" 等{len(names)}台"


# ═══════════ 巡检路线 ═══════════
@router.post("/routes", summary="创建巡检路线")
async def create_route(
    data: InspectionRouteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    route = await inspection_svc.create_route(db, data.model_dump())
    return success_response(
        data=InspectionRouteResponse.model_validate(route)
    )


@router.get("/routes", summary="巡检路线列表")
async def list_routes(
    is_active: bool | None = Query(None, description="是否启用"),
    location_id: uuid.UUID | None = Query(None, description="按地点筛选"),
    keyword: str | None = Query(None, description="关键词搜索"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    routes, total = await inspection_svc.get_routes(
        db,
        is_active=is_active,
        location_id=location_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    resp_list = []
    for r in routes:
        resp = InspectionRouteResponse.model_validate(r)
        # 统计未删除的地点下的未删除设备
        count = 0
        for loc in (r.locations_rel or []):
            count += len([e for e in (loc.equipments or []) if not e.is_deleted])
        resp.equipment_count = count
        resp.location_count = len(r.locations_rel or [])
        resp_list.append(resp)
    return paginated_response(
        data=resp_list,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/routes/{route_id}", summary="巡检路线详情")
async def get_route(
    route_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await inspection_svc.get_route_by_id(db, route_id)
    resp = InspectionRouteDetailResponse.model_validate(route)
    resp.locations = [
        RouteLocationResponse(
            id=loc.id,
            location_id=loc.location_id,
            location_name=loc.location.name if loc.location else None,
            sort_order=loc.sort_order,
            equipments=[
                RouteLocationEquipmentResponse(
                    id=eq.id,
                    equipment_id=eq.equipment_id,
                    sort_order=eq.sort_order,
                    equipment_name=(
                        eq.equipment.name
                        if (eq.equipment and not eq.equipment.is_deleted)
                        else None
                    ),
                    equipment_no=(
                        eq.equipment.equipment_no
                        if (eq.equipment and not eq.equipment.is_deleted)
                        else None
                    ),
                    templates=[
                        RouteEquipmentTemplateResponse(
                            id=rt.id,
                            template_id=rt.template_id,
                            template_name=rt.template.name if rt.template else None,
                        )
                        for rt in (eq.templates_rel or [])
                    ],
                )
                for eq in (loc.equipments or [])
            ],
        )
        for loc in (route.locations_rel or [])
    ]
    return success_response(data=resp)


@router.put("/routes/{route_id}", summary="更新巡检路线")
async def update_route(
    route_id: uuid.UUID,
    data: InspectionRouteUpdate,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    update_data = data.model_dump(exclude_unset=True)
    route = await inspection_svc.update_route(db, route_id, update_data)
    return success_response(
        data=InspectionRouteResponse.model_validate(route)
    )


@router.delete("/routes/{route_id}", summary="删除巡检路线")
async def delete_route(
    route_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await inspection_svc.delete_route(db, route_id)
    return success_response(message="删除成功")


@router.post(
    "/routes/{route_id}/locations", summary="配置路线地点设备模板"
)
async def set_route_locations(
    route_id: uuid.UUID,
    data: RouteLocationsBatch,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items = [item.model_dump() for item in data.locations]
    locations = await inspection_svc.set_route_locations(db, route_id, items)
    resp_list = [
        RouteLocationResponse(
            id=loc.id,
            location_id=loc.location_id,
            location_name=loc.location.name if loc.location else None,
            sort_order=loc.sort_order,
            equipments=[
                RouteLocationEquipmentResponse(
                    id=eq.id,
                    equipment_id=eq.equipment_id,
                    sort_order=eq.sort_order,
                    equipment_name=eq.equipment.name if eq.equipment else None,
                    equipment_no=eq.equipment.equipment_no if eq.equipment else None,
                    templates=[
                        RouteEquipmentTemplateResponse(
                            id=rt.id,
                            template_id=rt.template_id,
                            template_name=rt.template.name if rt.template else None,
                        )
                        for rt in (eq.templates_rel or [])
                    ],
                )
                for eq in (loc.equipments or [])
            ],
        )
        for loc in locations
    ]
    return success_response(data=resp_list)


# ═══════════ 巡检任务 ═══════════
@router.post("/tasks", summary="创建巡检任务")
async def create_task(
    data: InspectionTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    task = await inspection_svc.create_task(db, data.model_dump())
    return success_response(data=_task_to_response(task))


@router.get("/tasks", summary="巡检任务列表")
async def list_tasks(
    status: str | None = Query(None, description="任务状态"),
    exclude_status: str | None = Query(None, description="排除的任务状态"),
    route_id: uuid.UUID | None = Query(None, description="路线ID"),
    assigned_to: uuid.UUID | None = Query(None, description="巡检人员ID"),
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    planned_time_from: str | None = Query(
        None, description="计划时间起始"
    ),
    planned_time_to: str | None = Query(
        None, description="计划时间截止"
    ),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from datetime import datetime as dt_type

    pt_from = (
        dt_type.fromisoformat(planned_time_from)
        if planned_time_from
        else None
    )
    pt_to = (
        dt_type.fromisoformat(planned_time_to)
        if planned_time_to
        else None
    )

    tasks, total = await inspection_svc.get_tasks(
        db,
        status=status,
        exclude_status=exclude_status,
        route_id=route_id,
        assigned_to=assigned_to,
        equipment_id=equipment_id,
        planned_time_from=pt_from,
        planned_time_to=pt_to,
        page=page,
        page_size=page_size,
    )
    resp_list = [_task_to_response(t) for t in tasks]
    await _enrich_multi_device_names(db, resp_list)
    return paginated_response(
        data=resp_list,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/tasks/{task_id}", summary="巡检任务详情")
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    task = await inspection_svc.get_task_by_id(db, task_id)
    resp = _task_to_response(task)
    # 填充已完成设备列表
    completed_ids = await repo.get_task_equipment_completed_ids(db, task_id)
    resp.completed_equipment_ids = list(completed_ids)
    resp.completed_count = len(completed_ids)
    return success_response(data=resp)


@router.put("/tasks/{task_id}/start", summary="开始巡检")
async def start_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    task = await inspection_svc.start_task(db, task_id)
    return success_response(data=_task_to_response(task))


@router.put("/tasks/{task_id}/complete", summary="提交完成")
async def complete_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    task = await inspection_svc.complete_task(db, task_id)
    return success_response(data=_task_to_response(task))


@router.post("/tasks/{task_id}/route-check", summary="提交线路巡检结果")
async def submit_route_check(
    task_id: uuid.UUID,
    data: RouteCheckSubmit,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    task = await inspection_svc.submit_route_check(
        db, task_id, data.overall_result, data.route_summary
    )
    return success_response(data=_task_to_response(task))


@router.put("/tasks/{task_id}/close", summary="关闭任务")
async def close_task(
    task_id: uuid.UUID,
    data: InspectionTaskClose | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    task = await inspection_svc.close_task(
        db, task_id, data.closure_remark if data else None
    )
    return success_response(data=_task_to_response(task))


# ═══════════ 巡检执行 ═══════════
@router.post(
    "/tasks/{task_id}/equipments/{equipment_id}/check",
    summary="提交设备检查结果",
)
async def submit_equipment_check(
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    data: EquipmentCheckResult,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    records = [r.model_dump() for r in data.records]
    result = await inspection_svc.submit_equipment_check(
        db, task_id, equipment_id, records
    )
    return success_response(
        data=[
            InspectionRecordResponse.model_validate(r) for r in result
        ]
    )


@router.post(
    "/tasks/{task_id}/equipments/{equipment_id}/photos",
    summary="上传到位照片",
)
async def upload_equipment_photo(
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    file: UploadFile = File(..., description="照片文件"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    _require_user(current_user)
    photo = await inspection_svc.upload_photo(
        db, task_id, equipment_id, file
    )
    return success_response(
        data=InspectionPhotoResponse.model_validate(photo)
    )


@router.post(
    "/tasks/{task_id}/photos",
    summary="上传任务级照片（线路巡检用）",
)
async def upload_task_photo(
    task_id: uuid.UUID,
    file: UploadFile = File(..., description="照片文件"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    _require_user(current_user)
    photo = await inspection_svc.upload_photo(
        db, task_id, equipment_id=None, file=file
    )
    return success_response(
        data=InspectionPhotoResponse.model_validate(photo)
    )


@router.get("/tasks/{task_id}/photos", summary="获取任务所有照片")
async def get_task_photos(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    photos = await inspection_svc.get_task_photos(db, task_id)
    return success_response(
        data=[
            InspectionPhotoResponse.model_validate(p) for p in photos
        ]
    )


@router.get("/photos/{photo_id}/file", summary="查看照片文件")
async def serve_photo(
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    from app.core.storage import get_object
    from app.core.storage import is_enabled as minio_enabled

    photo = await repo.get_photo_by_id(db, photo_id)
    if not photo:
        raise NotFoundException("照片", str(photo_id))

    if minio_enabled():
        result = get_object("equipment", photo.file_path)
        if result is None:
            raise NotFoundException("照片文件")
        data, content_type = result
        return StreamingResponse(BytesIO(data), media_type=content_type)

    # 本地文件系统模式
    if not os.path.exists(photo.file_path):
        raise NotFoundException("照片文件")
    return FileResponse(photo.file_path)


@router.delete(
    "/tasks/{task_id}/photos/{photo_id}", summary="删除照片"
)
async def remove_photo(
    task_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
) -> JSONResponse:
    _require_user(current_user)
    await inspection_svc.delete_photo(db, photo_id)
    return success_response(message="照片已删除")


# ═══════════ AI 分析 ═══════════
@router.post(
    "/tasks/{task_id}/equipments/{equipment_id}/ai-analyze",
    summary="AI 分析巡检照片",
)
async def ai_analyze_photo(
    task_id: uuid.UUID,
    equipment_id: uuid.UUID,
    data: InspectionAIAnalyzeRequest,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.modules.equipment.service.ai import analyze_inspection_photo

    results = await analyze_inspection_photo(
        db=db,
        task_id=task_id,
        equipment_id=equipment_id,
        image_base64=data.image_base64,
        image_mime_type=data.image_mime_type,
    )
    return success_response(
        data=[
            InspectionAIItemResult(
                template_item_id=uuid.UUID(r["template_item_id"]),
                item_name=r["item_name"],
                expected_result=r["expected_result"],
                result=r["result"],
                actual_value=r["actual_value"],
                remark=r["remark"],
            )
            for r in results
        ]
    )


# ═══════════ 历史 ═══════════
@router.get("/history", summary="巡检历史记录")
async def get_history(
    date_from: str | None = Query(None, description="起始日期"),
    date_to: str | None = Query(None, description="截止日期"),
    equipment_id: uuid.UUID | None = Query(None, description="设备ID"),
    route_id: uuid.UUID | None = Query(None, description="路线ID"),
    result: str | None = Query(None, description="巡检结果"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from datetime import date as date_type

    d_from = date_type.fromisoformat(date_from) if date_from else None
    d_to = date_type.fromisoformat(date_to) if date_to else None

    tasks, total = await inspection_svc.get_history(
        db,
        date_from=d_from,
        date_to=d_to,
        equipment_id=equipment_id,
        route_id=route_id,
        result=result,
        page=page,
        page_size=page_size,
    )
    resp_list = [_task_to_response(t) for t in tasks]
    await _enrich_multi_device_names(db, resp_list)
    return paginated_response(
        data=resp_list,
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/history/{task_id}", summary="巡检历史详情")
async def get_history_detail(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await inspection_svc.get_task_detail(db, task_id)
    resp = _task_to_response(detail["task"])
    await _enrich_multi_device_names(db, [resp])

    # 收集所有涉及到的 equipment_id，批量查询名称
    record_eq_ids: set[uuid.UUID] = set()
    for r in detail["records"]:
        if r.equipment_id:
            record_eq_ids.add(r.equipment_id)
    eq_name_map = await repo.get_equipment_names_by_ids(
        db, list(record_eq_ids)
    ) if record_eq_ids else {}

    model = InspectionTaskDetailResponse(
        **resp.model_dump(),
        records=[
            InspectionRecordResponse(
                id=r.id,
                task_id=r.task_id,
                equipment_id=r.equipment_id,
                equipment_name=eq_name_map.get(r.equipment_id) if r.equipment_id else None,
                template_item_id=r.template_item_id,
                result=r.result,
                actual_value=r.actual_value,
                remark=r.remark,
                item_name=(
                    r.template_item.item_name
                    if r.template_item
                    else None
                ),
                expected_result=(
                    r.template_item.expected_result
                    if r.template_item
                    else None
                ),
                created_at=r.created_at,
            )
            for r in detail["records"]
        ],
        photos=[
            InspectionPhotoResponse.model_validate(p)
            for p in detail["photos"]
        ],
    )
    return success_response(data=model)


# ═══════════ 路线定时任务 ═══════════

@router.get(
    "/routes/{route_id}/schedules",
    summary="获取路线定时任务列表",
)
async def list_schedules(
    route_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    schedules = await inspection_svc.get_schedules_by_route(db, route_id)
    return success_response(schedules)


@router.post(
    "/routes/{route_id}/schedules",
    summary="创建定时任务",
)
async def create_schedule(
    route_id: uuid.UUID,
    body: InspectionScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
):
    _require_user(current_user)
    data = body.model_dump(exclude_unset=True)
    schedule = await inspection_svc.create_schedule(db, route_id, data)
    return success_response(InspectionScheduleResponse.model_validate(schedule))


@router.put(
    "/routes/{route_id}/schedules/{schedule_id}",
    summary="更新定时任务",
)
async def update_schedule(
    route_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: InspectionScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
):
    _require_user(current_user)
    data = body.model_dump(exclude_unset=True)
    schedule = await inspection_svc.update_schedule(db, schedule_id, data)
    if str(schedule.route_id) != str(route_id):
        raise NotFoundException("定时任务", str(schedule_id))
    return success_response(InspectionScheduleResponse.model_validate(schedule))


@router.delete(
    "/routes/{route_id}/schedules/{schedule_id}",
    summary="删除定时任务",
)
async def delete_schedule(
    route_id: uuid.UUID,
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = None,
):
    _require_user(current_user)
    schedule = await repo.get_schedule_by_id(db, schedule_id)
    if not schedule or str(schedule.route_id) != str(route_id):
        raise NotFoundException("定时任务", str(schedule_id))
    await inspection_svc.delete_schedule(db, schedule_id)
    return success_response(None)
