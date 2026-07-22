"""知识图谱 Service 层 — 图节点/边 CRUD + 图查询。"""

import logging
import uuid as _uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.safety.knowledge.graph_models import (
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)
from app.modules.safety.knowledge.graph_schemas import (
    FullGraphResponse,
    GraphEdgeCreate,
    GraphEdgeUpdate,
    GraphNodeCreate,
    GraphNodeUpdate,
)

logger = logging.getLogger(__name__)


class GraphService:
    """知识图谱业务服务 — 节点/边的 CRUD 与图查询。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── 节点 CRUD ──────────────────────────────────────────────

    async def get_nodes(
        self,
        skip: int = 0,
        limit: int = 100,
        node_type: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[KnowledgeGraphNode], int]:
        """获取节点列表（分页 + 筛选）。"""
        base = select(KnowledgeGraphNode).where(~KnowledgeGraphNode.is_deleted)

        if node_type:
            base = base.where(KnowledgeGraphNode.node_type == node_type)
        if entity_type:
            base = base.where(KnowledgeGraphNode.entity_type == entity_type)
        if status:
            base = base.where(KnowledgeGraphNode.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            base = base.where(
                or_(
                    KnowledgeGraphNode.name.ilike(pattern),
                    KnowledgeGraphNode.ai_summary.ilike(pattern),
                )
            )

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar() or 0

        # Fetch
        stmt = base.order_by(KnowledgeGraphNode.node_type, KnowledgeGraphNode.name)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_node(self, node_id: _uuid.UUID) -> KnowledgeGraphNode | None:
        """获取单个节点（含边）。"""
        stmt = (
            select(KnowledgeGraphNode)
            .options(
                selectinload(KnowledgeGraphNode.outgoing_edges),
                selectinload(KnowledgeGraphNode.incoming_edges),
            )
            .where(
                KnowledgeGraphNode.id == node_id,
                ~KnowledgeGraphNode.is_deleted,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_node(self, data: GraphNodeCreate) -> KnowledgeGraphNode:
        """创建节点。"""
        node = KnowledgeGraphNode(
            name=data.name,
            node_type=data.node_type,
            aliases=data.aliases or [],
            article_id=data.article_id,
            entity_type=data.entity_type,
            ai_summary=data.ai_summary,
            confidence=data.confidence,
            status=data.status,
            merged_into_id=data.merged_into_id,
            metadata_=data.metadata or {},
        )
        self.session.add(node)
        await self.session.flush()
        return node

    async def update_node(self, node_id: _uuid.UUID, data: GraphNodeUpdate) -> KnowledgeGraphNode | None:
        """更新节点。"""
        node = await self.get_node(node_id)
        if not node:
            return None

        update_fields = data.model_dump(exclude_unset=True)
        for key, value in update_fields.items():
            if hasattr(node, key):
                setattr(node, key, value)
            elif key == "metadata":
                node.metadata_ = value

        await self.session.flush()
        # re-fetch for UPDATE (to get updated_at etc.)
        return await self.get_node(node_id)

    async def delete_node(self, node_id: _uuid.UUID) -> bool:
        """软删除节点（级联软删除关联边）。"""
        node = await self.get_node(node_id)
        if not node:
            return False

        # 软删除关联边
        edges_stmt = (
            select(KnowledgeGraphEdge)
            .where(
                or_(
                    KnowledgeGraphEdge.source_node_id == node_id,
                    KnowledgeGraphEdge.target_node_id == node_id,
                ),
                ~KnowledgeGraphEdge.is_deleted,
            )
        )
        edges_result = await self.session.execute(edges_stmt)
        for edge in edges_result.scalars().all():
            edge.is_deleted = True

        node.is_deleted = True
        await self.session.flush()
        return True

    # ── 边 CRUD ────────────────────────────────────────────────

    async def get_edges(
        self,
        skip: int = 0,
        limit: int = 200,
        relation_type: str | None = None,
        status: str | None = None,
        source_node_id: _uuid.UUID | None = None,
        target_node_id: _uuid.UUID | None = None,
    ) -> tuple[list[KnowledgeGraphEdge], int]:
        """获取边列表（分页 + 筛选）。"""
        base = select(KnowledgeGraphEdge).where(~KnowledgeGraphEdge.is_deleted)

        if relation_type:
            base = base.where(KnowledgeGraphEdge.relation_type == relation_type)
        if status:
            base = base.where(KnowledgeGraphEdge.status == status)
        if source_node_id:
            base = base.where(KnowledgeGraphEdge.source_node_id == source_node_id)
        if target_node_id:
            base = base.where(KnowledgeGraphEdge.target_node_id == target_node_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar() or 0

        stmt = base.order_by(KnowledgeGraphEdge.relation_type)
        stmt = stmt.offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def get_edge(self, edge_id: _uuid.UUID) -> KnowledgeGraphEdge | None:
        """获取单条边。"""
        stmt = (
            select(KnowledgeGraphEdge)
            .options(
                selectinload(KnowledgeGraphEdge.source_node),
                selectinload(KnowledgeGraphEdge.target_node),
            )
            .where(
                KnowledgeGraphEdge.id == edge_id,
                ~KnowledgeGraphEdge.is_deleted,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_edge(self, data: GraphEdgeCreate) -> KnowledgeGraphEdge | None:
        """创建边。返回 None 如果源/目标节点不存在。"""
        # 验证两端节点存在
        source = await self.session.get(KnowledgeGraphNode, data.source_node_id)
        target = await self.session.get(KnowledgeGraphNode, data.target_node_id)
        if not source or not target:
            return None
        if source.is_deleted or target.is_deleted:
            return None

        edge = KnowledgeGraphEdge(
            source_node_id=data.source_node_id,
            target_node_id=data.target_node_id,
            relation_type=data.relation_type,
            description=data.description,
            evidence_text=data.evidence_text,
            confidence=data.confidence,
            status=data.status,
            metadata_=data.metadata or {},
        )
        self.session.add(edge)
        await self.session.flush()
        return edge

    async def update_edge(self, edge_id: _uuid.UUID, data: GraphEdgeUpdate) -> KnowledgeGraphEdge | None:
        """更新边。"""
        edge = await self.get_edge(edge_id)
        if not edge:
            return None

        update_fields = data.model_dump(exclude_unset=True)
        for key, value in update_fields.items():
            if hasattr(edge, key):
                setattr(edge, key, value)
            elif key == "metadata":
                edge.metadata_ = value

        await self.session.flush()
        return await self.get_edge(edge_id)

    async def delete_edge(self, edge_id: _uuid.UUID) -> bool:
        """软删除边。"""
        edge = await self.get_edge(edge_id)
        if not edge:
            return False
        edge.is_deleted = True
        await self.session.flush()
        return True

    # ── 完整图查询 ──────────────────────────────────────────────

    async def get_full_graph(
        self,
        node_types: list[str] | None = None,
        relation_types: list[str] | None = None,
        max_nodes: int = 500,
    ) -> FullGraphResponse:
        """获取完整图（节点 + 边），供前端渲染。"""
        # 节点
        node_base = select(KnowledgeGraphNode).where(
            ~KnowledgeGraphNode.is_deleted,
        )
        if node_types:
            node_base = node_base.where(KnowledgeGraphNode.node_type.in_(node_types))
        node_base = node_base.limit(max_nodes)
        node_result = await self.session.execute(node_base)
        nodes = list(node_result.scalars().all())
        node_ids = [n.id for n in nodes]

        # 边 — 仅限可见节点之间的边
        edge_base = select(KnowledgeGraphEdge).where(
            ~KnowledgeGraphEdge.is_deleted,
            KnowledgeGraphEdge.source_node_id.in_(node_ids),
            KnowledgeGraphEdge.target_node_id.in_(node_ids),
        )
        if relation_types:
            edge_base = edge_base.where(KnowledgeGraphEdge.relation_type.in_(relation_types))
        edge_result = await self.session.execute(edge_base)
        edges = list(edge_result.scalars().all())

        # 统计
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for n in nodes:
            by_type[n.node_type] = by_type.get(n.node_type, 0) + 1
            by_status[n.status] = by_status.get(n.status, 0) + 1

        return FullGraphResponse(
            nodes=nodes,
            edges=edges,
            stats={
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "by_type": by_type,
                "by_status": by_status,
            },
        )

    # ── 搜索 & 展开 ────────────────────────────────────────────

    async def search_nodes(
        self, query: str, node_types: list[str] | None = None, limit: int = 20,
    ) -> list[KnowledgeGraphNode]:
        """按关键词搜索节点。"""
        pattern = f"%{query}%"
        stmt = select(KnowledgeGraphNode).where(
            ~KnowledgeGraphNode.is_deleted,
            or_(
                KnowledgeGraphNode.name.ilike(pattern),
                KnowledgeGraphNode.ai_summary.ilike(pattern),
            ),
        )
        if node_types:
            stmt = stmt.where(KnowledgeGraphNode.node_type.in_(node_types))
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def expand_node(
        self,
        node_id: _uuid.UUID,
        hops: int = 1,
        relation_types: list[str] | None = None,
        max_nodes: int = 50,
    ) -> FullGraphResponse:
        """从指定节点展开 N-hop 邻居子图。"""
        visited: set[_uuid.UUID] = set()
        current_layer: set[_uuid.UUID] = {node_id}
        all_nodes: dict[_uuid.UUID, KnowledgeGraphNode] = {}
        all_edges: dict[_uuid.UUID, KnowledgeGraphEdge] = {}

        for _ in range(hops):
            if not current_layer:
                break
            if len(all_nodes) >= max_nodes:
                break

            # 加载当前层节点
            stmt = select(KnowledgeGraphNode).where(
                KnowledgeGraphNode.id.in_(list(current_layer - visited)),
                ~KnowledgeGraphNode.is_deleted,
            )
            result = await self.session.execute(stmt)
            for node in result.scalars().all():
                all_nodes[node.id] = node

            visited.update(current_layer)

            # 查找关联边
            edge_stmt = select(KnowledgeGraphEdge).where(
                ~KnowledgeGraphEdge.is_deleted,
                or_(
                    KnowledgeGraphEdge.source_node_id.in_(list(current_layer)),
                    KnowledgeGraphEdge.target_node_id.in_(list(current_layer)),
                ),
            )
            if relation_types:
                edge_stmt = edge_stmt.where(
                    KnowledgeGraphEdge.relation_type.in_(relation_types),
                )
            edge_result = await self.session.execute(edge_stmt)

            next_layer: set[_uuid.UUID] = set()
            for edge in edge_result.scalars().all():
                all_edges[edge.id] = edge
                if edge.source_node_id not in visited:
                    next_layer.add(edge.source_node_id)
                if edge.target_node_id not in visited:
                    next_layer.add(edge.target_node_id)

            current_layer = next_layer

        # 加载下一层节点（不在 visited 中的）
        missing = set()
        for e in all_edges.values():
            if e.source_node_id not in all_nodes:
                missing.add(e.source_node_id)
            if e.target_node_id not in all_nodes:
                missing.add(e.target_node_id)

        if missing:
            stmt = select(KnowledgeGraphNode).where(
                KnowledgeGraphNode.id.in_(list(missing)),
                ~KnowledgeGraphNode.is_deleted,
            )
            result = await self.session.execute(stmt)
            for node in result.scalars().all():
                all_nodes[node.id] = node

        nodes = list(all_nodes.values())
        edges = list(all_edges.values())

        by_type: dict[str, int] = {}
        for n in nodes:
            by_type[n.node_type] = by_type.get(n.node_type, 0) + 1

        return FullGraphResponse(
            nodes=nodes,
            edges=edges,
            stats={
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "by_type": by_type,
            },
        )
