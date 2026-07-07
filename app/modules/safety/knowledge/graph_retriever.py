"""图导航检索器 — 沿知识图谱边遍历找到相关条款。

用于增强 RegulationRetriever 的关键词检索：
  1. 从隐患描述中匹配知识图谱实体
  2. 沿 entity → clause 边找到直接关联条款
  3. 沿 clause → cites/supplements 边展开 1-2 hop
  4. 沿 belongs_to 边向上找到分类 → 兄弟节点
  5. 按图距离排序返回

用法:
    retriever = GraphRetriever(session)
    chunks = await retriever.find_related_clauses(
        entity_names=["防爆堵头", "防爆电箱"],
        max_hops=2,
    )
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.knowledge.graph_models import (
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)

logger = logging.getLogger(__name__)


@dataclass
class GraphSearchResult:
    """图检索结果。"""
    node_id: UUID
    node_name: str
    node_type: str
    graph_distance: int  # 距离起始实体的跳数
    path: list[str] = field(default_factory=list)  # 导航路径


class GraphRetriever:
    """图导航检索器 — 沿知识图谱边遍历找到相关条款。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_related_clauses(
        self,
        entity_names: list[str],
        max_results: int = 20,
        max_hops: int = 2,
    ) -> list[GraphSearchResult]:
        """从实体名称出发，沿图导航找到相关条款。

        Args:
            entity_names: 从隐患描述中提取的实体名称列表
            max_results: 最大返回数
            max_hops: 最大展开跳数

        Returns:
            按图距离排序的检索结果
        """
        if not entity_names:
            return []

        # 1. 匹配实体节点（精确 + 别名）
        entities = await self._match_entities(entity_names)
        if not entities:
            logger.debug("GraphRetriever: 未匹配到实体: %s", entity_names)
            return []

        logger.debug("GraphRetriever: 匹配 %d 个实体", len(entities))

        # 2. BFS 图遍历
        results: dict[UUID, GraphSearchResult] = {}
        visited: set[UUID] = set()
        current_layer: list[tuple[UUID, int, list[str]]] = [
            (e.id, 0, [f"entity:{e.name}"]) for e in entities
        ]

        while current_layer and len(results) < max_results:
            next_layer: list[tuple[UUID, int, list[str]]] = []

            for node_id, dist, path in current_layer:
                if node_id in visited:
                    continue
                if dist > max_hops:
                    continue
                visited.add(node_id)

                # 获取节点详情
                node = await self.session.get(KnowledgeGraphNode, node_id)
                if not node or node.is_deleted:
                    continue

                # 仅收集 clause 和 document 类型的节点作为结果
                if node.node_type in ("clause", "document"):
                    if node_id not in results:
                        results[node_id] = GraphSearchResult(
                            node_id=node_id,
                            node_name=node.name,
                            node_type=node.node_type,
                            graph_distance=dist,
                            path=path,
                        )

                # 查找出边
                edges = await self._get_outgoing_edges(node_id)
                for edge in edges:
                    target = edge.target_node_id
                    if target not in visited:
                        next_layer.append((
                            target, dist + 1,
                            path + [f"{edge.relation_type}:{edge.target_node.name if edge.target_node else target}"],
                        ))

                # 查找入边（反向导航）
                incoming = await self._get_incoming_edges(node_id)
                for edge in incoming:
                    source = edge.source_node_id
                    if source not in visited:
                        next_layer.append((
                            source, dist + 1,
                            path + [f"rev_{edge.relation_type}:{edge.source_node.name if edge.source_node else source}"],
                        ))

            current_layer = next_layer

        # 按距离排序
        sorted_results = sorted(results.values(), key=lambda r: r.graph_distance)
        return sorted_results[:max_results]

    async def get_graph_context(
        self,
        entity_names: list[str],
        max_results: int = 20,
        max_hops: int = 2,
    ) -> str:
        """一步获取图导航上下文（Markdown 格式）。

        Returns:
            Markdown 文本，无结果时返回空字符串
        """
        results = await self.find_related_clauses(
            entity_names=entity_names,
            max_results=max_results,
            max_hops=max_hops,
        )
        if not results:
            return ""

        lines = [
            "## 知识图谱导航结果\n",
            f"从 {len(entity_names)} 个实体出发，导航到 {len(results)} 个相关条款：\n",
        ]
        for r in results:
            path_str = " → ".join(r.path) if r.path else "直接匹配"
            lines.append(f"- **{r.node_name}** (距离={r.graph_distance}, 类型={r.node_type})")
            lines.append(f"  导航路径: {path_str}")

        return "\n".join(lines)

    # ── 内部方法 ───────────────────────────────────────────────

    async def _match_entities(self, names: list[str]) -> list[KnowledgeGraphNode]:
        """按名称/别名匹配实体节点。"""
        conditions = []
        for name in names:
            name = name.strip()
            if not name:
                continue
            # 精确匹配 name
            conditions.append(KnowledgeGraphNode.name == name)
            # 模糊匹配 name (ILIKE)
            conditions.append(KnowledgeGraphNode.name.ilike(f"%{name}%"))
            # 别名匹配
            conditions.append(KnowledgeGraphNode.aliases.any(name))

        if not conditions:
            return []

        stmt = (
            select(KnowledgeGraphNode)
            .where(
                KnowledgeGraphNode.node_type == "entity",
                ~KnowledgeGraphNode.is_deleted,
                or_(*conditions),
            )
            .limit(50)
        )
        result = await self.session.execute(stmt)
        nodes = list(result.scalars().all())

        # 去重 + 精确匹配优先排序
        seen: set[UUID] = set()
        exact_first: list[KnowledgeGraphNode] = []
        fuzzy: list[KnowledgeGraphNode] = []
        for n in nodes:
            if n.id in seen:
                continue
            seen.add(n.id)
            if n.name in names:
                exact_first.append(n)
            else:
                fuzzy.append(n)

        return exact_first + fuzzy

    async def _get_outgoing_edges(self, node_id: UUID) -> list[KnowledgeGraphEdge]:
        """获取节点的出边（仅 confirmed/ai_generated 状态）。"""
        stmt = select(KnowledgeGraphEdge).where(
            KnowledgeGraphEdge.source_node_id == node_id,
            ~KnowledgeGraphEdge.is_deleted,
            KnowledgeGraphEdge.status.in_(("human_confirmed", "ai_generated")),
        ).limit(20)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _get_incoming_edges(self, node_id: UUID) -> list[KnowledgeGraphEdge]:
        """获取节点的入边（仅 confirmed/ai_generated 状态）。"""
        stmt = select(KnowledgeGraphEdge).where(
            KnowledgeGraphEdge.target_node_id == node_id,
            ~KnowledgeGraphEdge.is_deleted,
            KnowledgeGraphEdge.status.in_(("human_confirmed", "ai_generated")),
        ).limit(20)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
