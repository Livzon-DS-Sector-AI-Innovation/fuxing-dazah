"""生产模块 HTTP 路由。只做 HTTP 层：入参、依赖注入、调 service、统一响应。"""

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.response import paginated_response, success_response
from app.modules.production.schemas import (
    BatchCreate,
    BatchOut,
    DeriveIn,
    ExecutionCompleteIn,
    ExecutionOut,
    ExecutionStartIn,
    IntermediateTypeCreate,
    IntermediateTypeOut,
    IntermediateTypeUpdate,
    MergeIn,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    RouteCreate,
    RouteGraphIn,
    RouteOut,
)
from app.modules.production.service import (
    batch_service,
    execution_service,
    intermediate_service,
    route_service,
    trace_service,
)
from app.platform.identity.models import User
from app.platform.permission.deps import require_permission

router = APIRouter()

_manage = require_permission("production:process:manage")
_submit = require_permission("production:batch:submit")
_read = require_permission("production:batch:read")


# ── 产品 ──


@router.get("/products", summary="产品列表")
async def list_products(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await route_service.list_products_paged(db, keyword, page, page_size)
    return paginated_response(
        [ProductOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/products", summary="新建产品")
async def create_product(
    payload: ProductCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    product = await route_service.create_product(db, payload, user)
    return success_response(ProductOut.model_validate(product).model_dump(mode="json"))


@router.get("/products/{product_id}", summary="产品详情")
async def get_product(
    product_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    product = await route_service.get_product_or_404(db, product_id)
    return success_response(ProductOut.model_validate(product).model_dump(mode="json"))


@router.put("/products/{product_id}", summary="更新产品")
async def update_product(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    product = await route_service.update_product(db, product_id, payload, user)
    return success_response(ProductOut.model_validate(product).model_dump(mode="json"))


@router.delete("/products/{product_id}", summary="删除产品")
async def delete_product(
    product_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await route_service.delete_product(db, product_id, user)
    return success_response()


# ── 工艺路线 ──


@router.get("/routes", summary="工艺路线列表")
async def list_routes(
    product_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await route_service.list_routes_paged(db, product_id, page, page_size)
    return paginated_response(
        [RouteOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/routes", summary="新建工艺路线（draft）")
async def create_route(
    payload: RouteCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.create_route(db, payload, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.get("/routes/{route_id}", summary="工艺路线完整图")
async def get_route_graph(
    route_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    graph = await route_service.get_graph(db, route_id)
    return success_response(graph.model_dump(mode="json"))


@router.put("/routes/{route_id}/graph", summary="整图保存（仅 draft）")
async def save_route_graph(
    route_id: uuid.UUID,
    payload: RouteGraphIn,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await route_service.save_graph(db, route_id, payload, user)
    return success_response()


@router.post("/routes/{route_id}/publish", summary="发布路线")
async def publish_route(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.publish_route(db, route_id, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.post("/routes/{route_id}/archive", summary="归档路线")
async def archive_route(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.archive_route(db, route_id, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.post("/routes/{route_id}/new-version", summary="复制新版本（draft）")
async def new_route_version(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    route = await route_service.new_version(db, route_id, user)
    return success_response(RouteOut.model_validate(route).model_dump(mode="json"))


@router.delete("/routes/{route_id}", summary="删除路线（仅 draft）")
async def delete_route(
    route_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await route_service.delete_route(db, route_id, user)
    return success_response()


# ── 批次 ──


@router.get("/batches", summary="批次列表")
async def list_batches(
    product_id: uuid.UUID | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str = Query("created_at", pattern="^(batch_no|created_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await batch_service.list_batches_paged(
        db, product_id, status, keyword, page, page_size, order_by, order
    )
    return paginated_response(
        [BatchOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/batches", summary="创建起始批次")
async def create_batch(
    payload: BatchCreate,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    batch = await batch_service.create_batch(db, payload, user)
    return success_response(BatchOut.model_validate(batch).model_dump(mode="json"))


@router.get("/batches/{batch_id}", summary="批次详情（含执行时间线）")
async def get_batch_detail(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    detail = await batch_service.get_batch_detail(db, batch_id)
    return success_response(detail.model_dump(mode="json"))


@router.post("/batches/{batch_id}/derive", summary="分裂 / 1→1 换号")
async def derive_batches(
    batch_id: uuid.UUID,
    payload: DeriveIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    children = await batch_service.derive_batches(db, batch_id, payload, user)
    return success_response(
        [BatchOut.model_validate(c).model_dump(mode="json") for c in children]
    )


@router.post("/batches/merge", summary="合并批次")
async def merge_batches(
    payload: MergeIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    child = await batch_service.merge_batches(db, payload, user)
    return success_response(BatchOut.model_validate(child).model_dump(mode="json"))


@router.post("/batches/{batch_id}/complete", summary="批次完成")
async def complete_batch(
    batch_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    batch = await batch_service.complete_batch(db, batch_id, user)
    return success_response(BatchOut.model_validate(batch).model_dump(mode="json"))


@router.post("/batches/{batch_id}/cancel", summary="批次报废")
async def cancel_batch(
    batch_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    batch = await batch_service.cancel_batch(db, batch_id, user)
    return success_response(BatchOut.model_validate(batch).model_dump(mode="json"))


@router.get("/batches/{batch_id}/trace", summary="全链路溯源")
async def get_trace(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    trace = await trace_service.get_trace(db, batch_id)
    return success_response(trace.model_dump(mode="json"))


# ── 工序执行 ──


@router.post("/batches/{batch_id}/executions", summary="开始工序")
async def start_execution(
    batch_id: uuid.UUID,
    payload: ExecutionStartIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    execution = await execution_service.start_execution(db, batch_id, payload, user)
    return success_response(
        ExecutionOut.model_validate(execution).model_dump(mode="json")
    )


@router.post("/executions/{execution_id}/complete", summary="结束工序")
async def complete_execution(
    execution_id: uuid.UUID,
    payload: ExecutionCompleteIn,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    execution = await execution_service.complete_execution(
        db, execution_id, payload, user
    )
    return success_response(
        ExecutionOut.model_validate(execution).model_dump(mode="json")
    )


@router.post("/executions/{execution_id}/abort", summary="中止工序执行")
async def abort_execution(
    execution_id: uuid.UUID,
    user: User = Depends(_submit),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    execution = await execution_service.abort_execution(db, execution_id, user)
    return success_response(
        ExecutionOut.model_validate(execution).model_dump(mode="json")
    )


@router.get("/nodes/{node_id}/executions", summary="工序执行记录（跨批次）")
async def list_node_executions(
    node_id: uuid.UUID,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    order_by: str = Query("started_at", pattern="^(batch_no|started_at)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await execution_service.list_node_executions(
        db, node_id, status, page, page_size, order_by, order
    )
    return paginated_response(
        [i.model_dump(mode="json") for i in items], page, page_size, total
    )


# ── 中间体字典 ──


@router.get("/intermediate-types", summary="中间体字典列表")
async def list_intermediate_types(
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    items, total = await intermediate_service.list_intermediate_types_paged(
        db, keyword, page, page_size
    )
    return paginated_response(
        [IntermediateTypeOut.model_validate(i).model_dump(mode="json") for i in items],
        page,
        page_size,
        total,
    )


@router.post("/intermediate-types", summary="新增中间体字典")
async def create_intermediate_type(
    payload: IntermediateTypeCreate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    obj = await intermediate_service.create_intermediate_type(db, payload, user)
    return success_response(
        IntermediateTypeOut.model_validate(obj).model_dump(mode="json")
    )


@router.get("/intermediate-types/{type_id}", summary="中间体字典详情")
async def get_intermediate_type(
    type_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    from app.modules.production import repository as repo
    obj = await repo.get_intermediate_type(db, type_id)
    if not obj:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("中间体", str(type_id))
    return success_response(
        IntermediateTypeOut.model_validate(obj).model_dump(mode="json")
    )


@router.put("/intermediate-types/{type_id}", summary="编辑中间体字典")
async def update_intermediate_type(
    type_id: uuid.UUID,
    payload: IntermediateTypeUpdate,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    obj = await intermediate_service.update_intermediate_type(db, type_id, payload, user)
    return success_response(
        IntermediateTypeOut.model_validate(obj).model_dump(mode="json")
    )


@router.delete("/intermediate-types/{type_id}", summary="删除中间体字典")
async def delete_intermediate_type(
    type_id: uuid.UUID,
    user: User = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    await intermediate_service.delete_intermediate_type(db, type_id, user)
    return success_response()


# ── 批次中间体台账 ──


@router.get("/batches/{batch_id}/intermediates/outputs", summary="批次中间体产出列表")
async def list_batch_intermediate_outputs(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    outputs = await intermediate_service.get_batch_outputs(db, batch_id)
    return success_response([o.model_dump(mode="json") for o in outputs])


@router.get("/batches/{batch_id}/intermediates/consumptions", summary="批次中间体消耗列表")
async def list_batch_intermediate_consumptions(
    batch_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    consumptions = await intermediate_service.get_batch_consumptions(db, batch_id)
    return success_response([c.model_dump(mode="json") for c in consumptions])


@router.get("/intermediates/outputs/{output_id}/trace", summary="中间体物料流向追溯")
async def trace_intermediate(
    output_id: uuid.UUID,
    user: User = Depends(_read),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """给定一个中间体产出 ID，返回该产出本身及其下游消耗记录。"""
    result = await intermediate_service.trace_intermediate_output(db, output_id)
    return success_response({
        "output": result["output"].model_dump(mode="json"),
        "consumptions": [c.model_dump(mode="json") for c in result["consumptions"]],
    })
