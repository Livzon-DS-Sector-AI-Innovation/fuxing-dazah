"""AI 知识图谱生成器 — 从法规文档中提取实体、构建分类体系、识别关系。

流程:
  Step 1: 加载文档 (knowledge_articles published)
  Step 2: AI 实体提取（每份文档独立，可并行分批）
  Step 3: AI 分类体系构建（全局）
  Step 4: AI 关系识别（全局）
  Step 5: 去重 + 合并 + 置信度评分
  Step 6: 写入数据库
"""

import asyncio
import json
import logging
import uuid as _uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.knowledge.graph_models import (
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

# 每批并行处理的文档数（AI API 并发限制）
ENTITY_EXTRACTION_BATCH_SIZE = 5
# 关系识别的最大边数（避免 token 超限）
MAX_EDGES_PER_BATCH = 50
# AI 输出解析失败最大重试次数
MAX_RETRIES = 2

# ═══════════════════════════════════════════════════════════════
# Prompt 模板
# ═══════════════════════════════════════════════════════════════

ENTITY_EXTRACTION_PROMPT = """你是安全法规知识图谱构建专家。请从以下法规文档中提取所有安全相关的实体。

文档名称: {title}
文档类别: {category}
文档内容:
{content}

对每个实体提取以下字段:
- entity_name: 实体名称（使用规范术语，如"防爆堵头"而非"堵头"）
- entity_type: 实体类型，必须是以下之一:
  * equipment: 设备/部件（如防爆电箱、安全阀、接地线）
  * condition: 状态/缺陷（如封堵缺失、锈蚀、接地不良）
  * location: 场所/区域（如爆炸危险区、受限空间、罐区）
  * operation: 作业活动（如动火、临时用电、盲板抽堵）
  * material: 物料/介质（如易燃液体、有毒气体）
  * standard: 标准/法规（如 GB 3836.1、安全生产法）
- aliases: 同义词/简称列表（如 ["Ex堵头", "防爆封堵件", "电缆引入装置密封堵头"]）
- related_clauses: 涉及的具体条款编号列表
- description: 一句话描述该实体在本文档中的含义

请以 JSON 对象格式返回，结构为 {{"entities": [...]}}。只提取确实在文档中出现的实体，不要编造。"""

TAXONOMY_BUILD_PROMPT = """你正在构建一个原料药工厂安全知识图谱的分类体系。

以下是所有已提取的实体列表（每个实体的 name + type + description）:
{entities_summary}

以下是所有文档的标题和类别:
{documents_summary}

请构建一个 3-4 层的安全知识分类树:
- 根类别（如 电气安全、特殊作业、消防安全、设备安全、职业健康、危化品管理、管理体系）
- 子类别（如 电气安全→防爆电气、电气安全→电气安装、电气安全→防雷防静电）
- 叶子节点可以是具体的法规条款

输出 JSON 格式:
{{
  "taxonomy": [
    {{
      "name": "电气安全",
      "description": "...",
      "children": [
        {{
          "name": "防爆电气",
          "description": "...",
          "children": [
            {{ "name": "GB 3836.1 §15 电缆引入装置密封", "description": "..." }}
          ]
        }}
      ]
    }}
  ]
}}

注意:
- 同一实体/条款可以挂在多个分类节点下
- 分类应该覆盖所有主要的安全领域
- 层级不要太深（最多 4 层）"""

RELATION_EXTRACTION_PROMPT = """你是安全法规关系识别专家。以下有两个列表:

实体节点:
{nodes_summary}

分类节点:
{taxonomy_summary}

请识别以下关系类型:
1. cites (引用): 法规 A 明确引用了法规 B 的标准/条款
2. supplements (补充): 法规 A 是对法规 B 的细化/补充说明
3. replaces (替代): 法规 A 替代了法规 B（如新标准替代旧标准）
4. belongs_to (归属): 实体 X 属于分类 Y
5. related_to (相关): 两个实体/法规语义相关但无明确引用关系

对每条关系提供:
- source_name: 源节点名称（必须与上面列表中的 name 完全一致）
- target_name: 目标节点名称
- relation_type: cites / supplements / replaces / belongs_to / related_to
- description: 一句话解释为什么存在这个关系
- evidence: 支持该关系的原文引用（如可用）
- confidence: 0.0-1.0 的置信度评分

请以 JSON 对象格式返回，结构为 {{"relations": [...]}}，最多 {max_edges} 条关系。
只返回你高度确信的关系（confidence >= 0.7），不要猜测。"""


# ═══════════════════════════════════════════════════════════════
# GraphBuilder
# ═══════════════════════════════════════════════════════════════

class GraphBuilder:
    """AI 知识图谱生成器 — 编排实体提取、分类构建、关系识别的完整流程。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._ai = None  # 延迟创建

    async def _get_ai(self):
        """懒加载 AIService。"""
        if self._ai is None:
            from app.modules.safety.service.config import create_ai_service
            self._ai = create_ai_service("text")
        return self._ai

    # ── 主入口 ─────────────────────────────────────────────────

    async def build_full_graph(
        self,
        document_ids: list[_uuid.UUID] | None = None,
        force_rebuild: bool = False,
    ) -> dict:
        """完整图谱生成流程。

        Args:
            document_ids: 指定文档 ID，None 表示全量
            force_rebuild: 是否清除已有 AI 生成数据后重建

        Returns:
            {nodes_created, nodes_updated, edges_created, errors}
        """
        result = {"nodes_created": 0, "nodes_updated": 0, "edges_created": 0, "errors": []}

        # 0. 可选：清除已有 AI 生成数据
        if force_rebuild:
            await self._clear_ai_generated()

        # 1. 加载文档
        documents = await self._load_documents(document_ids)
        if not documents:
            result["errors"].append("没有找到 published 状态的文档")
            return result
        logger.info("GraphBuilder: 加载 %d 份文档", len(documents))

        # 2. AI 实体提取（并行批次）
        entities = await self._extract_entities(documents)
        logger.info("GraphBuilder: 提取 %d 个实体", len(entities))

        # 3. 写入实体节点
        for entity in entities:
            try:
                node = await self._upsert_entity_node(entity)
                if node:
                    result["nodes_created"] += 1
            except Exception as e:
                result["errors"].append(f"写入实体节点失败: {entity.get('entity_name', '?')} - {e}")

        await self.session.flush()

        # 4. AI 分类体系构建
        taxonomy = await self._build_taxonomy(documents, entities)
        logger.info("GraphBuilder: 构建 %d 个分类节点", len(taxonomy))

        # 5. 写入分类节点 + belongs_to 边
        for taxon in taxonomy:
            try:
                node = await self._upsert_taxonomy_node(taxon)
                if node:
                    result["nodes_created"] += 1
                # 创建子节点 → 父节点的 belongs_to 边
                await self._create_taxonomy_edges(taxon)
            except Exception as e:
                result["errors"].append(f"写入分类节点失败: {taxon.get('name', '?')} - {e}")

        await self.session.flush()

        # 6. AI 关系识别
        relations = await self._extract_relations(entities, taxonomy)
        logger.info("GraphBuilder: 识别 %d 条关系", len(relations))

        # 7. 写入关系边
        for rel in relations:
            try:
                edge = await self._upsert_relation_edge(rel)
                if edge:
                    result["edges_created"] += 1
            except Exception as e:
                result["errors"].append(f"写入关系边失败: {rel.get('source_name', '?')}→{rel.get('target_name', '?')} - {e}")

        await self.session.flush()

        return result

    # ── 文档加载 ───────────────────────────────────────────────

    async def _load_documents(self, document_ids: list[_uuid.UUID] | None) -> list[dict]:
        """加载 published 状态的文档。"""
        from app.modules.safety.models import SafetyKnowledgeArticle

        stmt = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.status == "published",
            ~SafetyKnowledgeArticle.is_deleted,
        )
        if document_ids:
            stmt = stmt.where(SafetyKnowledgeArticle.id.in_(document_ids))
        stmt = stmt.order_by(SafetyKnowledgeArticle.category, SafetyKnowledgeArticle.title)

        result = await self.session.execute(stmt)
        docs = result.scalars().all()

        return [
            {
                "id": str(d.id),
                "title": d.title,
                "category": d.category or "other",
                "summary": d.summary or "",
                "content": d.content or "",
                "knowledge_card": d.knowledge_card or {},
            }
            for d in docs
        ]

    # ── 实体提取 ───────────────────────────────────────────────

    async def _extract_entities(self, documents: list[dict]) -> list[dict]:
        """并行分批提取实体。"""
        all_entities: list[dict] = []
        ai = await self._get_ai()

        for i in range(0, len(documents), ENTITY_EXTRACTION_BATCH_SIZE):
            batch = documents[i:i + ENTITY_EXTRACTION_BATCH_SIZE]
            tasks = [self._extract_entities_from_doc(ai, doc) for doc in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("实体提取失败: doc=%s err=%s", batch[j]["title"], result)
                elif isinstance(result, list):
                    all_entities.extend(result)

        # 去重（按 entity_name）
        seen: set[str] = set()
        deduped: list[dict] = []
        for e in all_entities:
            name = e.get("entity_name", "").strip()
            if name and name not in seen:
                seen.add(name)
                deduped.append(e)
        return deduped

    async def _extract_entities_from_doc(self, ai, doc: dict) -> list[dict]:
        """从单个文档提取实体。"""
        # 构建文档内容
        content = doc.get("content", "") or ""
        if not content:
            card = doc.get("knowledge_card", {})
            if isinstance(card, dict):
                parts = []
                for k in ("hazard_type_definitions", "hazard_category_criteria",
                          "key_defect_examples", "legal_basis_clauses"):
                    if card.get(k):
                        parts.append(str(card[k]))
                content = "\n".join(parts)
        if not content:
            content = doc.get("summary", "") or ""
        if not content:
            return []

        # 截断过长内容
        max_chars = 15000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n...(内容过长，已截断)"

        prompt = ENTITY_EXTRACTION_PROMPT.format(
            title=doc["title"],
            category=doc.get("category", "未分类"),
            content=content,
        )

        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = await ai.chat(
                    messages=[
                        {"role": "system", "content": "你是安全法规知识图谱构建专家。请严格以 JSON 数组格式返回结果。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format="json_object",
                    temperature=0.1,
                    max_tokens=4096,
                )
                parsed = self._parse_json_array(raw)
                return parsed
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error("实体提取失败（重试%d次）: doc=%s err=%s", MAX_RETRIES, doc["title"], e)
                    return []
                logger.warning("实体提取重试 %d: doc=%s", attempt + 1, doc["title"])

        return []

    # ── 分类体系构建 ───────────────────────────────────────────

    async def _build_taxonomy(self, documents: list[dict], entities: list[dict]) -> list[dict]:
        """构建全局安全知识分类树。"""
        ai = await self._get_ai()

        # 构建摘要（限制长度）
        entities_summary = "\n".join(
            f"- {e.get('entity_name', '?')} [{e.get('entity_type', '?')}]: {e.get('description', '')[:60]}"
            for e in entities[:60]  # 最多 60 个实体
        )
        documents_summary = "\n".join(
            f"- [{d.get('category', '?')}] {d['title']}"
            for d in documents[:30]
        )

        prompt = TAXONOMY_BUILD_PROMPT.format(
            entities_summary=entities_summary[:8000],
            documents_summary=documents_summary[:3000],
        )

        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = await ai.chat(
                    messages=[
                        {"role": "system", "content": "你是安全知识分类体系构建专家。请严格以 JSON 格式返回分类树。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format="json_object",
                    temperature=0.1,
                    max_tokens=8192,
                )
                parsed = self._parse_json(raw)
                return self._flatten_taxonomy(parsed.get("taxonomy", []))
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error("分类体系构建失败（重试%d次）: %s", MAX_RETRIES, e)
                    return []
                logger.warning("分类体系构建重试 %d: %s", attempt + 1, e)

    def _flatten_taxonomy(self, tree: list[dict], parent_name: str = "") -> list[dict]:
        """将嵌套分类树展平为节点列表。"""
        result: list[dict] = []
        for node in tree:
            name = node.get("name", "")
            item = {
                "name": name,
                "description": node.get("description", ""),
                "parent_name": parent_name if parent_name else None,
            }
            result.append(item)
            children = node.get("children", [])
            if children:
                result.extend(self._flatten_taxonomy(children, parent_name=name))
        return result

    # ── 关系识别 ───────────────────────────────────────────────

    async def _extract_relations(self, entities: list[dict], taxonomy: list[dict]) -> list[dict]:
        """识别实体和分类之间的关系。"""
        ai = await self._get_ai()

        nodes_summary = "\n".join(
            f"- [entity] {e.get('entity_name', '?')} ({e.get('entity_type', '?')})"
            for e in entities[:50]
        )
        taxonomy_summary = "\n".join(
            f"- [category] {t.get('name', '?')} (parent: {t.get('parent_name', 'none')})"
            for t in taxonomy[:20]
        )

        prompt = RELATION_EXTRACTION_PROMPT.format(
            nodes_summary=nodes_summary[:8000],
            taxonomy_summary=taxonomy_summary[:3000],
            max_edges=MAX_EDGES_PER_BATCH,
        )

        for attempt in range(MAX_RETRIES + 1):
            try:
                raw = await ai.chat(
                    messages=[
                        {"role": "system", "content": "你是安全法规关系识别专家。请严格以 JSON 对象格式返回结果，结构为 {\"relations\": [...]}。"},
                        {"role": "user", "content": prompt},
                    ],
                    response_format="json_object",
                    temperature=0.1,
                    max_tokens=8192,
                )
                parsed = self._parse_json_array(raw)
                # 过滤低置信度
                return [r for r in parsed if r.get("confidence", 0) >= 0.7]
            except Exception as e:
                if attempt == MAX_RETRIES:
                    logger.error("关系识别失败（重试%d次）: %s", MAX_RETRIES, e)
                    return []
                logger.warning("关系识别重试 %d: %s", attempt + 1, e)

    # ── 数据库写入 ─────────────────────────────────────────────

    async def _upsert_entity_node(self, entity: dict) -> KnowledgeGraphNode | None:
        """创建或更新实体节点。"""
        name = entity.get("entity_name", "").strip()
        if not name:
            return None

        # 检查是否已存在（人工确认的节点不覆盖）
        existing = await self._find_node_by_name(name)
        if existing and existing.status == "human_confirmed":
            return None

        aliases = entity.get("aliases", []) or []
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]

        if existing:
            existing.aliases = list(set((existing.aliases or []) + aliases))
            existing.ai_summary = entity.get("description", "") or existing.ai_summary
            existing.confidence = 0.8
            existing.status = "ai_generated"
            return existing

        node = KnowledgeGraphNode(
            name=name,
            node_type="entity",
            aliases=aliases,
            entity_type=entity.get("entity_type", ""),
            ai_summary=entity.get("description", ""),
            confidence=0.8,
            status="ai_generated",
            metadata_={"source": "graph_builder"},
        )
        self.session.add(node)
        return node

    async def _upsert_taxonomy_node(self, taxon: dict) -> KnowledgeGraphNode | None:
        """创建或更新分类节点。"""
        name = taxon.get("name", "").strip()
        if not name:
            return None

        existing = await self._find_node_by_name(name)
        if existing and existing.status == "human_confirmed":
            return None

        if existing:
            existing.ai_summary = taxon.get("description", "") or existing.ai_summary
            existing.confidence = 0.7
            existing.status = "ai_generated"
            return existing

        node = KnowledgeGraphNode(
            name=name,
            node_type="category",
            ai_summary=taxon.get("description", ""),
            confidence=0.7,
            status="ai_generated",
            metadata_={"parent_name": taxon.get("parent_name"), "source": "graph_builder"},
        )
        self.session.add(node)
        return node

    async def _create_taxonomy_edges(self, taxon: dict) -> None:
        """创建分类节点的 belongs_to 边（子→父）。"""
        parent_name = taxon.get("parent_name")
        if not parent_name:
            return

        child = await self._find_node_by_name(taxon.get("name", ""))
        parent = await self._find_node_by_name(parent_name)
        if not child or not parent:
            return

        # 检查边是否已存在
        existing = await self._find_edge(child.id, parent.id, "belongs_to")
        if existing:
            return

        edge = KnowledgeGraphEdge(
            source_node_id=child.id,
            target_node_id=parent.id,
            relation_type="belongs_to",
            description=f"{child.name} 属于 {parent.name}",
            confidence=0.9,
            status="ai_generated",
            metadata_={"source": "graph_builder"},
        )
        self.session.add(edge)

    async def _upsert_relation_edge(self, rel: dict) -> KnowledgeGraphEdge | None:
        """创建或更新关系边。"""
        source_name = rel.get("source_name", "").strip()
        target_name = rel.get("target_name", "").strip()
        relation_type = rel.get("relation_type", "").strip()

        if not source_name or not target_name or not relation_type:
            return None

        source = await self._find_node_by_name(source_name)
        target = await self._find_node_by_name(target_name)
        if not source or not target:
            return None

        existing = await self._find_edge(source.id, target.id, relation_type)
        confidence = rel.get("confidence", 0.7)

        if existing:
            if existing.status == "human_confirmed":
                return None
            existing.description = rel.get("description", "") or existing.description
            existing.evidence_text = rel.get("evidence", "") or existing.evidence_text
            existing.confidence = max(existing.confidence or 0, confidence)
            return existing

        edge = KnowledgeGraphEdge(
            source_node_id=source.id,
            target_node_id=target.id,
            relation_type=relation_type,
            description=rel.get("description", ""),
            evidence_text=rel.get("evidence", ""),
            confidence=confidence,
            status="ai_generated",
            metadata_={"source": "graph_builder"},
        )
        self.session.add(edge)
        return edge

    # ── 辅助方法 ───────────────────────────────────────────────

    async def _find_node_by_name(self, name: str) -> KnowledgeGraphNode | None:
        """按 name 精确匹配节点。"""
        stmt = select(KnowledgeGraphNode).where(
            KnowledgeGraphNode.name == name,
            ~KnowledgeGraphNode.is_deleted,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _find_edge(
        self, source_id: _uuid.UUID, target_id: _uuid.UUID, relation_type: str,
    ) -> KnowledgeGraphEdge | None:
        """查找已存在的边。"""
        stmt = select(KnowledgeGraphEdge).where(
            KnowledgeGraphEdge.source_node_id == source_id,
            KnowledgeGraphEdge.target_node_id == target_id,
            KnowledgeGraphEdge.relation_type == relation_type,
            ~KnowledgeGraphEdge.is_deleted,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _clear_ai_generated(self) -> None:
        """清除所有 AI 生成的节点和边（保留人工确认/新增的）。"""
        # 边
        edges_stmt = select(KnowledgeGraphEdge).where(
            KnowledgeGraphEdge.status == "ai_generated",
            ~KnowledgeGraphEdge.is_deleted,
        )
        edges_result = await self.session.execute(edges_stmt)
        for edge in edges_result.scalars().all():
            edge.is_deleted = True

        # 节点
        nodes_stmt = select(KnowledgeGraphNode).where(
            KnowledgeGraphNode.status == "ai_generated",
            ~KnowledgeGraphNode.is_deleted,
        )
        nodes_result = await self.session.execute(nodes_stmt)
        for node in nodes_result.scalars().all():
            node.is_deleted = True

        await self.session.flush()
        logger.info("GraphBuilder: 已清除 AI 生成数据")

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """解析 AI 返回的 JSON 对象（兼容 markdown 代码块包裹）。"""
        text = raw.strip()
        # 去掉 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if not line.strip().startswith("```"):
                    text = "\n".join(lines[i:])
                    break
            if text.endswith("```"):
                text = text[:-3].strip()
        return json.loads(text)

    @staticmethod
    def _parse_json_array(raw: str) -> list[dict]:
        """解析 AI 返回的 JSON（兼容数组和对象包装）。"""
        text = raw.strip()
        # 去掉 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            for i, line in enumerate(lines):
                if not line.strip().startswith("```"):
                    text = "\n".join(lines[i:])
                    break
            if text.endswith("```"):
                text = text[:-3].strip()

        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            # 尝试找常见的数组 key
            for key in ("entities", "results", "data", "items", "relations"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            # 如果是单对象，包装为数组
            return [parsed]
        return []
