"""记忆存储层 —— CRUD + 惰性清理。

DEPRECATED（S5 ``core/memory.py`` 冲突合并在更高层编排）：本模块保留底层 CRUD 供旧调用方
兼容，新代码走 ``app.modules.safety.business_agent.core.memory.merge_on_conflict`` /
``retrieve_with_decay``，冲突合并与衰减排序由 core 层接管。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.memory.models import AgentMemory

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── 去重阈值 ──
_DEDUP_SIMILARITY_THRESHOLD = 0.85  # embedding 余弦相似度 ≥ 此值视为重复


class MemoryStore:
    """记忆持久化 CRUD。

    所有方法接受外部传入的 AsyncSession，不持有 session 引用。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 写入 ──

    async def upsert(
        self,
        user_id: str,
        memory_type: str,
        content: str,
        *,
        embedding: list[float] | None = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source_session_id: UUID | None = None,
        source_message_id: UUID | None = None,
        metadata_: dict | None = None,
    ) -> AgentMemory | None:
        """插入或更新一条记忆。

        去重逻辑：先对 content 做 embedding，在用户记忆池中查相似度。
        若存在 ≥ _DEDUP_SIMILARITY_THRESHOLD 的已有记忆 → 更新置信度和内容；
        否则插入新记录。

        Returns:
            新创建或更新后的 AgentMemory 对象，失败返回 None。
        """
        try:
            # 去重检查
            if embedding:
                existing = await self._find_similar(
                    user_id, memory_type, embedding, content,
                )
                if existing:
                    # 更新已有记忆
                    existing.content = content
                    existing.confidence = max(existing.confidence, confidence)
                    existing.importance = max(existing.importance, importance)
                    existing.metadata_ = metadata_ or {}
                    await self.db.flush()
                    logger.debug("Memory updated (dedup): %s", content[:60])
                    return existing

            # 插入新记忆
            emb_json = json.dumps(embedding) if embedding else None
            memory = AgentMemory(
                user_id=user_id,
                memory_type=memory_type,
                content=content,
                embedding=emb_json,
                importance=importance,
                confidence=confidence,
                source_session_id=source_session_id,
                source_message_id=source_message_id,
                metadata_=metadata_ or {},
            )
            self.db.add(memory)
            await self.db.flush()
            logger.debug("Memory created: type=%s content=%s", memory_type, content[:60])
            return memory
        except Exception:
            logger.exception("Memory upsert failed, skipping")
            return None

    async def _find_similar(
        self,
        user_id: str,
        memory_type: str,
        query_embedding: list[float],
        content: str,
    ) -> AgentMemory | None:
        """在用户记忆池中查找语义相似的已有记忆。"""
        try:
            from app.modules.safety.knowledge.embedding_service import cosine_similarity

            # 查询同类型、未删除的用户记忆
            stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.memory_type == memory_type,
                    AgentMemory.is_deleted == False,  # noqa: E712
                    AgentMemory.embedding.isnot(None),
                )
                .limit(100)  # 每人每种类型最多扫描 100 条
            )
            result = await self.db.execute(stmt)
            candidates = result.scalars().all()

            best_score = 0.0
            best_match: AgentMemory | None = None
            for c in candidates:
                try:
                    cached_emb = json.loads(c.embedding) if c.embedding else None
                    if cached_emb is None:
                        continue
                    score = cosine_similarity(query_embedding, cached_emb)
                    if score > best_score:
                        best_score = score
                        best_match = c
                        if score >= 0.98:  # 近乎完全相同，提前终止
                            break
                except (json.JSONDecodeError, TypeError):
                    continue

            if best_match is not None and best_score >= _DEDUP_SIMILARITY_THRESHOLD:
                return best_match
            return None
        except Exception:
            logger.debug("Memory dedup check failed, will insert as new", exc_info=True)
            return None

    # ── 读取 ──

    async def get_by_user(
        self,
        user_id: str,
        *,
        memory_type: str | None = None,
        limit: int = 50,
    ) -> list[AgentMemory]:
        """获取用户的所有记忆（按重要性降序）。"""
        try:
            stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.is_deleted == False,  # noqa: E712
                )
                .order_by(AgentMemory.importance.desc())
                .limit(limit)
            )
            if memory_type:
                stmt = stmt.where(AgentMemory.memory_type == memory_type)
            result = await self.db.execute(stmt)
            return list(result.scalars().all())
        except Exception:
            logger.exception("Memory get_by_user failed")
            return []

    async def get_with_embeddings(
        self,
        user_id: str,
        *,
        memory_type: str | None = None,
    ) -> list[tuple[UUID, str, list[float]]]:
        """获取用户记忆的 (id, content, embedding) 三元组（供语义检索）。

        Returns:
            [(memory_id, content, embedding_vector), ...]
            仅返回 embedding 不为 NULL 的记录。
        """
        try:
            stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.is_deleted == False,  # noqa: E712
                    AgentMemory.embedding.isnot(None),
                )
            )
            if memory_type:
                stmt = stmt.where(AgentMemory.memory_type == memory_type)
            result = await self.db.execute(stmt)
            rows = result.scalars().all()

            triples: list[tuple[UUID, str, list[float]]] = []
            for r in rows:
                try:
                    emb = json.loads(r.embedding) if r.embedding else None
                    if emb:
                        triples.append((r.id, r.content, emb))
                except (json.JSONDecodeError, TypeError):
                    continue
            return triples
        except Exception:
            logger.exception("Memory get_with_embeddings failed")
            return []

    # ── 更新 ──

    async def record_access(self, memory_id: UUID) -> None:
        """记录一次记忆检索（access_count + 1，更新 last_accessed_at）。"""
        try:
            stmt = (
                update(AgentMemory)
                .where(AgentMemory.id == memory_id)
                .values(
                    access_count=AgentMemory.access_count + 1,
                    last_accessed_at=datetime.now(UTC),
                )
            )
            await self.db.execute(stmt)
            await self.db.flush()
        except Exception:
            logger.debug("Memory record_access failed, skipping", exc_info=True)

    # ── 删除 ──

    async def soft_delete(self, memory_id: UUID) -> bool:
        """软删除一条记忆。"""
        try:
            stmt = (
                select(AgentMemory)
                .where(AgentMemory.id == memory_id, AgentMemory.is_deleted == False)  # noqa: E712
            )
            result = await self.db.execute(stmt)
            memory = result.scalar_one_or_none()
            if memory is None:
                return False
            memory.is_deleted = True
            await self.db.flush()
            return True
        except Exception:
            logger.exception("Memory soft_delete failed")
            return False

    async def cleanup_expired(self, user_id: str) -> int:
        """清理用户的过期记忆（软删除）。返回清理条数。"""
        try:
            now = datetime.now(UTC)
            stmt = (
                select(AgentMemory)
                .where(
                    AgentMemory.user_id == user_id,
                    AgentMemory.is_deleted == False,  # noqa: E712
                    AgentMemory.expires_at.isnot(None),
                    AgentMemory.expires_at < now,
                )
            )
            result = await self.db.execute(stmt)
            expired = result.scalars().all()
            for m in expired:
                m.is_deleted = True
            await self.db.flush()
            if expired:
                logger.info("Memory cleanup: %d expired for user %s", len(expired), user_id)
            return len(expired)
        except Exception:
            logger.exception("Memory cleanup_expired failed")
            return 0
