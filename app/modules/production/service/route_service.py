"""产品与工艺路线配置：CRUD、整图保存、发布校验、版本复制。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production import repository as repo
from app.modules.production.models import (
    NodeFieldDef,
    ProcessRoute,
    Product,
    RouteEdge,
    RouteNode,
    RouteNodeIntermediate,
)
from app.modules.production.schemas import (
    EdgeOut,
    FieldDefOut,
    NodeIntermediateOut,
    NodeOut,
    ProductCreate,
    ProductUpdate,
    RouteCreate,
    RouteGraphIn,
    RouteGraphOut,
    RouteOut,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

# ── 产品 ──


async def create_product(
    db: AsyncSession, payload: ProductCreate, user: User | None
) -> Product:
    if await repo.get_product_by_name(db, payload.product_name):
        raise DuplicateException("产品名称", payload.product_name)
    product = Product(
        product_code=payload.product_code,
        product_name=payload.product_name,
        unit=payload.unit,
        remark=payload.remark,
        created_by=user.id if user else None,
    )
    db.add(product)
    await db.flush()
    return product


async def update_product(
    db: AsyncSession, product_id: uuid.UUID, payload: ProductUpdate, user: User | None
) -> Product:
    product = await repo.get_product(db, product_id)
    if not product:
        raise NotFoundException("产品", str(product_id))
    if payload.product_name is not None:
        product.product_name = payload.product_name
    if payload.unit is not None:
        product.unit = payload.unit
    if payload.remark is not None:
        product.remark = payload.remark
    product.updated_by = user.id if user else None
    await db.flush()
    # UPDATE 后 re-fetch（铁律）
    refreshed = await repo.get_product(db, product_id)
    assert refreshed is not None
    return refreshed


async def delete_product(
    db: AsyncSession, product_id: uuid.UUID, user: User | None
) -> None:
    product = await repo.get_product(db, product_id)
    if not product:
        raise NotFoundException("产品", str(product_id))
    unfinished = await repo.count_unfinished_batches(db, product_id)
    if unfinished:
        raise AppException(
            status_code=400,
            message=f"该产品还有 {unfinished} 个未完成批次，请先完成或报废后再删除",
        )
    product.is_deleted = True
    product.updated_by = user.id if user else None
    await db.flush()


# ── 路线 ──


async def create_route(
    db: AsyncSession, payload: RouteCreate, user: User | None
) -> ProcessRoute:
    if not await repo.get_product(db, payload.product_id):
        raise NotFoundException("产品", str(payload.product_id))
    route = ProcessRoute(
        product_id=payload.product_id,
        version=await repo.next_route_version(db, payload.product_id),
        name=payload.name,
        status="draft",
        created_by=user.id if user else None,
    )
    db.add(route)
    await db.flush()
    return route


async def _get_route_or_404(db: AsyncSession, route_id: uuid.UUID) -> ProcessRoute:
    route = await repo.get_route(db, route_id)
    if not route:
        raise NotFoundException("工艺路线", str(route_id))
    return route


async def save_graph(
    db: AsyncSession, route_id: uuid.UUID, graph: RouteGraphIn, user: User | None
) -> None:
    """整图保存（仅 draft）：软删旧图后全量重建。draft 不会被批次引用，替换安全。"""
    route = await _get_route_or_404(db, route_id)
    if route.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的路线可编辑")

    codes = [n.node_code for n in graph.nodes]
    if len(codes) != len(set(codes)):
        raise AppException(status_code=400, message="节点编码重复")
    code_set = set(codes)
    for e in graph.edges:
        if e.from_node_code not in code_set or e.to_node_code not in code_set:
            raise AppException(
                status_code=400,
                message=f"边引用了不存在的节点: {e.from_node_code}->{e.to_node_code}",
            )
        if e.edge_type == "rework" and e.is_batch_boundary:
            raise AppException(status_code=400, message="回流边不允许标记批次边界")

    await repo.soft_delete_route_graph(db, route_id)

    node_by_code: dict[str, RouteNode] = {}
    for n in graph.nodes:
        node = RouteNode(
            route_id=route_id,
            node_code=n.node_code,
            name=n.name,
            stage_name=n.stage_name,
            node_type=n.node_type,
            sort_order=n.sort_order,
            created_by=user.id if user else None,
        )
        db.add(node)
        node_by_code[n.node_code] = node
    await db.flush()

    for n in graph.nodes:
        field_keys = [f.field_key for f in n.fields]
        if len(field_keys) != len(set(field_keys)):
            raise AppException(
                status_code=400, message=f"节点 {n.node_code} 的字段键重复"
            )
        for f in n.fields:
            db.add(
                NodeFieldDef(
                    node_id=node_by_code[n.node_code].id,
                    field_key=f.field_key,
                    field_label=f.field_label,
                    field_group=f.field_group,
                    phase=f.phase,
                    data_type=f.data_type,
                    options=f.options,
                    unit=f.unit,
                    required=f.required,
                    min_value=f.min_value,
                    max_value=f.max_value,
                    sort_order=f.sort_order,
                    created_by=user.id if user else None,
                )
            )
    for e in graph.edges:
        db.add(
            RouteEdge(
                route_id=route_id,
                from_node_id=node_by_code[e.from_node_code].id,
                to_node_id=node_by_code[e.to_node_code].id,
                edge_type=e.edge_type,
                is_batch_boundary=e.is_batch_boundary,
                remark=e.remark,
                created_by=user.id if user else None,
            )
        )
    for n in graph.nodes:
        for im in n.intermediates:
            db.add(
                RouteNodeIntermediate(
                    node_id=node_by_code[n.node_code].id,
                    intermediate_type_id=im.intermediate_type_id,
                    direction=im.direction,
                    unit_override=im.unit_override,
                    required=im.required,
                    sort_order=im.sort_order,
                    remark=im.remark,
                    created_by=user.id if user else None,
                )
            )
    await db.flush()


async def get_graph(db: AsyncSession, route_id: uuid.UUID) -> RouteGraphOut:
    route = await _get_route_or_404(db, route_id)
    nodes = await repo.get_route_nodes(db, route_id)
    edges = await repo.get_route_edges(db, route_id)
    defs = await repo.get_field_defs_by_nodes(db, [n.id for n in nodes])
    defs_by_node: dict[uuid.UUID, list[FieldDefOut]] = {}
    for d in defs:
        defs_by_node.setdefault(d.node_id, []).append(FieldDefOut.model_validate(d))
    intermediates = await repo.get_node_intermediates(db, [n.id for n in nodes])
    # 批量查出中间体类型名称
    type_ids = list({im.intermediate_type_id for im in intermediates})
    type_name_map = {t.id: t.name for t in await repo.get_intermediate_types_by_ids(db, type_ids)}
    ims_by_node: dict[uuid.UUID, list[NodeIntermediateOut]] = {}
    for im in intermediates:
        out = NodeIntermediateOut.model_validate(im)
        out.intermediate_type_name = type_name_map.get(im.intermediate_type_id)
        ims_by_node.setdefault(im.node_id, []).append(out)
    node_outs = []
    for n in nodes:
        out = NodeOut.model_validate(n)
        out.fields = defs_by_node.get(n.id, [])
        out.intermediates = ims_by_node.get(n.id, [])
        node_outs.append(out)
    return RouteGraphOut(
        route=RouteOut.model_validate(route),
        nodes=node_outs,
        edges=[EdgeOut.model_validate(e) for e in edges],
    )


def compute_start_nodes(
    nodes: list[RouteNode], edges: list[RouteEdge]
) -> set[uuid.UUID]:
    """起点 = 没有 normal 入边的节点。"""
    node_ids = {n.id for n in nodes}
    has_incoming = {e.to_node_id for e in edges if e.edge_type == "normal"}
    return node_ids - has_incoming


def _validate_graph(nodes: list[RouteNode], edges: list[RouteEdge]) -> None:
    if not nodes:
        raise AppException(status_code=400, message="路线至少需要一个节点")
    node_ids = {n.id for n in nodes}
    normal = [e for e in edges if e.edge_type == "normal"]
    starts = compute_start_nodes(nodes, edges)
    ends = node_ids - {e.from_node_id for e in normal}
    if not starts:
        raise AppException(status_code=400, message="路线缺少起点（正常流转存在环）")
    if not ends:
        raise AppException(status_code=400, message="路线缺少终点（正常流转存在环）")
    # 连通性：从全部起点沿 normal 边 BFS，必须覆盖所有节点
    adjacency: dict[uuid.UUID, list[uuid.UUID]] = {}
    for e in normal:
        adjacency.setdefault(e.from_node_id, []).append(e.to_node_id)
    seen = set(starts)
    queue = list(starts)
    while queue:
        current = queue.pop()
        for nxt in adjacency.get(current, []):
            if nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    if seen != node_ids:
        raise AppException(status_code=400, message="存在从起点不可达的节点")
    # 孤立节点：同时是起点和终点（无入边也无出边），且图中不止一个节点时视为不可达
    if len(nodes) > 1:
        orphans = starts & ends
        if orphans:
            raise AppException(status_code=400, message="存在从起点不可达的节点")
    for e in edges:
        if e.edge_type == "rework" and e.is_batch_boundary:
            raise AppException(status_code=400, message="回流边不允许标记批次边界")


async def publish_route(
    db: AsyncSession, route_id: uuid.UUID, user: User | None
) -> ProcessRoute:
    route = await _get_route_or_404(db, route_id)
    if route.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的路线可发布")
    nodes = await repo.get_route_nodes(db, route_id)
    edges = await repo.get_route_edges(db, route_id)
    _validate_graph(nodes, edges)
    route.status = "published"
    route.updated_by = user.id if user else None
    await db.flush()
    await record_audit_log(
        db,
        action="production.route.publish",
        user=user,
        resource_type="process_route",
        resource_id=route.id,
    )
    refreshed = await repo.get_route(db, route_id)
    assert refreshed is not None
    return refreshed


async def archive_route(
    db: AsyncSession, route_id: uuid.UUID, user: User | None
) -> ProcessRoute:
    route = await _get_route_or_404(db, route_id)
    if route.status != "published":
        raise AppException(status_code=400, message="仅 published 状态的路线可归档")
    route.status = "archived"
    route.updated_by = user.id if user else None
    await db.flush()
    refreshed = await repo.get_route(db, route_id)
    assert refreshed is not None
    return refreshed


async def new_version(
    db: AsyncSession, route_id: uuid.UUID, user: User | None
) -> ProcessRoute:
    """从任意版本复制出新 draft（节点/边/字段定义全量克隆，UUID 重新生成）。"""
    source = await _get_route_or_404(db, route_id)
    new_route = ProcessRoute(
        product_id=source.product_id,
        version=await repo.next_route_version(db, source.product_id),
        name=source.name,
        status="draft",
        created_by=user.id if user else None,
    )
    db.add(new_route)
    await db.flush()

    nodes = await repo.get_route_nodes(db, route_id)
    edges = await repo.get_route_edges(db, route_id)
    defs = await repo.get_field_defs_by_nodes(db, [n.id for n in nodes])

    id_map: dict[uuid.UUID, uuid.UUID] = {}
    for n in nodes:
        clone_id = uuid.uuid4()  # 显式生成：flush 前字段定义/边就要引用它
        db.add(
            RouteNode(
                id=clone_id,
                route_id=new_route.id,
                node_code=n.node_code,
                name=n.name,
                stage_name=n.stage_name,
                node_type=n.node_type,
                sort_order=n.sort_order,
                created_by=user.id if user else None,
            )
        )
        id_map[n.id] = clone_id
    for d in defs:
        db.add(
            NodeFieldDef(
                node_id=id_map[d.node_id],
                field_key=d.field_key,
                field_label=d.field_label,
                field_group=d.field_group,
                phase=d.phase,
                data_type=d.data_type,
                options=d.options,
                unit=d.unit,
                required=d.required,
                min_value=d.min_value,
                max_value=d.max_value,
                sort_order=d.sort_order,
                created_by=user.id if user else None,
            )
        )
    intermediates = await repo.get_node_intermediates(
        db, [n.id for n in nodes]
    )
    for im in intermediates:
        if im.node_id not in id_map:
            continue
        db.add(
            RouteNodeIntermediate(
                node_id=id_map[im.node_id],
                intermediate_type_id=im.intermediate_type_id,
                direction=im.direction,
                unit_override=im.unit_override,
                required=im.required,
                sort_order=im.sort_order,
                remark=im.remark,
                created_by=user.id if user else None,
            )
        )
    for e in edges:
        db.add(
            RouteEdge(
                route_id=new_route.id,
                from_node_id=id_map[e.from_node_id],
                to_node_id=id_map[e.to_node_id],
                edge_type=e.edge_type,
                is_batch_boundary=e.is_batch_boundary,
                remark=e.remark,
                created_by=user.id if user else None,
            )
        )
    await db.flush()
    return new_route


async def delete_route(
    db: AsyncSession, route_id: uuid.UUID, user: User | None
) -> None:
    route = await _get_route_or_404(db, route_id)
    if route.status != "draft":
        raise AppException(status_code=400, message="仅 draft 状态的路线可删除")
    await repo.soft_delete_route_graph(db, route_id)
    route.is_deleted = True
    route.updated_by = user.id if user else None
    await db.flush()


async def list_products_paged(
    db: AsyncSession, keyword: str | None, page: int, page_size: int
) -> tuple[list[Product], int]:
    return await repo.list_products(db, keyword, page, page_size)


async def list_routes_paged(
    db: AsyncSession, product_id: uuid.UUID | None, page: int, page_size: int
) -> tuple[list[ProcessRoute], int]:
    return await repo.list_routes(db, product_id, page, page_size)


async def get_product_or_404(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await repo.get_product(db, product_id)
    if not product:
        raise NotFoundException("产品", str(product_id))
    return product
