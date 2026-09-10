"""知识库缓存 —— Chat 回答 + RAG 检索结果双层缓存。

Redis 主存储 + in-memory 自动降级（Redis 不可用时 fail-open）。
Epoch 轮转失效：法规变更时递增 epoch，旧 key 即时不可达。

Layer 0 — 精确匹配（SHA256）：
  HIT → <1ms 返回
Layer 1 — 语义匹配（embedding cosine similarity）：
  HIT → 跳过全部管线（检索 + AI 调用），~175ms（embedding API）+ <5ms
Layer 2 — RAG 检索缓存：
  HIT → 跳过三层检索管线（≥100ms）
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from uuid import UUID

from app.core.redis import cache_get, cache_set

logger = logging.getLogger(__name__)

# ── 常量 ──

CHAT_CACHE_TTL = 3600       # Chat 回答缓存 1 小时
RAG_CACHE_TTL = 3600        # RAG 检索缓存 1 小时
CHAT_CACHE_PREFIX = "chatcache:"
RAG_CACHE_PREFIX = "ragcache:"
EPOCH_KEY = "knowledge:epoch"
EPOCH_TTL = 86400 * 30      # 30 天

# 语义缓存
SEMANTIC_THRESHOLD = 0.70           # 余弦相似度阈值（测试：0 误匹配 + 92% 命中）
EMB_INDEX_PREFIX = "embidx:"        # 向量索引前缀
EMB_INDEX_TTL = CHAT_CACHE_TTL + 600  # 比 Chat 缓存稍长，避免索引先于数据过期

# ── In-memory fallback（Redis 不可用时自动降级）──


class _MemStore:
    """LRU-aware in-memory dict with TTL — Redis 不可用时的降级缓存。"""

    def __init__(self, max_entries: int = 2000):
        self._store: dict[str, tuple[float, str]] = {}  # key → (expires_at, value)
        self._max = max_entries

    async def get(self, key: str) -> str | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: str, ex: int = 3600) -> None:
        # LRU eviction: when full, drop oldest 25%
        if len(self._store) >= self._max:
            cutoff = int(self._max * 0.75)
            sorted_keys = sorted(self._store.keys(), key=lambda k: self._store[k][0])
            for old_key in sorted_keys[:self._max - cutoff]:
                del self._store[old_key]
        self._store[key] = (time.monotonic() + ex, value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def __len__(self) -> int:
        return len(self._store)


# 模块级单例
_mem = _MemStore()
_redis_available: bool | None = None  # None = 未检测，True/False = 已知状态

# 向量索引 in-memory fallback: key → {digest: [vector], ...}
_emb_idx_store: dict[str, dict[str, list[float]]] = {}

async def _get_embedder():
    """获取 EmbeddingService 共享单例（延迟 import 避免循环依赖，
    与 retriever 复用同一实例：连接池 + is_available 探测只做一次）。"""
    from app.modules.safety.knowledge.embedding_service import get_shared_embedder
    return get_shared_embedder()


def _emb_index_key(epoch: int, user_id: str | None = None) -> str:
    """向量索引 Redis key — 含 epoch 确保失效后自动隔离。"""
    if user_id:
        return f"{EMB_INDEX_PREFIX}{epoch}:{user_id}"
    return f"{EMB_INDEX_PREFIX}{epoch}"


async def _get_emb_index(epoch: int, user_id: str | None = None) -> dict[str, list[float]]:
    """读取 embedding 索引 {digest: [vector], ...}。"""
    key = _emb_index_key(epoch, user_id)
    if await _use_redis():
        try:
            raw = await cache_get(key)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _emb_idx_store.get(key, {})


async def _set_emb_index(
    epoch: int, data: dict[str, list[float]], user_id: str | None = None
) -> None:
    """写入 embedding 索引。"""
    key = _emb_index_key(epoch, user_id)
    payload = json.dumps(data, ensure_ascii=False)
    if await _use_redis():
        try:
            await cache_set(key, payload, ex=EMB_INDEX_TTL)
            return
        except Exception:
            pass
    _emb_idx_store[key] = data


async def _embed_query(query: str) -> list[float] | None:
    """对查询文本做 embedding。失败返回 None → 语义缓存降级。"""
    try:
        embedder = await _get_embedder()
        return await embedder.embed(query)
    except Exception:
        logger.debug("Embedding unavailable for semantic cache", exc_info=True)
        return None


async def _semantic_lookup(
    query_embedding: list[float],
    epoch: int,
    user_id: str | None = None,
) -> tuple[str | None, float]:
    """在 embedding 索引中查找最佳语义匹配。

    遍历索引中所有已缓存的查询向量，计算余弦相似度，
    返回第一个 ≥ SEMANTIC_THRESHOLD 的 (cache_key, score)。
    无匹配返回 (None, 0.0)。

    复杂度：O(n * d)，n=缓存条目数，d=向量维度(2048)。
    以 200 条目计，~0.4ms（纯 Python 内积运算）。
    """
    from app.modules.safety.knowledge.embedding_service import cosine_similarity

    index = await _get_emb_index(epoch, user_id)
    if not index:
        return None, 0.0

    best_key: str | None = None
    best_score = 0.0

    for digest, cached_emb in index.items():
        score = cosine_similarity(query_embedding, cached_emb)
        if score > best_score:
            best_score = score
            best_key = digest
            if score >= 0.98:  # 近乎完全相同，提前终止
                break

    if best_key is not None and best_score >= SEMANTIC_THRESHOLD:
        return best_key, best_score

    return None, 0.0


async def _add_to_emb_index(
    digest: str,
    query_embedding: list[float],
    epoch: int,
    user_id: str | None = None,
) -> None:
    """将一条查询向量加入索引。同时惰性清理已过期的条目。"""
    try:
        index = await _get_emb_index(epoch, user_id)
        # 惰性清理：检查哪些 digest 对应的缓存已过期
        clean_keys = []
        for existing_digest in list(index.keys()):
            cache_key = f"{CHAT_CACHE_PREFIX}{existing_digest}"
            raw = await _kv_get(cache_key)
            if raw is None:
                clean_keys.append(existing_digest)
        for k in clean_keys:
            del index[k]

        index[digest] = query_embedding
        await _set_emb_index(epoch, index, user_id)
    except Exception:
        logger.debug("Failed to update embedding index", exc_info=True)


async def _use_redis() -> bool:
    """检测 Redis 是否可用（只检测一次，结果缓存）。"""
    global _redis_available
    if _redis_available is not None:
        return _redis_available
    try:
        await cache_set("__health__", "1", ex=5)
        _redis_available = True
    except Exception:
        logger.info("Redis 不可用，缓存降级为 in-memory（进程内）")
        _redis_available = False
    return _redis_available


# ── 统一的 KV 读写 ──


async def _kv_get(key: str) -> str | None:
    if await _use_redis():
        try:
            return await cache_get(key)
        except Exception:
            pass
    return await _mem.get(key)


async def _kv_set(key: str, value: str, ex: int = 3600) -> None:
    if await _use_redis():
        try:
            await cache_set(key, value, ex=ex)
            return
        except Exception:
            pass
    await _mem.set(key, value, ex=ex)


# ── Epoch 轮转失效 ──


async def _get_epoch() -> int:
    raw = await _kv_get(EPOCH_KEY)
    if raw is None:
        await _kv_set(EPOCH_KEY, "0", ex=EPOCH_TTL)
        return 0
    return int(raw)


async def invalidate_knowledge_cache() -> None:
    """递增 epoch → 所有旧 Chat/RAG 缓存 key 即时失效。"""
    try:
        raw = await _kv_get(EPOCH_KEY)
        epoch = int(raw) + 1 if raw else 1
        await _kv_set(EPOCH_KEY, str(epoch), ex=EPOCH_TTL)
        logger.info("知识库缓存已失效: epoch → %d", epoch)
    except Exception:
        logger.exception("知识库缓存失效失败（不影响业务）")


# ── 隐私检测 ──

# 查询中包含以下任一模式 → 判定为涉私查询 → key 含 user_id 隔离
_PRIVACY_INDICATORS = [
    "我的", "我部门", "我公司", "我们部门", "本单位", "本人", "个人",
    "我负责", "我管辖", "我名下", "归我",
]


def _is_privacy_query(query: str) -> bool:
    """检测查询是否涉及用户私有数据（我的隐患/我部门的检查等）。"""
    for indicator in _PRIVACY_INDICATORS:
        if indicator in query:
            return True
    return False


# ── Chat 回答缓存 ──


def _chat_cache_key(
    query: str,
    history: list[dict] | None,
    epoch: int,
    user_id: str | None = None,
) -> str:
    hist_str = ""
    if history:
        compact = [{"r": m.get("role", ""), "c": m.get("content", "")[:200]} for m in history]
        hist_str = "|" + json.dumps(compact, ensure_ascii=False, sort_keys=True)
    payload = f"{query}{hist_str}|{epoch}"
    # 涉私查询：key 拼接 user_id → 不同用户隔离；公共查询：不拼接 → 跨用户共享
    if user_id:
        payload += f"|{user_id}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{CHAT_CACHE_PREFIX}{digest}"


async def get_chat_cache(
    query: str,
    history: list[dict] | None = None,
    user_id: str | None = None,
) -> dict | None:
    """读取 Chat 缓存（三层查找：精确 → 语义 → 私有回退）。

    - L0 精确匹配（SHA256）：逐字相同 → <1ms 返回
    - L1 语义匹配（embedding cosine）：含义相同 → ~175ms + 遍历
    - 公共查询（无隐私指示词）：先公共池 L0→L1，miss 回退私有池
    - 涉私查询（含"我的"/"我部门"等）：仅查私有池（含 user_id）
    """
    try:
        epoch = await _get_epoch()

        if _is_privacy_query(query):
            # ── 涉私查询：只查私有池 ──
            if user_id:
                # L0: 精确
                key = _chat_cache_key(query, history, epoch, user_id)
                raw = await _kv_get(key)
                if raw:
                    logger.debug("Chat cache HIT (private exact): %s", key)
                    return json.loads(raw)

                # L1: 语义
                if history is None:  # 仅对无历史的查询做语义匹配（含历史 → 上下文不同）
                    q_emb = await _embed_query(query)
                    if q_emb is not None:
                        match_digest, score = await _semantic_lookup(q_emb, epoch, user_id)
                        if match_digest is not None:
                            match_key = f"{CHAT_CACHE_PREFIX}{match_digest}"
                            raw = await _kv_get(match_key)
                            if raw:
                                logger.debug(
                                    "Chat cache HIT (private semantic, %.3f): %s → %s",
                                    score, query[:40], match_key,
                                )
                                return json.loads(raw)
            return None

        # ── 公共查询：先公共池 → L0 → L1 → 私有回退 ──
        # L0: 精确
        public_key = _chat_cache_key(query, history, epoch)
        raw = await _kv_get(public_key)
        if raw:
            logger.debug("Chat cache HIT (public exact): %s", public_key)
            return json.loads(raw)

        # L1: 语义（公共池）
        if history is None:
            q_emb = await _embed_query(query)
            if q_emb is not None:
                match_digest, score = await _semantic_lookup(q_emb, epoch)
                if match_digest is not None:
                    match_key = f"{CHAT_CACHE_PREFIX}{match_digest}"
                    raw = await _kv_get(match_key)
                    if raw:
                        logger.debug(
                            "Chat cache HIT (public semantic, %.3f): %s → %s",
                            score, query[:40], match_key,
                        )
                        return json.loads(raw)

        # 私有回退：L0 精确
        if user_id:
            private_key = _chat_cache_key(query, history, epoch, user_id)
            raw = await _kv_get(private_key)
            if raw:
                logger.debug("Chat cache HIT (private fallback): %s", private_key)
                return json.loads(raw)
    except Exception:
        logger.debug("Chat cache read failed, skipping", exc_info=True)
    return None


async def set_chat_cache(
    query: str,
    answer: str,
    sources: list[dict],
    history: list[dict] | None = None,
    user_id: str | None = None,
) -> None:
    """写入 Chat 缓存（智能分类存储 + embedding 索引）。

    - 涉私查询 → 仅写私有池（key 含 user_id），不污染公共池
    - 公共查询 → 写公共池，跨用户共享
    - 同时将查询向量写入 embedding 索引供后续语义匹配
    """
    try:
        epoch = await _get_epoch()

        if user_id and _is_privacy_query(query):
            # 涉私：写入私有池
            key = _chat_cache_key(query, history, epoch, user_id)
            logger.debug("Chat cache SET (private): %s", key)
        else:
            # 公共：写入公共池
            key = _chat_cache_key(query, history, epoch)
            logger.debug("Chat cache SET (public): %s", key)

        payload = json.dumps({"answer": answer, "sources": sources}, ensure_ascii=False)
        await _kv_set(key, payload, ex=CHAT_CACHE_TTL)

        # ── 写入 embedding 索引（无历史时）──
        if history is None:
            digest = key[len(CHAT_CACHE_PREFIX):]  # 去掉前缀得 digest
            q_emb = await _embed_query(query)
            if q_emb is not None:
                idx_user = user_id if (user_id and _is_privacy_query(query)) else None
                await _add_to_emb_index(digest, q_emb, epoch, idx_user)
    except Exception:
        logger.debug("Chat cache write failed, skipping", exc_info=True)


# ── RAG 检索缓存 ──


def _rag_cache_key(
    query: str, categories: list[str] | None,
    target_chunks: int, max_hops: int, epoch: int,
) -> str:
    cats = ",".join(sorted(categories)) if categories else "_all"
    payload = f"{query}|{cats}|{target_chunks}|{max_hops}|{epoch}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{RAG_CACHE_PREFIX}{digest}"


async def get_rag_cache(
    query: str,
    categories: list[str] | None = None,
    target_chunks: int = 8,
    max_hops: int = 2,
) -> dict | None:
    try:
        epoch = await _get_epoch()
        key = _rag_cache_key(query, categories, target_chunks, max_hops, epoch)
        raw = await _kv_get(key)
        if raw:
            logger.debug("RAG cache HIT: %s", key)
            return json.loads(raw)
    except Exception:
        logger.debug("RAG cache read failed, skipping", exc_info=True)
    return None


async def set_rag_cache(
    query: str,
    context_dict: dict,
    categories: list[str] | None = None,
    target_chunks: int = 8,
    max_hops: int = 2,
) -> None:
    try:
        epoch = await _get_epoch()
        key = _rag_cache_key(query, categories, target_chunks, max_hops, epoch)
        await _kv_set(key, json.dumps(context_dict, ensure_ascii=False), ex=RAG_CACHE_TTL)
        logger.debug("RAG cache SET: %s", key)
    except Exception:
        logger.debug("RAG cache write failed, skipping", exc_info=True)


# ── KnowledgeContext 序列化 ──


def context_to_dict(context) -> dict:
    chunks_json = []
    for c in context.chunks:
        chunks_json.append({
            "chunk_id": c.chunk_id, "chunk_text": c.chunk_text,
            "source_doc": c.source_doc, "source_article": c.source_article,
            "doc_category": c.doc_category, "priority": c.priority,
            "score": c.score, "vector_score": c.vector_score,
            "text_score": c.text_score, "retrieval_path": c.retrieval_path,
            "article_id": c.article_id,
        })
    return {
        "chunks": chunks_json,
        "graph_path": context.graph_path,
        "article_ids": [str(aid) for aid in (context.article_ids or [])],
        "markdown": context.markdown,
        "degradation": context.degradation,
    }


def context_from_dict(data: dict) -> object:
    from app.modules.safety.knowledge.retriever import KnowledgeContext, RetrievalResult

    chunks = [RetrievalResult(
        chunk_id=c["chunk_id"], chunk_text=c["chunk_text"],
        source_doc=c["source_doc"], source_article=c["source_article"],
        doc_category=c["doc_category"], priority=c["priority"],
        score=c["score"], vector_score=c["vector_score"],
        text_score=c["text_score"], retrieval_path=c["retrieval_path"],
        article_id=c["article_id"],
    ) for c in data.get("chunks", [])]

    article_ids = [UUID(aid) for aid in data.get("article_ids", [])]

    return KnowledgeContext(
        chunks=chunks, graph_path=data.get("graph_path"),
        article_ids=article_ids, markdown=data.get("markdown", ""),
        degradation=data.get("degradation", "full"),
    )
