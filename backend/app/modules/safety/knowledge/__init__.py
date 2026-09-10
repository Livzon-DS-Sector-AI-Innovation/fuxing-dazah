"""安全知识库模块 — 法规标准文档管理与 RAG 知识检索。

提供：
- KnowledgeCard: 法规知识卡片的 Pydantic 数据模型
- KnowledgeDocumentMeta / KNOWLEDGE_DOCUMENTS: 法规清单元数据
- DocumentLoader: 飞书 Drive 文档下载与解析
- SafetyKnowledgeRetriever: 统一 RAG 检索入口（三层管线）
- KnowledgeGraphNode / KnowledgeGraphEdge: 知识图谱节点与边 ORM 模型
- GraphService: 图谱 CRUD 与图查询
- GraphBuilder: AI 图谱生成器
- GraphRetriever: 图导航检索器

用法:
    from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

    retriever = SafetyKnowledgeRetriever(session)
    context = await retriever.retrieve(description="防爆堵头未封堵")
    injection_md = retriever.build_injection_context(context)
"""

from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector
from app.modules.safety.knowledge.document_loader import DocumentLoader
from app.modules.safety.knowledge.graph_builder import GraphBuilder
from app.modules.safety.knowledge.graph_models import (
    KnowledgeGraphEdge,
    KnowledgeGraphNode,
)
from app.modules.safety.knowledge.graph_retriever import GraphRetriever
from app.modules.safety.knowledge.graph_schemas import (
    FullGraphResponse,
    GraphEdgeCreate,
    GraphEdgeResponse,
    GraphEdgeUpdate,
    GraphNodeCreate,
    GraphNodeResponse,
    GraphNodeUpdate,
)
from app.modules.safety.knowledge.graph_service import GraphService
from app.modules.safety.knowledge.injector import KnowledgeInjector
from app.modules.safety.knowledge.knowledge_card import (
    KNOWLEDGE_DOCUMENTS,
    KnowledgeCard,
    KnowledgeDocumentMeta,
)

__all__ = [
    "KnowledgeCard",
    "KnowledgeDocumentMeta",
    "KNOWLEDGE_DOCUMENTS",
    "DocumentLoader",
    "KnowledgeCardSelector",
    "KnowledgeInjector",
    # Graph
    "KnowledgeGraphNode",
    "KnowledgeGraphEdge",
    "GraphService",
    "GraphBuilder",
    "GraphRetriever",
    "GraphNodeCreate",
    "GraphNodeUpdate",
    "GraphNodeResponse",
    "GraphEdgeCreate",
    "GraphEdgeUpdate",
    "GraphEdgeResponse",
    "FullGraphResponse",
]
