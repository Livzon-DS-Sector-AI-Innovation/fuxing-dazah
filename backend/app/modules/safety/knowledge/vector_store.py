"""NumPy-accelerated vector store — fast in-memory cosine similarity search.

Replaces the per-query Python loop (2104 chunks × 2048 dims per query)
with a single pre-loaded numpy matrix multiplication (~5ms for any query).

At the current scale (2104 chunks × 2048d = 16MB), this outperforms
pgvector by avoiding the network round-trip. When the dataset grows
beyond ~100K chunks, switch to pgvector HNSW.

Usage:
    from app.modules.safety.knowledge.vector_store import VectorStore

    store = VectorStore(session)
    await store.refresh()  # load embeddings from DB
    results = await store.search(query_embedding, categories, top_k=30, filter_article_ids=[...])
    # -> list of (chunk_id, similarity_score)
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import RegulationChunk, SafetyKnowledgeArticle

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Refresh interval in seconds (0 = refresh on every query)
# 2026-09-02: 300→3600。26694 chunks（208.5MB）全量重载耗时 6-7 分钟，
# 5 分钟过期会让长任务（17:00 AI 日报批次）中途反复触发重载把任务拖到超时；
# 知识库为日更级别，1 小时刷新足够，且过期改走后台刷新不阻塞查询。
REFRESH_INTERVAL = 3600  # 1 hour


@dataclass
class VectorSearchResult:
    """Single vector search result."""
    chunk_id: UUID
    score: float  # cosine similarity


@dataclass
class VectorStoreState:
    """Immutable snapshot of the vector store at a point in time."""
    embeddings: np.ndarray  # shape (N, 2048), float32, L2-normalized
    chunk_ids: np.ndarray   # shape (N,), UUID strings
    article_ids: np.ndarray  # shape (N,), UUID strings (or empty string)
    categories: np.ndarray   # shape (N,), str
    loaded_at: float = field(default_factory=time.time)
    version: int = 0


class VectorStore:
    """NumPy-based in-memory vector store for fast cosine similarity search.

    Thread-safe: uses immutable state snapshots + atomic swap.
    Single writer (refresh), multiple readers (search).

    Performance characteristics (2104 chunks × 2048d):
      - Memory: ~16 MB (float32)
      - Load time: ~50ms (JSON parse + numpy conversion)
      - Search time: ~2-5ms (matrix multiplication)
      - vs current: ~500-2000ms (Python loop)
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory
        self._state: VectorStoreState | None = None
        self._last_refresh = 0.0
        # 2026-09-02 并发防护：多任务同时发现过期时只允许一个 refresh，
        # 其余继续用当前快照（此前无锁会并发重复全量加载 6-7 分钟×N）。
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None
        # 数据指纹 (count, max_updated_at)：未变化时跳过全量重载
        self._fingerprint: tuple[int, str] | None = None

    @property
    def is_loaded(self) -> bool:
        return self._state is not None and len(self._state.chunk_ids) > 0

    @property
    def size(self) -> int:
        return len(self._state.chunk_ids) if self._state else 0

    async def refresh(self, session: AsyncSession | None = None) -> int:
        """Reload all embeddings from the database into numpy arrays.

        数据指纹（count + max updated_at）未变化时跳过全量重载，仅续期。

        Returns the number of chunks loaded.
        """
        close_session = False
        if session is None:
            from app.core.database import async_session_factory
            factory = self._session_factory or async_session_factory
            session = factory()
            close_session = True

        try:
            # 指纹检查：数据未变 → 跳过分钟级全量加载（26694 chunks/208.5MB）
            join_cond = RegulationChunk.article_id == SafetyKnowledgeArticle.id
            where_conds = (
                RegulationChunk.embedding.isnot(None),
                RegulationChunk.is_deleted == False,  # noqa: E712
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
            fp_result = await session.execute(
                select(
                    func.count(RegulationChunk.id),
                    func.max(RegulationChunk.updated_at),
                )
                .join(SafetyKnowledgeArticle, join_cond)
                .where(*where_conds)
            )
            fp_row = fp_result.one()
            fingerprint = (int(fp_row[0] or 0), str(fp_row[1] or ""))
            if (
                self._state is not None
                and self._fingerprint == fingerprint
                and len(self._state.chunk_ids) == fingerprint[0]
            ):
                self._last_refresh = time.time()
                logger.debug(
                    "VectorStore: fingerprint unchanged (%d chunks), skip reload",
                    fingerprint[0],
                )
                return len(self._state.chunk_ids)

            t0 = time.perf_counter()

            stmt = (
                select(
                    RegulationChunk.id,
                    RegulationChunk.embedding,
                    RegulationChunk.article_id,
                    RegulationChunk.doc_category,
                )
                .join(SafetyKnowledgeArticle, join_cond)
                .where(*where_conds)
            )
            result = await session.execute(stmt)
            rows = result.all()

            if not rows:
                logger.warning("VectorStore: no chunks with embeddings found")
                return 0

            # 2026-09-03：27k 行 × 45KB JSON 解析为分钟级纯 CPU 循环，
            # 直接跑在事件循环线程会冻结整个后端（所有 async 调用停摆，
            # embedding/chat 计时被拉长数十秒）——挪线程池执行。
            state = await asyncio.to_thread(_build_state_from_rows, rows)

            self._state = state
            self._fingerprint = fingerprint
            self._last_refresh = time.time()

            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "VectorStore: loaded %d chunks in %.1fms (%.1fMB)",
                len(state.chunk_ids), elapsed, state.embeddings.nbytes / (1024 * 1024),
            )
            return len(state.chunk_ids)

        finally:
            if close_session:
                await session.close()

    async def ensure_loaded(self, session: AsyncSession) -> bool:
        """Refresh if not loaded or stale. Returns True if ready.

        - 冷启动（未加载）：持锁同步加载，首个调用者加载，并发者等待复用
        - 已加载但过期：单飞后台刷新（自建 session），查询立即返回当前快照
          （26694 chunks 全量重载为分钟级，不能阻塞在查询路径上）
        """
        if not self.is_loaded:
            async with self._refresh_lock:
                if not self.is_loaded:  # double-check：等待期间可能已被加载
                    await self.refresh(session)
            return self.is_loaded
        if time.time() - self._last_refresh > REFRESH_INTERVAL:
            self._start_background_refresh()
        return self.is_loaded

    def _start_background_refresh(self) -> None:
        """单飞后台刷新：同一时刻至多一个后台刷新任务，不阻塞当前查询。"""
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        # 先续期，避免刷新期间其他调用重复排队
        self._last_refresh = time.time()

        async def _bg_refresh() -> None:
            try:
                async with self._refresh_lock:
                    await self.refresh(None)
            except Exception:
                logger.exception("VectorStore 后台刷新失败，继续使用当前快照")

        try:
            self._refresh_task = asyncio.create_task(_bg_refresh())
        except RuntimeError:
            # 无运行中的事件循环（同步上下文调用）→ 放弃，下次再刷
            pass

    async def search(
        self,
        query_embedding: list[float],
        categories: list[str] | None = None,
        top_k: int = 30,
        filter_article_ids: list[UUID] | None = None,
        session: AsyncSession | None = None,
    ) -> list[VectorSearchResult]:
        """Search for chunks with highest cosine similarity to the query.

        Args:
            query_embedding: The query vector (2048 dimensions)
            categories: Filter by doc_category (None = all)
            top_k: Number of top results to return
            filter_article_ids: Restrict to these article_ids
            session: DB session for lazy refresh

        Returns:
            List of VectorSearchResult sorted by similarity descending
        """
        if session:
            await self.ensure_loaded(session)

        if not self.is_loaded:
            return []

        state = self._state  # atomic snapshot
        query_vec = np.array(query_embedding, dtype=np.float32)

        # Normalize query vector
        q_norm = np.linalg.norm(query_vec)
        if q_norm > 0:
            query_vec = query_vec / q_norm

        # Build boolean mask for filters
        mask = np.ones(len(state.chunk_ids), dtype=bool)

        if categories:
            cat_mask = np.isin(state.categories, np.array(categories))
            mask &= cat_mask

        if filter_article_ids:
            art_ids_set = {str(aid) for aid in filter_article_ids}
            art_mask = np.array([aid in art_ids_set for aid in state.article_ids])
            mask &= art_mask

        if not mask.any():
            return []

        # Compute cosine similarities (dot product of normalized vectors)
        if mask.all():
            similarities = state.embeddings @ query_vec
        else:
            # Only compute for masked rows
            masked_embs = state.embeddings[mask]
            similarities_masked = masked_embs @ query_vec
            # Map back to full indices
            similarities = np.zeros(len(state.chunk_ids), dtype=np.float32)
            similarities[mask] = similarities_masked

        # Get top-k indices
        k = min(top_k, len(similarities))
        if k == 0:
            return []

        # Use argpartition for efficiency (O(n) vs O(n log n))
        if k < len(similarities):
            top_indices = np.argpartition(similarities, -k)[-k:]
            # Sort the top-k by similarity descending
            top_indices = top_indices[np.argsort(similarities[top_indices])[::-1]]
        else:
            top_indices = np.argsort(similarities)[::-1]

        results = []
        for idx in top_indices:
            score = float(similarities[idx])
            if score > 0.01:  # minimum threshold
                results.append(VectorSearchResult(
                    chunk_id=UUID(state.chunk_ids[idx]),
                    score=score,
                ))

        return results

    def invalidate(self) -> None:
        """Force refresh on next query."""
        self._last_refresh = 0.0


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

_EMBEDDING_DIMS = 2048


def _build_state_from_rows(rows: list) -> VectorStoreState:
    """纯 CPU 同步构建快照（线程池执行，勿在事件循环线程调用）。

    rows: (chunk_id, embedding, article_id, doc_category) 元组列表。
    """
    n = len(rows)
    dims = _EMBEDDING_DIMS
    emb_matrix = np.empty((n, dims), dtype=np.float32)
    chunk_ids = np.empty(n, dtype=object)
    article_ids = np.empty(n, dtype=object)
    categories = np.empty(n, dtype=object)

    for i, row in enumerate(rows):
        chunk_ids[i] = str(row[0])
        emb = _parse_embedding_fast(row[1])
        if emb.shape[0] == dims:
            emb_matrix[i] = emb
        else:
            # Dimension mismatch — pad or truncate
            if emb.shape[0] > dims:
                emb_matrix[i] = emb[:dims]
            else:
                emb_matrix[i] = np.pad(emb, (0, dims - emb.shape[0]))
        article_ids[i] = str(row[2]) if row[2] else ""
        categories[i] = row[3] or ""

    # L2-normalize for cosine similarity via dot product
    norms = np.linalg.norm(emb_matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)  # avoid div-by-zero
    emb_matrix = emb_matrix / norms

    return VectorStoreState(
        embeddings=emb_matrix,
        chunk_ids=chunk_ids,
        article_ids=article_ids,
        categories=categories,
        loaded_at=time.time(),
        version=int(time.time()),
    )


def _parse_embedding_fast(raw: str | list | None) -> np.ndarray:
    """Fast embedding parser — JSON string/list → float32 ndarray.

    2026-09-02：np.asarray C 级转换替代 [float(v) for v in parsed]
    （26694 chunks × 2048 dims ≈ 5460 万次 Python float() 调用是全量
    加载耗时 6-7 分钟的主因之一）。
    """
    empty = np.empty(0, dtype=np.float32)
    if raw is None:
        return empty
    try:
        if isinstance(raw, str):
            raw = _json.loads(raw)
        if isinstance(raw, list):
            return np.asarray(raw, dtype=np.float32)
    except (ValueError, TypeError, _json.JSONDecodeError):
        pass
    return empty


# ═══════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════

_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Get or create the singleton VectorStore instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
