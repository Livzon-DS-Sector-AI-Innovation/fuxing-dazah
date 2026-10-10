"""物料容器赋码 API：批量赋码、台账查询、进出库、标签下载。"""

from io import BytesIO
from urllib.parse import quote

from fastapi import Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.quality.api._common import router
from app.modules.quality.repository import (
    get_material_container_by_no,
    list_container_movements,
    list_material_containers,
)
from app.modules.quality.schemas import (
    ContainerBatchMoveRequest,
    ContainerLabelRequest,
    ContainerMovementOut,
    ContainerMoveRequest,
    ContainerStatusUpdate,
    MaterialContainerGenerateRequest,
    MaterialContainerListItem,
    MaterialContainerOut,
)
from app.modules.quality.service import material_container_service
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission


@router.post("/material/containers/generate", summary="批量赋码：生成连续容器号（MC-物料代码-日期-流水）")
async def generate_containers_endpoint(
    payload: MaterialContainerGenerateRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    containers = await material_container_service.generate_containers(db, payload, issued_by=user.id)
    return success_response(
        data=[MaterialContainerListItem.model_validate(c).model_dump(mode="json") for c in containers],
        message=f"已赋码 {len(containers)} 个容器（{containers[0].container_no} 起）" if containers else "已赋码 0 个容器",
    )


@router.get("/material/containers", summary="物料容器台账列表")
async def list_containers_endpoint(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None, description="状态筛选"),
    batch_no: str | None = Query(default=None, description="进厂批号模糊搜索"),
    material_code: str | None = Query(default=None, description="物料代码模糊搜索"),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    rows, total = await list_material_containers(
        db, page=page, page_size=page_size, status=status, batch_no=batch_no, material_code=material_code
    )
    items = [MaterialContainerListItem.model_validate(r).model_dump(mode="json") for r in rows]
    return paginated_response(data=items, total=total, page=page, page_size=page_size)


@router.post("/material/containers/batch-move", summary="批量进出库（逐容器独立校验，返回逐条结果）")
async def batch_move_endpoint(
    payload: ContainerBatchMoveRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    results = await material_container_service.batch_move(db, payload, operator=user.id)
    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count
    return success_response(
        data={"results": results, "updated": ok_count, "failed": fail_count},
        message=f"已处理 {ok_count} 个容器" + (f"，失败 {fail_count} 个（详见结果）" if fail_count else ""),
    )


@router.get("/material/containers/{container_no}", summary="按容器号查询（扫码入口共用）")
async def get_container_endpoint(
    container_no: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> JSONResponse:
    container = await get_material_container_by_no(db, container_no)
    if container is None:
        raise HTTPException(status_code=404, detail=f"容器 {container_no} 不存在")
    movements = await list_container_movements(db, container.id)
    return success_response(data={
        "container": MaterialContainerOut.model_validate(container).model_dump(mode="json"),
        "movements": [ContainerMovementOut.model_validate(m).model_dump(mode="json") for m in movements],
    })


@router.post("/material/containers/{container_no}/move", summary="进出库：in 入库登记 / out 领料出库")
async def move_container_endpoint(
    container_no: str,
    payload: ContainerMoveRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    container = await material_container_service.move_container(db, container_no, payload, operator=user.id)
    return success_response(
        data=MaterialContainerOut.model_validate(container).model_dump(mode="json"),
        message="已入库登记" if payload.op_type == "in" else "已领料出库",
    )


@router.put("/material/containers/{container_no}/status", summary="人工状态流转（阶段1：手动合格/作废）")
async def update_container_status_endpoint(
    container_no: str,
    payload: ContainerStatusUpdate = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("quality:material:manage")),
) -> JSONResponse:
    container = await material_container_service.update_status(db, container_no, payload.status, operator=user.id)
    return success_response(
        data=MaterialContainerOut.model_validate(container).model_dump(mode="json"),
        message=f"状态已变更为 {payload.status}",
    )


@router.post("/material/containers/label", summary="批量标签 PDF（A4 不干胶 2×4 排版）")
async def container_label_endpoint(
    payload: ContainerLabelRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("quality:material:read")),
) -> StreamingResponse:
    pdf_bytes = await material_container_service.build_label_pdf(db, payload.container_nos)
    encoded = quote(f"物料标签-{len(payload.container_nos)}张.pdf")
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="labels.pdf"; filename*=UTF-8\'\'{encoded}'},
    )
