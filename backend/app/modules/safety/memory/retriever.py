"""记忆检索器 —— 混合检索用户记忆（向量语义 + 关键词）。

DEPRECATED（S5 ``core/memory.retrieve_with_decay`` 接管衰减检索排序）：本模块保留 ``MemoryStore``
CRUD + numpy 检索基础设施供兼容期复用；冲突合并与衰减排序由 core 层编排。

复用现有基础设施（EmbeddingService + cosine_similarity），
与 cache.py 的语义匹配架构一致。

检索策略：
  1. 对当前查询做 embedding
  2. 在用户记忆池中做向量相似度检索（线性扫描，O(n*d)）
  3. 关键词匹配增强（Chinese bigram overlap）
  4. 按 importance × similarity × recency 融合排序
  5. 返回 top_k 条记忆
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.memory.store import MemoryStore

logger = logging.getLogger(__name__)

# ── 检索配置 ──
_DEFAULT_TOP_K = 5
_MIN_SIMILARITY_THRESHOLD = 0.60  # 低于此相似度的记忆不返回


class MemoryRetriever:
    """混合检索用户记忆。

    用法::

        retriever = MemoryRetriever(db)
        memories = await retriever.retrieve(user_id, query, top_k=5)
        # → list[dict]（含 content, similarity, memory_type 等）
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._store = MemoryStore(db)
        self._embedder: object | None = None

    async def _get_embedder(self):
        """获取 EmbeddingService 单例（懒加载）。"""
        if self._embedder is None:
            from app.modules.safety.knowledge.embedding_service import EmbeddingService
            self._embedder = EmbeddingService()
        return self._embedder

    # ── 公共接口 ──

    async def retrieve(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = _DEFAULT_TOP_K,
        memory_types: list[str] | None = None,
    ) -> list[dict]:
        """检索与当前查询最相关的用户记忆。

        Args:
            user_id: 用户标识
            query: 当前用户查询文本
            top_k: 返回条数上限
            memory_types: 限定记忆类型（None=全部）

        Returns:
            [{"content": str, "memory_type": str, "similarity": float, ...}, ...]
            按 relevance 降序排列。
        """
        try:
            # 1. 对查询做 embedding
            embedder = await self._get_embedder()
            try:
                query_emb = await embedder.embed(query)
            except Exception:
                logger.debug("Embedding unavailable for memory retrieval", exc_info=True)
                return []

            # 2. 获取用户的记忆向量
            from app.modules.safety.knowledge.embedding_service import cosine_similarity

            all_triples: list[tuple[UUID, str, list[float]]] = []
            if memory_types:
                for mt in memory_types:
                    triples = await self._store.get_with_embeddings(user_id, memory_type=mt)
                    all_triples.extend(triples)
            else:
                all_triples = await self._store.get_with_embeddings(user_id)

            if not all_triples:
                return []

            # 3. 向量相似度 + 关键词增强 → 融合排序
            scored: list[dict] = []

            for mem_id, content, cached_emb in all_triples:
                # 向量相似度
                vec_sim = cosine_similarity(query_emb, cached_emb)

                # 关键词 overlap（Chinese bigram）
                kw_sim = _keyword_similarity(query, content)

                # 融合分数（向量 70% + 关键词 30%）
                hybrid_score = vec_sim * 0.7 + kw_sim * 0.3

                if hybrid_score < _MIN_SIMILARITY_THRESHOLD:
                    continue

                scored.append({
                    "id": str(mem_id),
                    "content": content,
                    "similarity": round(hybrid_score, 4),
                    "vector_score": round(vec_sim, 4),
                    "keyword_score": round(kw_sim, 4),
                })

            # 按融合分数降序
            scored.sort(key=lambda x: x["similarity"], reverse=True)

            # 取 top_k
            top = scored[:top_k]

            # 4. 记录访问
            for item in top:
                try:
                    await self._store.record_access(UUID(item["id"]))
                except Exception:
                    pass

            if top:
                logger.debug(
                    "Memory retrieval: %d results for user=%s query=%s",
                    len(top), user_id, query[:40],
                )

            return top

        except Exception:
            logger.exception("Memory retrieval failed")
            return []

    # ── 便捷方法：仅获取用户上下文文本 ──

    async def get_context_text(
        self,
        user_id: str,
        query: str,
        *,
        top_k: int = _DEFAULT_TOP_K,
    ) -> str:
        """检索并格式化为可注入 prompt 的上下文文本。

        Returns:
            上下文文本，形如：
            "- 该用户默认关注部门：原料药生产部\n- 上次查询：防爆电气隐患"
            若无相关记忆返回空字符串。
        """
        memories = await self.retrieve(user_id, query, top_k=top_k)
        if not memories:
            return ""

        lines = ["相关记忆："]
        for m in memories:
            lines.append(f"  - {m['content']}")
        return "\n".join(lines)


# ── 关键词相似度（Chinese bigram overlap）─────────────────────


def _keyword_similarity(query: str, content: str) -> float:
    """计算两个中文文本的 bigram overlap 分数 (0-1)。"""
    try:
        q_bigrams = set(_chinese_bigrams(query))
        c_bigrams = set(_chinese_bigrams(content))
        if not q_bigrams or not c_bigrams:
            return 0.0
        intersection = q_bigrams & c_bigrams
        return len(intersection) / min(len(q_bigrams), len(c_bigrams))
    except Exception:
        return 0.0


def _chinese_bigrams(text: str) -> list[str]:
    """提取中文文本的字符 bigram（连续两个字符）。"""
    chars = [ch for ch in text if '一' <= ch <= '鿿' or '㐀' <= ch <= '䶿']
    if len(chars) < 2:
        return chars
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
