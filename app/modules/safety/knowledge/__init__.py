"""安全知识库模块 — 法规标准文档管理与 AI 知识注入。

提供：
- KnowledgeCard: 法规知识卡片的 Pydantic 数据模型
- DocumentLoader: 飞书 Drive 文档下载与解析
- KnowledgeInjector: AI prompt 知识注入层
- KnowledgeCardSelector: AI 智能卡片选择器（根据隐患上下文精准选择相关卡片）

用法:
    from app.modules.safety.knowledge import KnowledgeInjector

    injector = KnowledgeInjector(session)
    context = await injector.build_knowledge_context()
"""

from app.modules.safety.knowledge.card_selector import KnowledgeCardSelector
from app.modules.safety.knowledge.document_loader import DocumentLoader
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
    "KnowledgeInjector",
    "KnowledgeCardSelector",
]
