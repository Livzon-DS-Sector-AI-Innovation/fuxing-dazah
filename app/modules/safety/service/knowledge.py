"""Safety business workflows."""

import logging
import os
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import delete_object
from app.core.storage import is_enabled as minio_enabled
from app.modules.safety.models import (
    SafetyKnowledgeArticle,
)
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.schemas import (
    SafetyKnowledgeArticleCreate,
    SafetyKnowledgeArticleUpdate,
)

logger = logging.getLogger(__name__)


class KnowledgeService:
    """安全知识库业务服务"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    @staticmethod
    def _cleanup_file(file_path: str | None) -> None:
        """Delete a single file from MinIO or local disk."""
        if not file_path:
            return
        try:
            if minio_enabled():
                try:
                    delete_object("safety", file_path)
                except Exception:
                    pass
            else:
                abs_path = os.path.abspath(file_path)
                if os.path.exists(abs_path):
                    os.remove(abs_path)
        except OSError:
            pass

    async def get_articles(
        self,
        skip: int = 0,
        limit: int = 20,
        category: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SafetyKnowledgeArticle], int]:
        """获取知识库文章列表"""
        return await self.repo.get_knowledge_articles(
            skip, limit, category, status, keyword
        )

    async def get_article(self, article_id: uuid.UUID) -> SafetyKnowledgeArticle | None:
        """获取文章详情（浏览计数+1）"""
        article = await self.repo.get_knowledge_article_by_id(article_id)
        if article:
            await self.repo.update_knowledge_article(
                article_id, {"view_count": article.view_count + 1}
            )
        return article

    async def create_article(
        self, data: SafetyKnowledgeArticleCreate
    ) -> SafetyKnowledgeArticle:
        """创建知识库文章"""
        article_data = data.model_dump()
        return await self.repo.create_knowledge_article(article_data)

    async def update_article(
        self, article_id: uuid.UUID, data: SafetyKnowledgeArticleUpdate
    ) -> SafetyKnowledgeArticle | None:
        """更新知识库文章"""
        update_data = {k: v for k, v in data.model_dump().items() if v is not None}
        return await self.repo.update_knowledge_article(article_id, update_data)

    async def delete_article(self, article_id: uuid.UUID) -> bool:
        """删除知识库文章"""
        article = await self.repo.get_knowledge_article_by_id(article_id)
        result = await self.repo.delete_knowledge_article(article_id)
        if result and article:
            self._cleanup_file(article.attachment_path)
        return result

    async def publish_article(self, article_id: uuid.UUID) -> SafetyKnowledgeArticle | None:
        """发布文章（草稿→已发布）"""
        article = await self.repo.get_knowledge_article_by_id(article_id)
        if not article or article.status != "draft":
            return None
        return await self.repo.update_knowledge_article(
            article_id, {"status": "published"}
        )

    async def archive_article(self, article_id: uuid.UUID) -> SafetyKnowledgeArticle | None:
        """归档文章（已发布→已归档）"""
        article = await self.repo.get_knowledge_article_by_id(article_id)
        if not article or article.status != "published":
            return None
        return await self.repo.update_knowledge_article(
            article_id, {"status": "archived"}
        )


# ==================== 风险作业报备 Services ====================


