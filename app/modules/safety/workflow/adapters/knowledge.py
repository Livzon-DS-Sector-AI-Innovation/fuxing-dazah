"""DazahKnowledgeRetriever — 将 KnowledgeInjector 适配为 graphon 知识检索接口。

graphon 的 knowledge-retrieval 节点调用 KnowledgeRetrieverProtocol.retrieve()。
此适配器桥接 dazah 的 KnowledgeInjector。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DazahKnowledgeRetriever:
    """封装 dazah KnowledgeInjector，提供同步 retrieve() 接口。

    graphon 在 worker 线程中同步调用，所以用 asyncio.run() 包装。
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    def retrieve(
        self,
        query: str = "",
        categories: list[str] | None = None,
        max_cards: int = 3,
        top_k: int = 5,
    ) -> str | None:
        """检索知识上下文，返回 Markdown 格式文本。

        与 graphon 原生 KnowledgeRetrieverProtocol 略有差异：
        直接返回文本而非 list[RetrievalResult]，简化适配。

        Returns:
            组装好的知识库 Markdown 文本，无可用卡片时返回 None
        """
        return asyncio.run(
            self._retrieve_async(
                query=query, categories=categories, max_cards=max_cards,
            )
        )

    async def _retrieve_async(
        self,
        query: str = "",
        categories: list[str] | None = None,
        max_cards: int = 3,
    ) -> str | None:
        """异步调用 KnowledgeInjector.build_context()。"""
        try:
            from app.modules.safety.knowledge import KnowledgeInjector

            injector = KnowledgeInjector(self._session)
            context = await injector.build_context(
                categories=categories,
                max_cards=max_cards,
            )
            return context if context else None
        except Exception as e:
            logger.warning("知识上下文加载失败（非致命）: %s", e)
            return None
