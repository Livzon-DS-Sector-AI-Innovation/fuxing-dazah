"""Adaptive hybrid retriever — vector + full-text + RRF fusion.

Searches regulation_chunks for clauses relevant to a hazard description.
Supports adaptive depth (complexity-dependent), domain quotas, and graceful
degradation: vector search → PostgreSQL full-text → empty (graceful).

Two-level architecture:
  SafetyKnowledgeRetriever  (unified entry → 3-layer pipeline)
    ├── Layer 1: EntityExtractor + GraphRetriever → article_id set
    └── Layer 2: HybridRetriever (with filter_article_ids) → top-k chunks

Usage:
    # Unified entry (preferred):
    from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever
    retriever = SafetyKnowledgeRetriever(session)
    context = await retriever.retrieve(description="防爆电箱堵头未封堵")
    # -> KnowledgeContext(chunks, graph_path, markdown, ...)

    # Direct hybrid search (backward-compatible):
    from app.modules.safety.knowledge.retriever import HybridRetriever
    from app.modules.safety.knowledge.embedding_service import EmbeddingService
    embedder = EmbeddingService(api_key="...", base_url="...")
    retriever = HybridRetriever(session, embedder)
    report = await retriever.retrieve(description="...", target_chunks=8)
    # -> RetrievalReport(results=...)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.modules.safety.knowledge.bm25 import BM25Scorer, get_bm25_scorer
from app.modules.safety.knowledge.embedding_service import (
    EmbeddingService,
    cosine_similarity,
    get_shared_embedder,
)
from app.modules.safety.knowledge.reranker import Reranker
from app.modules.safety.knowledge.vector_store import VectorStore, get_vector_store
from app.modules.safety.models import RegulationChunk, SafetyKnowledgeArticle

if TYPE_CHECKING:
    from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)

# RRF constant
RRF_K = 60
# Minimum RRF score to include a chunk
SCORE_THRESHOLD = 0.01
# 全局检索并发闸门：跨所有任务/记录限制同时进行的 RAG 检索数。
# 2026-09-02：17:00 多个 AI 日报任务并行、各自对每条记录做 RAG 检索，
# 并发拖慢共享检索链路（单次 2.3s 被拉高到 60s+），这里使用模块级信号量统一限流。
_RETRIEVE_SEM = asyncio.Semaphore(6)

# BM25 chunk 索引（模块级，跨 HybridRetriever 实例共享）。
# 2026-09-03 修复：此前挂在实例上，而 BM25Scorer 是全局单例 —— 首个实例
# 建好索引后，后续新实例因单例已 _indexed 跳过构建、又不持有 chunk 映射，
# 导致 _bm25_search 恒返回空、文本召回在进程生命周期内一直失效。
_bm25_chunks: dict[int, "RegulationChunk"] = {}
_bm25_index_lock = asyncio.Lock()


# ═══════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════


@dataclass
class RetrievalResult:
    """A retrieved regulation chunk with metadata and relevance info."""

    chunk_id: str
    chunk_text: str
    source_doc: str
    source_article: str
    doc_category: str
    priority: str
    score: float  # RRF fusion score
    vector_score: float = 0.0
    text_score: float = 0.0
    retrieval_path: str = ""  # "vector", "text", "both"
    article_id: str = ""  # UUID of the parent SafetyKnowledgeArticle


@dataclass
class RetrievalReport:
    """Full retrieval report for audit trail."""

    results: list[RetrievalResult]
    total_candidates: int
    vector_hits: int
    text_hits: int
    degradation_level: str  # "full", "text_only", "fallback"


@dataclass
class KnowledgeContext:
    """Unified knowledge retrieval result — consumed by all AI scenarios.

    Three consumers use this:
      - Info query:   build_chat_context(context) → chat AI
      - Hazard ID:    build_injection_context(context) → AIHazardIdentifier
      - Hazard ident: build_injection_context(context) → orchestrator scripts
    """

    chunks: list[RetrievalResult] = field(default_factory=list)
    graph_path: str | None = None          # 图谱导航路径（Markdown）
    article_ids: list[UUID] = field(default_factory=list)
    markdown: str = ""                     # 可直接注入 AI prompt 的文本
    degradation: str = "full"              # full / graph_only / text_only / llm_expanded / fallback


# ═══════════════════════════════════════════════════════════════
# HybridRetriever
# ═══════════════════════════════════════════════════════════════


class HybridRetriever:
    """Adaptive hybrid retrieval: vector + full-text + RRF fusion.

    Degradation path:
    1. Full hybrid (vector + text + RRF) — primary
    2. Text-only (PostgreSQL full-text search) — embedding unavailable
    3. Empty — no results found (graceful degradation)

    The ``filter_article_ids`` parameter on ``retrieve()`` and internal
    methods narrows the search to chunks whose ``article_id`` is in the
    given set.  This is driven by the graph-navigation layer and
    typically reduces the candidate set by 80-90 %.
    """

    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingService | None = None,
        default_categories: list[str] | None = None,
        ai_service: AIService | None = None,
        vector_store: VectorStore | None = None,
        bm25: BM25Scorer | None = None,
        reranker: Reranker | None = None,
    ):
        self.session = session
        self.embedder = embedder
        self.ai_service = ai_service
        self.vector_store = vector_store  # None = use singleton
        self.bm25 = bm25  # None = use singleton
        self.reranker = reranker  # None = no reranking
        self.default_categories = default_categories or [
            "laws_regulations", "standards", "management_systems", "sds",
        ]
        self._bm25_ready = False  # lazy init

    async def retrieve(
        self,
        description: str,
        categories: list[str] | None = None,
        target_chunks: int = 8,
        max_chunks: int = 30,
        min_chunks: int = 3,
        filter_article_ids: list[UUID] | None = None,
        boost_article_ids: list[UUID] | None = None,
    ) -> RetrievalReport:
        """Main retrieval entry point（全局并发闸门 + 委托内部实现）。"""
        async with _RETRIEVE_SEM:
            return await self._retrieve_locked(
                description=description,
                categories=categories,
                target_chunks=target_chunks,
                max_chunks=max_chunks,
                min_chunks=min_chunks,
                filter_article_ids=filter_article_ids,
                boost_article_ids=boost_article_ids,
            )

    async def _retrieve_locked(
        self,
        description: str,
        categories: list[str] | None = None,
        target_chunks: int = 8,
        max_chunks: int = 30,
        min_chunks: int = 3,
        filter_article_ids: list[UUID] | None = None,
        boost_article_ids: list[UUID] | None = None,
    ) -> RetrievalReport:
        """内部检索实现（经 retrieve() 限流后调用）。

        Args:
            description: Hazard description text
            categories: Document categories to search (None = default)
            target_chunks: Target number of results
            max_chunks: Hard cap on results
            min_chunks: Minimum before triggering text-only fallback
            filter_article_ids: Optional article IDs to restrict search
                (from knowledge-graph navigation). When provided, only
                chunks whose article_id is in this list are considered.
            boost_article_ids: Optional article IDs to boost (soft signal).
                Chunks matching these IDs get a score bonus after RRF fusion.
                Unlike filter_article_ids, non-matching chunks are NOT excluded.

        Returns:
            RetrievalReport with ranked results and degradation info
        """
        categories = categories or self.default_categories
        total_candidates = await self._count_chunks(categories, filter_article_ids)

        # ═══ Attempt 1: Full hybrid ═══
        if self.embedder:
            try:
                is_avail = await self.embedder.is_available()
            except Exception:
                is_avail = False

            if is_avail:
                results = await self._hybrid_search(
                    description, categories, target_chunks, max_chunks,
                    filter_article_ids=filter_article_ids,
                    boost_article_ids=boost_article_ids,
                )
                if len(results) >= min_chunks:
                    return RetrievalReport(
                        results=results,
                        total_candidates=total_candidates,
                        vector_hits=sum(1 for r in results if r.vector_score > 0),
                        text_hits=sum(1 for r in results if r.text_score > 0),
                        degradation_level="full",
                    )
                logger.warning(
                    "Hybrid search returned only %d results (<%d min), "
                    "falling back to text-only", len(results), min_chunks,
                )

        # ═══ Attempt 2: LLM-expanded text search ═══
        if self.ai_service:
            try:
                results = await self._llm_text_search(
                    description, categories, target_chunks,
                    filter_article_ids=filter_article_ids,
                )
                if results:
                    return RetrievalReport(
                        results=results,
                        total_candidates=total_candidates,
                        vector_hits=0,
                        text_hits=len(results),
                        degradation_level="llm_expanded",
                    )
            except Exception as e:
                logger.warning("LLM query expansion failed: %s", e)

        # ═══ Attempt 3: Text-only (keyword extraction) ═══
        results = await self._text_search(
            description, categories, target_chunks,
            filter_article_ids=filter_article_ids,
        )
        if results:
            return RetrievalReport(
                results=results,
                total_candidates=total_candidates,
                vector_hits=0,
                text_hits=len(results),
                degradation_level="text_only",
            )

        # ═══ Attempt 4: Broad text search (relaxed) ═══
        results = await self._text_search(
            description, categories, target_chunks * 2, relaxed=True,
            filter_article_ids=filter_article_ids,
        )
        if results:
            return RetrievalReport(
                results=results[:target_chunks],
                total_candidates=total_candidates,
                vector_hits=0,
                text_hits=len(results),
                degradation_level="text_only",
            )

        # ═══ Attempt 5: All chunks (emergency fallback) ═══
        logger.warning("All retrieval attempts failed — returning empty")
        return RetrievalReport(
            results=[],
            total_candidates=total_candidates,
            vector_hits=0,
            text_hits=0,
            degradation_level="fallback",
        )

    async def retrieve_for_test(
        self,
        description: str,
        categories: list[str] | None = None,
        target_chunks: int = 8,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RetrievalResult]:
        """Convenience wrapper for tests — returns results list directly."""
        report = await self.retrieve(
            description, categories, target_chunks,
            filter_article_ids=filter_article_ids,
        )
        return report.results

    # ── Internal: LLM-expanded search ──

    async def _llm_text_search(
        self,
        description: str,
        categories: list[str],
        target_chunks: int,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RetrievalResult]:
        """Use LLM to expand query with standard terminology, then text-search."""
        from app.modules.safety.knowledge.llm_retriever import LLMQueryExpander

        assert self.ai_service is not None
        expander = LLMQueryExpander(self.ai_service)
        keywords = await expander.expand(description)

        # Search with each expanded keyword, merge results
        results: dict[str, RetrievalResult] = {}
        for kw in keywords:
            chunks = await self._text_search_single(
                kw, categories, limit=5, filter_article_ids=filter_article_ids,
            )
            for chunk in chunks:
                rid = str(chunk.id)
                if rid not in results:
                    results[rid] = RetrievalResult(
                        chunk_id=rid,
                        chunk_text=chunk.chunk_text or "",
                        source_doc=chunk.doc_title or "",
                        source_article=chunk.article_ref or chunk.chapter_title or "",
                        doc_category=chunk.doc_category or "",
                        priority=chunk.priority or "P2",
                        score=1.0,
                        text_score=1.0,
                        retrieval_path="llm_text",
                        article_id=str(chunk.article_id) if chunk.article_id else "",
                    )

        # Score: more keyword matches = higher rank
        for rid, result in results.items():
            text = result.chunk_text
            result.score = sum(1 for kw in keywords if kw in text)

        ranked = sorted(results.values(), key=lambda r: r.score, reverse=True)
        return ranked[:target_chunks]

    async def _text_search_single(
        self,
        query: str,
        categories: list[str],
        limit: int,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RegulationChunk]:
        """Text search for a single query string — delegate to _fulltext_search."""
        return await self._fulltext_search(
            query, categories, limit, filter_article_ids=filter_article_ids,
        )

    # ── Internal: Hybrid ──

    async def _hybrid_search(
        self,
        description: str,
        categories: list[str],
        target_chunks: int,
        max_chunks: int,
        filter_article_ids: list[UUID] | None = None,
        boost_article_ids: list[UUID] | None = None,
    ) -> list[RetrievalResult]:
        """Vector + full-text + RRF fusion + optional graph boost."""
        assert self.embedder is not None

        # Generate search queries from description
        queries = self._extract_keywords(description)

        # 1. Vector search
        vec_results: dict[str, RetrievalResult] = {}
        try:
            query_embedding = await self.embedder.embed(description)
            vec_chunks = await self._vector_search(
                query_embedding, categories, max_chunks * 2,
                filter_article_ids=filter_article_ids,
            )
            # 相似度直接来自 VectorStore（numpy 点积），不再回捞
            # chunk.embedding 用 Python 循环重算 cosine。
            for rank, (chunk, sim) in enumerate(vec_chunks):
                rid = str(chunk.id)
                vec_results[rid] = RetrievalResult(
                    chunk_id=rid,
                    chunk_text=chunk.chunk_text or "",
                    source_doc=chunk.doc_title or "",
                    source_article=chunk.article_ref or "",
                    doc_category=chunk.doc_category or "",
                    priority=chunk.priority or "P2",
                    score=0.0,
                    vector_score=sim,
                    retrieval_path="vector",
                    article_id=str(chunk.article_id) if chunk.article_id else "",
                )
        except Exception as e:
            logger.warning("Vector search failed: %s", e)

        # 2. Full-text search
        text_results: dict[str, RetrievalResult] = {}
        try:
            for query in queries:
                text_chunks = await self._fulltext_search(
                    query, categories, max_chunks,
                    filter_article_ids=filter_article_ids,
                )
                for rank, chunk in enumerate(text_chunks):
                    rid = str(chunk.id)
                    if rid in text_results:
                        continue
                    text_results[rid] = RetrievalResult(
                        chunk_id=rid,
                        chunk_text=chunk.chunk_text or "",
                        source_doc=chunk.doc_title or "",
                        source_article=chunk.article_ref or "",
                        doc_category=chunk.doc_category or "",
                        priority=chunk.priority or "P2",
                        score=0.0,
                        retrieval_path="text",
                        article_id=str(chunk.article_id) if chunk.article_id else "",
                    )
        except Exception as e:
            logger.warning("Full-text search failed: %s", e)

        # 3. RRF fusion
        fused = _rrf_fusion(
            list(vec_results.values()),
            list(text_results.values()),
            k=RRF_K,
        )

        # Merge vector_score and text_score from individual results
        for r in fused:
            if r.chunk_id in vec_results:
                r.vector_score = vec_results[r.chunk_id].vector_score
            if r.chunk_id in text_results:
                r.text_score = 1.0  # text match = binary
            if r.vector_score > 0 and r.text_score > 0:
                r.retrieval_path = "both"

        # 4. 按文档去重（在 Reranker 之前）：
        #    每个 source_doc 只保留 RRF 得分最高的 chunk，
        #    确保进入 Reranker 的候选集具备文档多样性。
        #    否则 Reranker 可能将 top-k 全部集中在 2-3 个文档上，
        #    去重后只剩下 2-3 个独特文档，AI 可用上下文大幅缩水。
        deduped: list[RetrievalResult] = []
        seen_docs: set[str] = set()
        for r in fused:
            if r.source_doc not in seen_docs:
                seen_docs.add(r.source_doc)
                deduped.append(r)
        if len(deduped) < len(fused):
            logger.debug(
                "Hybrid pre-dedup: %d chunks → %d unique docs", len(fused), len(deduped),
            )
        fused = deduped

        # 5. Cross-encoder reranking (LLM precision boost)
        #    此时候选集已去重，每个文档只有一个代表 chunk，Reranker
        #    在多样化文档上打分，不会出现"同一文档霸榜"的问题。
        if self.reranker and self.reranker.available and len(fused) > target_chunks:
            try:
                fused = await self.reranker.rerank(
                    query=description,
                    candidates=fused,
                    top_k=target_chunks,
                )
            except Exception as e:
                logger.warning("Reranker failed, continuing with RRF ranking: %s", e)

        # 6. Filter by score threshold
        fused = [r for r in fused if r.score > SCORE_THRESHOLD]

        # 7. 图谱软加分：图谱导航匹配到的文档获得额外权重，
        #    但非匹配文档不会被排除（与 filter_article_ids 不同）。
        if boost_article_ids:
            boost_set: set[str] = {str(aid) for aid in boost_article_ids}
            graph_boost = 0.06  # 图谱匹配文档的加分幅度（6%）
            boosted = 0
            for r in fused:
                if r.article_id in boost_set:
                    r.score += graph_boost
                    boosted += 1
            if boosted:
                fused.sort(key=lambda r: r.score, reverse=True)
                logger.debug(
                    "Graph boost: %d/%d chunks boosted (+%.2f)", boosted, len(fused), graph_boost,
                )

        return fused[:target_chunks]

    # ── Internal: Text-only ──

    async def _text_search(
        self,
        description: str,
        categories: list[str],
        target_chunks: int,
        relaxed: bool = False,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RetrievalResult]:
        """PostgreSQL full-text search (tsvector)."""
        queries = self._extract_keywords(description)
        results: dict[str, RetrievalResult] = {}

        for query in queries:
            try:
                chunks = await self._fulltext_search(
                    query, categories, target_chunks, relaxed,
                    filter_article_ids=filter_article_ids,
                )
                for chunk in chunks:
                    rid = str(chunk.id)
                    if rid not in results:
                        article_ref = chunk.article_ref or chunk.chapter_title or ""
                        results[rid] = RetrievalResult(
                            chunk_id=rid,
                            chunk_text=chunk.chunk_text or "",
                            source_doc=chunk.doc_title or "",
                            source_article=article_ref,
                            doc_category=chunk.doc_category or "",
                            priority=chunk.priority or "P2",
                            score=1.0 / (len(results) + RRF_K),
                            text_score=1.0,
                            retrieval_path="text",
                            article_id=str(chunk.article_id) if chunk.article_id else "",
                        )
            except Exception as e:
                logger.warning("Text search failed for query '%s': %s", query, e)

        return sorted(results.values(), key=lambda r: r.score, reverse=True)[:target_chunks]

    # ── DB queries ──

    async def _vector_search(
        self,
        query_embedding: list[float],
        categories: list[str],
        limit: int,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[tuple[RegulationChunk, float]]:
        """Find chunks by cosine similarity to query embedding.

        Uses numpy-accelerated VectorStore for sub-10ms search.
        Falls back to the legacy Python-loop approach if VectorStore is not loaded.

        Returns (chunk, similarity) pairs — similarity comes straight from
        VectorStore, no re-scoring against the raw embedding payload.
        """
        # ── Primary: numpy VectorStore (sub-10ms) ──
        store = self.vector_store or get_vector_store()
        if store.is_loaded or await store.ensure_loaded(self.session):
            try:
                vs_results = await store.search(
                    query_embedding=query_embedding,
                    categories=categories,
                    top_k=limit,
                    filter_article_ids=filter_article_ids,
                )
                if vs_results:
                    # Fetch chunk text from DB by IDs（defer embedding：结果分数
                    # 已由 VectorStore 给出，无需回捞 45KB/行的向量原文）
                    chunk_ids = [r.chunk_id for r in vs_results]
                    score_map = {r.chunk_id: r.score for r in vs_results}

                    stmt = (
                        select(RegulationChunk)
                        .options(defer(RegulationChunk.embedding))
                        .where(RegulationChunk.id.in_(chunk_ids))
                    )
                    result = await self.session.execute(stmt)
                    chunks = list(result.scalars().all())

                    # Sort by vector similarity score
                    chunks.sort(key=lambda c: score_map.get(c.id, 0), reverse=True)
                    return [(c, score_map.get(c.id, 0.0)) for c in chunks[:limit]]
            except Exception as e:
                logger.warning("VectorStore search failed, falling back to legacy: %s", e)

        # ── Fallback: legacy in-memory cosine similarity ──
        return await self._vector_search_legacy(
            query_embedding, categories, limit, filter_article_ids,
        )

    async def _vector_search_legacy(
        self,
        query_embedding: list[float],
        categories: list[str],
        limit: int,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[tuple[RegulationChunk, float]]:
        """Legacy vector search — load all chunks and compute similarity in Python.

        Kept as fallback for when VectorStore is not initialized.
        """
        stmt = (
            select(RegulationChunk)
            .join(
                SafetyKnowledgeArticle,
                RegulationChunk.article_id == SafetyKnowledgeArticle.id,
            )
            .where(
                RegulationChunk.doc_category.in_(categories),
                RegulationChunk.embedding.isnot(None),
                RegulationChunk.is_deleted == False,  # noqa: E712
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
            .limit(limit * 3)
        )
        if filter_article_ids:
            stmt = stmt.where(RegulationChunk.article_id.in_(filter_article_ids))

        result = await self.session.execute(stmt)
        chunks = result.scalars().all()

        scored = []
        for chunk in chunks:
            emb = _parse_embedding(chunk.embedding)
            if emb:
                sim = cosine_similarity(query_embedding, emb)
                scored.append((sim, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(chunk, sim) for sim, chunk in scored[:limit]]

    async def _fulltext_search(
        self,
        query: str,
        categories: list[str],
        limit: int,
        relaxed: bool = False,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RegulationChunk]:
        """Text search using BM25 scoring with TF-IDF weighting.

        Falls back to legacy n-gram overlap if BM25 index is not built.
        """
        # ── Primary: BM25 (TF-IDF weighted) ──
        bm25 = self.bm25 or get_bm25_scorer()
        if not self._bm25_ready:
            await self._ensure_bm25_index(bm25, categories)

        if self._bm25_ready:
            try:
                return await self._bm25_search(
                    bm25, query, categories, limit, filter_article_ids,
                )
            except Exception as e:
                logger.warning("BM25 search failed, falling back to n-gram: %s", e)

        # ── Fallback: legacy n-gram overlap ──
        return await self._fulltext_search_legacy(
            query, categories, limit, filter_article_ids=filter_article_ids,
        )

    async def _ensure_bm25_index(
        self, bm25: BM25Scorer, categories: list[str],
    ) -> None:
        """Build BM25 index from all chunks in the given categories.

        索引与 chunk 映射均为模块级共享；构建持锁，进程内只做一次。
        2026-09-03：加载时 defer embedding 列 —— 每行 45KB 文本对 BM25
        分词无用，27k 行全拖曾让索引构建多花数秒。
        """
        if bm25._indexed and _bm25_chunks:
            self._bm25_ready = True
            return

        async with _bm25_index_lock:
            if bm25._indexed and _bm25_chunks:  # double-check：等待期间已建好
                self._bm25_ready = True
                return

            stmt = (
                select(RegulationChunk)
                .options(defer(RegulationChunk.embedding))
                .join(
                    SafetyKnowledgeArticle,
                    RegulationChunk.article_id == SafetyKnowledgeArticle.id,
                )
                .where(
                    RegulationChunk.doc_category.in_(categories),
                    RegulationChunk.is_deleted == False,  # noqa: E712
                    SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
                )
            )
            result = await self.session.execute(stmt)
            chunks = result.scalars().all()

            if not chunks:
                return

            texts: list[str] = []
            for i, chunk in enumerate(chunks):
                _bm25_chunks[i] = chunk
                texts.append(chunk.chunk_text or "")

            bm25.index(texts)
            self._bm25_ready = True
            logger.info("BM25 index built: %d chunks", len(texts))

    async def _bm25_search(
        self,
        bm25: BM25Scorer,
        query: str,
        categories: list[str],
        limit: int,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RegulationChunk]:
        """Score all chunks via BM25 and return top matches."""
        if not _bm25_chunks:
            return []

        # Get top-k BM25 scores
        top_indices = bm25.score_top_k(query, top_k=limit * 2, min_score=0.01)

        results: list[RegulationChunk] = []
        seen_ids: set[str] = set()

        for idx, score in top_indices:
            chunk = _bm25_chunks.get(idx)
            if chunk is None:
                continue
            cid = str(chunk.id)
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            # Apply filters
            if chunk.doc_category not in categories:
                continue
            if filter_article_ids and chunk.article_id not in filter_article_ids:
                continue

            results.append(chunk)
            if len(results) >= limit:
                break

        return results

    async def _fulltext_search_legacy(
        self,
        query: str,
        categories: list[str],
        limit: int,
        filter_article_ids: list[UUID] | None = None,
    ) -> list[RegulationChunk]:
        """Legacy text search — n-gram keyword overlap (fallback)."""
        stmt = (
            select(RegulationChunk)
            .options(defer(RegulationChunk.embedding))
            .join(
                SafetyKnowledgeArticle,
                RegulationChunk.article_id == SafetyKnowledgeArticle.id,
            )
            .where(
                RegulationChunk.doc_category.in_(categories),
                RegulationChunk.is_deleted == False,  # noqa: E712
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
        )
        if filter_article_ids:
            stmt = stmt.where(RegulationChunk.article_id.in_(filter_article_ids))

        result = await self.session.execute(stmt)
        all_chunks = result.scalars().all()

        if not all_chunks:
            return []

        keywords = _extract_keywords_from_query(query)
        scored = []
        for chunk in all_chunks:
            text = chunk.chunk_text or ""
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored[:limit]]

    async def _count_chunks(
        self,
        categories: list[str],
        filter_article_ids: list[UUID] | None = None,
    ) -> int:
        """Count total chunks in given categories.

        2026-09-03：改为 DB 端 count —— 此前 select 全实体到 Python 再 len()，
        27k chunks（含每行 45KB embedding 文本）每次检索多付 ~6s。
        """
        stmt = (
            select(func.count(RegulationChunk.id))
            .join(
                SafetyKnowledgeArticle,
                RegulationChunk.article_id == SafetyKnowledgeArticle.id,
            )
            .where(
                RegulationChunk.doc_category.in_(categories),
                RegulationChunk.is_deleted == False,  # noqa: E712
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
        )
        if filter_article_ids:
            stmt = stmt.where(RegulationChunk.article_id.in_(filter_article_ids))
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0)

    # ── Keyword extraction ──

    @staticmethod
    def _extract_keywords(description: str) -> list[str]:
        """Extract search queries from hazard description.

        Returns the full description as primary query, plus key phrases.
        """
        queries = [description.strip()]
        # Split on common delimiters for sub-queries
        parts = re_split_description(description)
        queries.extend(p for p in parts if len(p) >= 4 and p not in queries)
        return queries[:5]


# ═══════════════════════════════════════════════════════════════
# SafetyKnowledgeRetriever — Unified Entry Point
# ═══════════════════════════════════════════════════════════════


class SafetyKnowledgeRetriever:
    """Unified knowledge retriever — 3-layer pipeline for all AI scenarios.

    Pipeline:
      1. EntityExtractor → extract safety entities from query text
      2. GraphRetriever   → match entities in knowledge graph, BFS to article_ids
      3. HybridRetriever  → search chunks filtered by article_ids (or full scan)

    Degradation: each layer fails independently — if entity extraction or
    graph navigation returns nothing, HybridRetriever runs on the full
    chunk set (same behaviour as before this class existed).

    Usage::

        retriever = SafetyKnowledgeRetriever(session)
        context = await retriever.retrieve(description="防爆堵头未封堵")
        # info query:
        chat_ctx = retriever.build_chat_context(context)
        # hazard identification:
        injection_ctx = retriever.build_injection_context(context)
    """

    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingService | None = None,
        ai_service: AIService | None = None,
    ):
        self.session = session
        # 共享单例：复用 httpx 连接池与 is_available 探测结果，
        # 避免每次请求重复探测一次 embedding API
        self.embedder = embedder or get_shared_embedder()
        self.ai_service = ai_service

        # Lazy-init sub-components
        self._graph_retriever = None
        self._entity_extractor = None
        self._hybrid_retriever = None

    @property
    def graph_retriever(self):
        if self._graph_retriever is None:
            from app.modules.safety.knowledge.graph_retriever import GraphRetriever
            self._graph_retriever = GraphRetriever(self.session)
        return self._graph_retriever

    @property
    def entity_extractor(self):
        if self._entity_extractor is None:
            # ── Primary: Rule-based (zero LLM, sub-ms latency) ──
            from app.modules.safety.knowledge.entity_extractor_rule import (
                RuleBasedEntityExtractor,
            )
            self._entity_extractor = RuleBasedEntityExtractor()
        return self._entity_extractor

    @property
    def hybrid_retriever(self) -> HybridRetriever:
        if self._hybrid_retriever is None:
            self._hybrid_retriever = HybridRetriever(
                self.session, self.embedder, ai_service=self.ai_service,
                reranker=Reranker(self.ai_service) if self.ai_service else None,
            )
        return self._hybrid_retriever

    # ── Public API ──

    async def retrieve(
        self,
        description: str,
        categories: list[str] | None = None,
        target_chunks: int = 8,
        max_hops: int = 2,
    ) -> KnowledgeContext:
        """Unified retrieval entry point — all consumers call this method.

        Args:
            description: Hazard description or user query text
            categories: Document categories to search (None = default)
            target_chunks: Target number of chunks to return
            max_hops: Max graph traversal hops (Layer 1)

        Returns:
            KnowledgeContext with chunks, graph_path, and injection-ready markdown
        """
        # ═══ Cache check ═══
        from app.modules.safety.knowledge.cache import (
            context_from_dict,
            context_to_dict,
            get_rag_cache,
            set_rag_cache,
        )

        cached = await get_rag_cache(
            query=description,
            categories=categories,
            target_chunks=target_chunks,
            max_hops=max_hops,
        )
        if cached is not None:
            ctx = context_from_dict(cached)
            logger.debug(
                "SafetyKnowledgeRetriever: cache HIT for query=%r", description[:60],
            )
            return ctx

        graph_path: str | None = None
        article_ids: list[UUID] = []
        degradation = "full"

        # ═══ Layer 1: Knowledge Graph Navigation ═══
        try:
            entities = await self.entity_extractor.extract(description)
            entity_names: list[str] = []

            if entities:
                entity_names = [e.name for e in entities]
                logger.debug("EntityExtractor: %d entities → %s", len(entities), entity_names)
            else:
                # Fallback: keyword scan against graph entity names
                # AI extraction can be unreliable (model-dependent) — when it
                # returns empty, try matching graph entity names in the text.
                entity_names = await self._keyword_extract_entities(description)
                if entity_names:
                    logger.debug(
                        "Keyword fallback: %d entities from graph scan → %s",
                        len(entity_names), entity_names,
                    )

            if entity_names:
                article_ids = await self.graph_retriever.get_article_ids(
                    entity_names=entity_names,
                    max_hops=max_hops,
                )
                if article_ids:
                    logger.debug("GraphRetriever: %d article_ids from graph navigation", len(article_ids))

                # Build graph path for context
                graph_path = await self.graph_retriever.get_graph_context(
                    entity_names=entity_names,
                    max_results=20,
                    max_hops=max_hops,
                )
            else:
                degradation = "graph_only"
                logger.debug("SafetyKnowledgeRetriever: no entities extracted, skipping graph nav")
        except Exception as e:
            logger.warning("Layer 1 (graph navigation) failed, degrading: %s", e)
            degradation = "graph_only"

        # ═══ Layer 2: Chunks Hybrid Search ═══
        # 图谱导航（Layer 1）提供 graph_path 展示上下文 + 软加分权重。
        # 不再作为硬过滤条件，而是将图谱匹配的 article_id 作为加分信号
        # 注入混合检索：图谱命中的文档在 RRF 融合后获得额外加分，
        # 确保高相关文档（如 GB 30871）即使不在图谱中也能被检索到，
        # 同时在图谱中的文档获得合理的优先级提升。
        report = await self.hybrid_retriever.retrieve(
            description=description,
            categories=categories,
            target_chunks=target_chunks,
            filter_article_ids=None,
            boost_article_ids=article_ids if article_ids else None,
        )

        # 最终降级级别采用混合检索的 report 级别。
        # 注意：图导航被跳过（graph_only）不代表检索失败——混合检索（Layer 2）
        # 始终运行且可能返回高质量分块。若此处保留 graph_only，会把一次成功的
        # 检索标记为降级，导致上层（query_service 的三模式判断）误判为
        # "replace"（仅网络搜索）而丢弃可用的 KB 分块。
        degradation = report.degradation_level

        # ═══ Assemble KnowledgeContext ═══
        markdown = self._build_markdown(report.results, graph_path)

        # 回填审计上下文（无上下文时静默忽略）——审计记录可回答
        # "这次调用检索降级到第几层、引用了哪些法规"
        from app.modules.safety.ai_audit.context import fill_retrieval_info

        fill_retrieval_info(
            degradation_level=degradation,
            cited_sources=[
                {"doc_title": c.source_doc, "article_ref": c.source_article}
                for c in report.results
            ],
        )

        context = KnowledgeContext(
            chunks=report.results,
            graph_path=graph_path,
            article_ids=article_ids,
            markdown=markdown,
            degradation=degradation,
        )

        # ═══ Cache write ═══
        await set_rag_cache(
            query=description,
            context_dict=context_to_dict(context),
            categories=categories,
            target_chunks=target_chunks,
            max_hops=max_hops,
        )

        return context

    async def _keyword_extract_entities(self, text: str) -> list[str]:
        """Fallback: extract entity names by matching graph entity names against text.

        Since graph entity nodes are regulation titles (e.g. "危险化学品企业
        特殊作业安全规范"), we use reverse bigram matching: a graph entity
        matches if enough of its character bigrams appear in the query text.

        This handles cases like query="动火作业未办理作业票" matching entity
        name="危险化学品企业特殊作业安全规范" because bigrams "作业" and "安全"
        overlap with the query.
        """
        from sqlalchemy import select as sa_select

        from app.modules.safety.knowledge.graph_models import (
            KnowledgeGraphNode as GNode,
        )
        from app.modules.safety.knowledge.graph_retriever import GraphRetriever

        stmt = sa_select(GNode).where(
            GNode.node_type == "entity",
            ~GNode.is_deleted,
        )
        result = await self.session.execute(stmt)
        entity_nodes = result.scalars().all()

        if not entity_nodes:
            return []

        text_bigrams = GraphRetriever._chinese_bigrams(text)
        if not text_bigrams:
            return []

        # Score each entity by bigram overlap with the query text
        scored: list[tuple[float, str]] = []
        for node in entity_nodes:
            search_texts = [node.name]
            if node.aliases:
                search_texts.extend(a for a in node.aliases if a)

            best_score = 0.0
            for st in search_texts:
                st_bigrams = GraphRetriever._chinese_bigrams(st)
                if not st_bigrams:
                    continue
                overlap = len(text_bigrams & st_bigrams)
                # Use overlap coefficient: intersection / min(|A|, |B|)
                score = overlap / min(len(text_bigrams), len(st_bigrams))
                if score > best_score:
                    best_score = score

            if best_score >= 0.25:  # At least 25% bigram overlap
                scored.append((best_score, node.name))

        # Sort by score descending, take top 20
        scored.sort(key=lambda x: x[0], reverse=True)
        return [name for _, name in scored[:20]]

    # ── Context builders ──

    def build_injection_context(self, context: KnowledgeContext) -> str:
        """Build AI prompt injection text (for hazard ID / hazard identification).

        Returns a Markdown string suitable for injecting into the system prompt
        of AIHazardIdentifier or orchestrator scripts.
        """
        return context.markdown

    def build_chat_context(self, context: KnowledgeContext) -> str:
        """Build conversational context for info-query AI chat.

        Returns a Markdown string with numbered sources for citation.
        """
        if not context.chunks:
            return "（知识库中暂无与查询相关的法规条款）"

        parts = []
        for i, r in enumerate(context.chunks, 1):
            src = f"[{i}] {r.source_doc}"
            if r.source_article:
                src += f" — {r.source_article}"
            parts.append(f"{src}\n{r.chunk_text}")

        return "\n\n---\n\n".join(parts)

    # ── Internal ──

    @staticmethod
    def _build_markdown(
        chunks: list[RetrievalResult],
        graph_path: str | None,
    ) -> str:
        """Assemble final markdown from chunks and optional graph path."""
        parts: list[str] = []

        if graph_path:
            parts.append(graph_path)

        if chunks:
            chunk_texts = []
            for i, c in enumerate(chunks, 1):
                ref = f"《{c.source_doc}》"
                if c.source_article:
                    ref += f" {c.source_article}"
                chunk_texts.append(f"[{i}] {ref}\n{c.chunk_text}")
            parts.append("## 相关法规条款\n\n" + "\n\n---\n\n".join(chunk_texts))

        if not parts:
            return "（知识库中暂无与查询相关的法规条款）"

        return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def re_split_description(text: str) -> list[str]:
    """Split hazard description into key phrases."""
    import re
    # Split on commas, "且", "、" etc
    parts = re.split(r"[，,、;；。且与和及]+", text)
    return [p.strip() for p in parts if p.strip()]


def _extract_keywords_from_query(query: str) -> list[str]:
    """Extract keywords from a Chinese query for text matching.

    Returns a list of 2-4 character n-grams that serve as search keywords.
    """
    import re
    # Strip non-Chinese characters
    cn = re.sub(r"[^一-鿿]", "", query)
    if not cn:
        return [query]

    keywords = []
    # Full query as one keyword
    keywords.append(cn)
    # Bigrams
    for i in range(len(cn) - 1):
        kw = cn[i:i + 2]
        if kw not in keywords:
            keywords.append(kw)
    # Trigrams
    for i in range(len(cn) - 2):
        kw = cn[i:i + 3]
        if kw not in keywords:
            keywords.append(kw)

    return keywords[:30]


def _parse_embedding(raw: str | list | None) -> list[float]:
    """Parse embedding from JSON string or list."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [float(v) for v in raw]
    try:
        import json as _json
        parsed = _json.loads(raw)
        if isinstance(parsed, list):
            return [float(v) for v in parsed]
    except (ValueError, TypeError, _json.JSONDecodeError):
        pass
    return []


def _rrf_fusion(
    vec_results: list[RetrievalResult],
    text_results: list[RetrievalResult],
    k: int = 60,
) -> list[RetrievalResult]:
    """Reciprocal Rank Fusion — combines results from multiple retrieval methods."""
    scores: dict[str, dict] = {}

    for rank, r in enumerate(vec_results):
        scores[r.chunk_id] = {"result": r, "score": 1.0 / (k + rank + 1)}

    for rank, r in enumerate(text_results):
        score = 1.0 / (k + rank + 1)
        if r.chunk_id in scores:
            scores[r.chunk_id]["score"] += score
        else:
            scores[r.chunk_id] = {"result": r, "score": score}

    merged = []
    for entry in scores.values():
        r = entry["result"]
        r.score = entry["score"]
        merged.append(r)

    merged.sort(key=lambda x: x.score, reverse=True)
    return merged
