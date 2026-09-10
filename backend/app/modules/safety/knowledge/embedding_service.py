"""Embedding service — generates vector embeddings via OpenAI-compatible API.

Uses the same API endpoint as AIService but calls /embeddings instead of
/chat/completions. Supports batch embedding for efficient bulk processing.

Usage:
    from app.modules.safety.knowledge.embedding_service import EmbeddingService

    embedder = EmbeddingService(api_key="...", base_url="https://api.deepseek.com/v1")
    vec = await embedder.embed("防爆电箱堵头未封堵")
    # -> list[float] with 1024 dimensions
    vecs = await embedder.embed_batch(["text1", "text2", "text3"])
    # -> list[list[float]]
"""

from __future__ import annotations

import hashlib
import logging
import asyncio
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default embedding dimensions for common models
DEFAULT_DIMS = 2048  # deepseek-embed returns 2048-dim vectors
CACHE: dict[str, list[float]] = {}


def _ensure_scenario_enabled(scenario: str) -> None:
    """管道场景熔断守卫：停用 → raise ScenarioDisabledError。

    - 固定 key（``embedding``），**无视** ctx.scenario 父场景（backend-design §5.2）：
      关「embedding」卡 = 全面禁用向量化；
    - 被检索层既有降级链捕获（``retriever._vector_search`` 的 try/except）→
      走全文检索，无需调用点改动。
    """
    from app.modules.safety.ai_config.scenario_store import scenario_store

    if not scenario_store.is_enabled(scenario):
        from app.modules.safety.ai_config.exceptions import ScenarioDisabledError

        raise ScenarioDisabledError(scenario)


class EmbeddingService:
    """Vector embedding generator via OpenAI-compatible embeddings API.

    Falls back to a simple hash-based embedding when the API is unavailable,
    ensuring the RAG pipeline works even without embedding infrastructure.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        dims: int | None = None,
        timeout: int = 60,
    ):
        # 默认值来源统一：参数优先 → AI 配置中心（DB→env→registry 默认）→ env 兜底
        # （延迟 import resolver，避免 knowledge ↔ ai_config import 期互相引用）
        cfg: dict = {}
        if not (api_key and base_url and model):
            try:
                from app.modules.safety.ai_config.resolver import get_profile_config

                cfg = get_profile_config("embedding")
            except Exception:
                cfg = {}
            api_key = (
                api_key
                or cfg.get("api_key")
                or os.getenv("SAFETY_EMBEDDING_API_KEY", "")
            )
            base_url = (
                base_url
                or cfg.get("base_url")
                or os.getenv("SAFETY_EMBEDDING_BASE_URL", "")
            ).rstrip("/")
            model = (
                model
                or cfg.get("model")
                or os.getenv("SAFETY_EMBEDDING_MODEL", "embedding-3")
            )
        # dims 独立于三主字段解析（MINOR 修复）：三主字段全传但 dims 未传时，
        # 原逻辑跳过配置中心 → dims 落 DEFAULT_DIMS；现在先取配置中心再回落默认
        if dims is None:
            if not cfg:
                try:
                    from app.modules.safety.ai_config.resolver import get_profile_config

                    cfg = get_profile_config("embedding")
                except Exception:
                    cfg = {}
            dims = cfg.get("dims") or int(
                os.getenv("SAFETY_EMBEDDING_DIMS", str(DEFAULT_DIMS))
            )
        if dims is None:
            dims = DEFAULT_DIMS
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dims = dims
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        self._available: bool | None = None  # None = unchecked

    async def _get_client(self) -> httpx.AsyncClient | None:
        """Lazy-init HTTP client. Returns None if not configured."""
        if not self.api_key or not self.base_url:
            return None
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    async def embed(self, text: str, use_cache: bool = True) -> list[float]:
        """Generate embedding vector for a single text.

        Returns a zero-vector [0.0] * dims if the API is unavailable.
        """
        _ensure_scenario_enabled("embedding")  # 入口熔断：停用 → raise（retriever 降级链捕获）

        if not text or not text.strip():
            return [0.0] * self.dims

        text = text.strip()

        # Cache check
        cache_key = _cache_key(text)
        if use_cache and cache_key in CACHE:
            return CACHE[cache_key]

        # Try API
        vec = await self._api_embed(text)
        if vec is not None:
            if use_cache:
                CACHE[cache_key] = vec
            return vec

        # Fallback: hash-based pseudo-embedding (deterministic but NOT semantically meaningful)
        vec = self._hash_embed(text)
        if use_cache:
            CACHE[cache_key] = vec
        return vec

    async def embed_batch(
        self, texts: list[str], use_cache: bool = True
    ) -> list[list[float]]:
        """Generate embeddings for multiple texts.

        Tries batch API first, falls back to individual calls.
        """
        _ensure_scenario_enabled("embedding")  # 入口熔断（embed 自动继承；batch 语义下显式判一次）

        if not texts:
            return []

        results: list[list[float]] = []
        uncached_texts: list[tuple[int, str]] = []

        # Check cache
        for i, text in enumerate(texts):
            if not text or not text.strip():
                results.append([0.0] * self.dims)
            elif use_cache:
                cache_key = _cache_key(text.strip())
                if cache_key in CACHE:
                    results.append(CACHE[cache_key])
                else:
                    uncached_texts.append((i, text.strip()))
            else:
                uncached_texts.append((i, text.strip()))

        if not uncached_texts:
            return results

        # Try batch API
        batch_vecs = await self._api_embed_batch([t for _, t in uncached_texts])
        if batch_vecs is not None:
            for (i, text), vec in zip(uncached_texts, batch_vecs):
                results.insert(i, vec)
                if use_cache:
                    CACHE[_cache_key(text)] = vec
            return results

        # Fallback: individual calls
        for i, text in uncached_texts:
            vec = await self.embed(text, use_cache=False)
            results.insert(i, vec)
            if use_cache:
                CACHE[_cache_key(text)] = vec

        return results

    async def is_available(self) -> bool:
        """Check if the embedding API is reachable."""
        if self._available is not None:
            return self._available
        client = await self._get_client()
        if client is None:
            self._available = False
            return False
        try:
            vec = await self._api_embed("test")
            self._available = vec is not None
        except Exception:
            self._available = False
        return self._available

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        CACHE.clear()

    # ── Internal ──

    # DeepSeek/智谱 embedding endpoint paths to try (in order)
    # 2026-09-02：把真实路径 /embeddings 放前面，避免每次都先试 /v1/embeddings 命中 404 再重试一次。
    EMBEDDING_PATHS = ["/embeddings", "/v1/embeddings"]

    # 单次请求整体硬上限（秒）：高峰期端点「慢滴漏」响应可拖到分钟级，
    # httpx 读超时挡不住；到点取消 → 走下一路径 / 降级文本检索。
    _CALL_CEILING = 25

    async def _api_embed(self, text: str) -> list[float] | None:
        """Single text embedding via API. Tries multiple endpoint paths."""
        client = await self._get_client()
        if client is None:
            return None

        started = time.monotonic()
        for path in self.EMBEDDING_PATHS:
            try:
                # 2026-09-03：整体硬超时。高峰期端点偶发「慢滴漏」响应（字节间隔
                # 不超时、总时长 1-4 分钟），httpx 读超时挡不住；asyncio.wait_for
                # 强制取消后降级走下一路径/文本检索，避免逐条 RAG 拖垮整批任务。
                resp = await asyncio.wait_for(
                    client.post(path, json={
                        "model": self.model,
                        "input": text,
                    }),
                    timeout=self._CALL_CEILING,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    emb = data.get("data", [{}])[0].get("embedding")
                    if emb and isinstance(emb, list):
                        # Remember the working path
                        self.EMBEDDING_PATHS = [path]
                        await _audit_embed(
                            model=self.model,
                            input_text=text,
                            usage=data.get("usage"),
                            latency_ms=int((time.monotonic() - started) * 1000),
                            status="success",
                        )
                        return _normalize(emb)
                elif resp.status_code == 404:
                    continue  # try next path
                else:
                    logger.debug("Embedding API %s returned %s", path, resp.status_code)
            except Exception as e:
                logger.debug("Embedding API %s failed: %s", path, e)

        await _audit_embed(
            model=self.model,
            input_text=text,
            usage=None,
            latency_ms=int((time.monotonic() - started) * 1000),
            status="failed",
            error="Embedding API unavailable — all paths tried",
        )
        logger.warning("Embedding API unavailable — all paths tried")
        return None

    async def _api_embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """Batch embedding via API."""
        client = await self._get_client()
        if client is None:
            return None
        started = time.monotonic()
        try:
            # 整体硬超时（同 _api_embed，防慢滴漏响应拖垮调用方）
            resp = await asyncio.wait_for(
                client.post("/embeddings", json={
                    "model": self.model,
                    "input": texts,
                }),
                timeout=self._CALL_CEILING + 15,  # 批量文本更多，给宽 15s
            )
            if resp.status_code == 200:
                data = resp.json()
                items: list[dict[str, Any]] = data.get("data", [])
                items.sort(key=lambda x: x.get("index", 0))
                await _audit_embed(
                    model=self.model,
                    input_text=f"batch: {len(texts)} texts, {sum(len(t) for t in texts)} chars",
                    usage=data.get("usage"),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    status="success",
                )
                return [_normalize(item["embedding"]) for item in items]
            await _audit_embed(
                model=self.model,
                input_text=f"batch: {len(texts)} texts",
                usage=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="failed",
                error=f"HTTP {resp.status_code}",
            )
            logger.warning("Batch embedding API returned %s", resp.status_code)
        except Exception as e:
            await _audit_embed(
                model=self.model,
                input_text=f"batch: {len(texts)} texts",
                usage=None,
                latency_ms=int((time.monotonic() - started) * 1000),
                status="failed",
                error=f"{type(e).__name__}: {e}",
            )
            logger.warning("Batch embedding API call failed: %s", e)
        return None

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic pseudo-embedding from SHA256 hash.

        NOT semantically meaningful — used only as fallback when API is unavailable.
        Search results will be random with this fallback.
        """
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec: list[float] = []
        for i in range(0, len(h), 4):
            chunk = h[i:i + 4]
            if len(chunk) < 4:
                break
            val = int.from_bytes(chunk, "big") / (2**32)
            vec.append(val * 2 - 1)  # scale to [-1, 1]
        # Pad or truncate to dims
        if len(vec) < self.dims:
            vec.extend([0.0] * (self.dims - len(vec)))
        return vec[:self.dims]


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ═══════════════════════════════════════════════════════════════
# 共享单例（2026-09-03）
# ═══════════════════════════════════════════════════════════════
# 此前每次请求 new 一个 EmbeddingService：is_available 探测结果与
# httpx 连接池均为实例级 → 每次 RAG 检索先发一次 "test" 探测请求再发
# 真实请求（多 ~0.5s + 双倍 API 计费）。共享单例 + TTL 重建：
# - 连接池 / 探测结果 / hash 降级路径复用；
# - TTL 到期重建，让配置中心（DB）改动在 _SHARED_EMBEDDER_TTL 内生效，
#   也让 is_available 的失败缓存（API 短暂故障后置 False）周期性自愈。

_SHARED_EMBEDDER_TTL = 300.0  # 秒

_shared_embedder: EmbeddingService | None = None
_shared_embedder_at: float = 0.0


def get_shared_embedder() -> EmbeddingService:
    """进程级共享 EmbeddingService（TTL 300s 重建）。

    同步工厂（构造只读配置中心缓存，无 IO）。TTL 过期瞬间的并发重建
    竞态无害：后赋值者胜出，先建的实例存活到本轮调用结束即被回收。
    """
    global _shared_embedder, _shared_embedder_at
    if (
        _shared_embedder is not None
        and time.monotonic() - _shared_embedder_at < _SHARED_EMBEDDER_TTL
    ):
        return _shared_embedder
    _shared_embedder = EmbeddingService()
    _shared_embedder_at = time.monotonic()
    return _shared_embedder


def _normalize(vec: list[float]) -> list[float]:
    """L2-normalize a vector."""
    norm_sq = sum(v * v for v in vec)
    if norm_sq == 0:
        return vec
    norm = norm_sq ** 0.5
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors (assumes normalized)."""
    if len(a) != len(b):
        return 0.0
    return sum(ai * bi for ai, bi in zip(a, b))


# ── 审计日志（延迟 import 避免循环依赖）──


async def _audit_embed(
    *,
    model: str,
    input_text: str,
    usage: dict | None,
    latency_ms: int,
    status: str,
    error: str | None = None,
) -> None:
    """嵌入模型调用审计落表。

    优先继承当前审计上下文的 scenario（如 memory_extraction），
    无上下文时默认 "embedding"。
    """
    try:
        from app.modules.safety.ai_audit import current_audit_ctx
        from app.modules.safety.ai_audit.audited_client import write_audit_record

        ctx = current_audit_ctx()
        scenario = ctx.scenario if ctx and ctx.scenario != "unknown" else "embedding"

        await write_audit_record(
            model=model,
            scenario=scenario,
            input_text=input_text[:64 * 1024] if input_text else None,
            usage=usage,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
    except Exception:
        logger.debug("Embedding audit write skipped")
