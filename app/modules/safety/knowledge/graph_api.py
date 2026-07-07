"""知识图谱 API 路由 — 节点/边 CRUD + 完整图 + 生成触发。"""

import uuid as _uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import CurrentUser, get_current_user
from app.core.response import ApiResponse
from app.modules.safety.knowledge.graph_schemas import (
    GraphEdgeCreate,
    GraphEdgeResponse,
    GraphEdgeUpdate,
    GraphGenerateRequest,
    GraphNodeCreate,
    GraphNodeResponse,
    GraphNodeUpdate,
)
from app.modules.safety.knowledge.graph_service import GraphService

graph_router = APIRouter()

# ═══════════════════════════════════════════════════════════════
# 节点 CRUD
# ═══════════════════════════════════════════════════════════════


@graph_router.get("/knowledge-graph/nodes", response_model=ApiResponse, summary="获取图谱节点列表")
async def list_graph_nodes(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    node_type: str | None = Query(None, description="节点类型"),
    entity_type: str | None = Query(None, description="实体类别"),
    status: str | None = Query(None, description="节点状态"),
    keyword: str | None = Query(None, description="搜索关键词"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取图谱节点列表，支持按类型/实体类别/状态/关键词筛选。"""
    service = GraphService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_nodes(skip, page_size, node_type, entity_type, status, keyword)
    return ApiResponse(
        data=[GraphNodeResponse.model_validate(n) for n in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@graph_router.get("/knowledge-graph/nodes/{node_id}", response_model=ApiResponse, summary="获取图谱节点详情")
async def get_graph_node(
    node_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取单个图谱节点详情（含关联边）。"""
    service = GraphService(db)
    node = await service.get_node(node_id)
    if not node:
        return ApiResponse(code=404, message="节点不存在")
    return ApiResponse(data=GraphNodeResponse.model_validate(node))


@graph_router.post("/knowledge-graph/nodes", response_model=ApiResponse, summary="创建图谱节点")
async def create_graph_node(
    data: GraphNodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动创建图谱节点。"""
    service = GraphService(db)
    node = await service.create_node(data)
    await db.commit()
    return ApiResponse(data=GraphNodeResponse.model_validate(node))


@graph_router.put("/knowledge-graph/nodes/{node_id}", response_model=ApiResponse, summary="更新图谱节点")
async def update_graph_node(
    node_id: _uuid.UUID,
    data: GraphNodeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新图谱节点。"""
    service = GraphService(db)
    node = await service.update_node(node_id, data)
    if not node:
        return ApiResponse(code=404, message="节点不存在")
    await db.commit()
    return ApiResponse(data=GraphNodeResponse.model_validate(node))


@graph_router.delete("/knowledge-graph/nodes/{node_id}", response_model=ApiResponse, summary="删除图谱节点")
async def delete_graph_node(
    node_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """软删除图谱节点（级联删除关联边）。"""
    service = GraphService(db)
    success = await service.delete_node(node_id)
    if not success:
        return ApiResponse(code=404, message="节点不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ═══════════════════════════════════════════════════════════════
# 边 CRUD
# ═══════════════════════════════════════════════════════════════


@graph_router.get("/knowledge-graph/edges", response_model=ApiResponse, summary="获取图谱边列表")
async def list_graph_edges(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    relation_type: str | None = Query(None, description="关系类型"),
    status: str | None = Query(None, description="边状态"),
    source_node_id: _uuid.UUID | None = Query(None, description="源节点 ID"),
    target_node_id: _uuid.UUID | None = Query(None, description="目标节点 ID"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取图谱边列表，支持按关系类型/状态/端点筛选。"""
    service = GraphService(db)
    skip = (page - 1) * page_size
    items, total = await service.get_edges(
        skip, page_size, relation_type, status, source_node_id, target_node_id,
    )
    return ApiResponse(
        data=[GraphEdgeResponse.model_validate(e) for e in items],
        meta={"page": page, "page_size": page_size, "total": total},
    )


@graph_router.get("/knowledge-graph/edges/{edge_id}", response_model=ApiResponse, summary="获取图谱边详情")
async def get_graph_edge(
    edge_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取单条图谱边详情。"""
    service = GraphService(db)
    edge = await service.get_edge(edge_id)
    if not edge:
        return ApiResponse(code=404, message="边不存在")
    return ApiResponse(data=GraphEdgeResponse.model_validate(edge))


@graph_router.post("/knowledge-graph/edges", response_model=ApiResponse, summary="创建图谱边")
async def create_graph_edge(
    data: GraphEdgeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """手动创建图谱边。源/目标节点必须存在。"""
    service = GraphService(db)
    edge = await service.create_edge(data)
    if not edge:
        return ApiResponse(code=400, message="源节点或目标节点不存在")
    await db.commit()
    return ApiResponse(data=GraphEdgeResponse.model_validate(edge))


@graph_router.put("/knowledge-graph/edges/{edge_id}", response_model=ApiResponse, summary="更新图谱边")
async def update_graph_edge(
    edge_id: _uuid.UUID,
    data: GraphEdgeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """更新图谱边。"""
    service = GraphService(db)
    edge = await service.update_edge(edge_id, data)
    if not edge:
        return ApiResponse(code=404, message="边不存在")
    await db.commit()
    return ApiResponse(data=GraphEdgeResponse.model_validate(edge))


@graph_router.delete("/knowledge-graph/edges/{edge_id}", response_model=ApiResponse, summary="删除图谱边")
async def delete_graph_edge(
    edge_id: _uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """软删除图谱边。"""
    service = GraphService(db)
    success = await service.delete_edge(edge_id)
    if not success:
        return ApiResponse(code=404, message="边不存在")
    await db.commit()
    return ApiResponse(message="删除成功")


# ═══════════════════════════════════════════════════════════════
# 完整图 & 搜索 & 展开
# ═══════════════════════════════════════════════════════════════


@graph_router.get("/knowledge-graph/full-graph", response_model=ApiResponse, summary="获取完整知识图谱")
async def get_full_graph(
    node_types: str | None = Query(None, description="节点类型（逗号分隔）"),
    relation_types: str | None = Query(None, description="关系类型（逗号分隔）"),
    max_nodes: int = Query(500, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """获取完整图数据（所有节点 + 边），供前端 React Flow 渲染。"""
    service = GraphService(db)
    nt = node_types.split(",") if node_types else None
    rt = relation_types.split(",") if relation_types else None
    graph = await service.get_full_graph(node_types=nt, relation_types=rt, max_nodes=max_nodes)
    return ApiResponse(data=graph)


@graph_router.get("/knowledge-graph/search", response_model=ApiResponse, summary="搜索图谱节点")
async def search_graph_nodes(
    query: str = Query(..., min_length=1, max_length=500, description="搜索关键词"),
    node_types: str | None = Query(None, description="节点类型（逗号分隔）"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """按关键词搜索图谱节点（匹配名称 + AI 摘要）。"""
    service = GraphService(db)
    nt = node_types.split(",") if node_types else None
    nodes = await service.search_nodes(query, node_types=nt, limit=limit)
    return ApiResponse(data=[GraphNodeResponse.model_validate(n) for n in nodes])


@graph_router.get("/knowledge-graph/expand", response_model=ApiResponse, summary="图展开 — 从节点展开 N-hop 邻居")
async def expand_graph_node(
    node_id: _uuid.UUID = Query(..., description="起始节点 ID"),
    hops: int = Query(1, ge=1, le=3, description="展开跳数"),
    relation_types: str | None = Query(None, description="关系类型（逗号分隔）"),
    max_nodes: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """从指定节点出发，沿边展开 N-hop 邻居子图。"""
    service = GraphService(db)
    rt = relation_types.split(",") if relation_types else None
    graph = await service.expand_node(node_id, hops=hops, relation_types=rt, max_nodes=max_nodes)
    return ApiResponse(data=graph)


# ═══════════════════════════════════════════════════════════════
# AI 生成 (Phase 2 实现)
# ═══════════════════════════════════════════════════════════════


@graph_router.post("/knowledge-graph/generate", response_model=ApiResponse, summary="触发 AI 图谱生成")
async def generate_graph(
    data: GraphGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """触发 AI 图生成任务。

    从 knowledge_articles 读取已发布的法规文档，
    AI 提取实体 → 构建分类体系 → 识别关系 → 写入图谱。
    """
    try:
        from app.modules.safety.knowledge.graph_builder import GraphBuilder

        builder = GraphBuilder(db)
        doc_ids = data.document_ids if data else None
        force = data.force_rebuild if data else False

        result = await builder.build_full_graph(
            document_ids=doc_ids,
            force_rebuild=force,
        )
        await db.commit()

        status = "completed" if result["nodes_created"] > 0 or result["nodes_updated"] > 0 else "completed"
        return ApiResponse(
            data={
                "status": status,
                "nodes_created": result["nodes_created"],
                "edges_created": result["edges_created"],
                "errors": result["errors"],
            },
            message=f"图谱生成完成: {result['nodes_created']} 个节点, {result['edges_created']} 条边",
        )
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.exception("AI 图谱生成失败")
        return ApiResponse(code=500, message=f"图谱生成失败: {e}")


@graph_router.get("/knowledge-graph/generate/status", response_model=ApiResponse, summary="查询 AI 生成状态")
async def get_generate_status(
    task_id: str = Query(..., description="生成任务 ID"),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser | None = Depends(get_current_user),
):
    """查询 AI 图生成任务的进度。Phase 2 实现。"""
    return ApiResponse(
        code=501,
        message="AI 图生成功能将在 Phase 2 实现",
    )
