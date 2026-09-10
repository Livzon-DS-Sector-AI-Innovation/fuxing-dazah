"""Cross-encoder reranker — dedicated API-first + LLM fallback.

After RRF fusion produces a coarse-ranked list of ~20 candidates,
this reranker scores each candidate against the query and re-sorts.

Two backends (API-first, graceful degradation):
  ① ZhipuAI rerank API (rerank-pro) — fast dedicated model, ~0.8 ¥/M tokens
  ② DeepSeek LLM prompt scoring — fallback when API unavailable

Usage:
    from app.modules.safety.knowledge.reranker import Reranker

    reranker = Reranker()  # auto-reads env vars for API
    reranked = await reranker.rerank(
        query="防爆堵头未封堵",
        candidates=top_20_chunks,
        top_k=8,
    )
    # -> re-ordered list with updated scores
"""

from __future__ import annotations

import json as _json
import logging
import os as _os
import time as _time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from app.modules.safety.knowledge.retriever import RetrievalResult
    from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)

# Max candidates per LLM call (stay under token limits)
BATCH_SIZE = 8
# Max chars per candidate chunk (truncate longer texts)
MAX_CHUNK_CHARS = 400

# ── Rerank API defaults ──
_DEFAULT_RERANK_MODEL = "rerank-pro"
_DEFAULT_RERANK_TIMEOUT = 30  # seconds


def _ensure_env_loaded() -> None:
    """Load .env.development if not already loaded.

    SAFETY_EMBEDDING_API_KEY / SAFETY_EMBEDDING_BASE_URL may not be in
    os.environ when the knowledge module is imported before other modules
    that call load_dotenv (e.g. business_agent, feishu client).
    """
    import os as _os2
    if _os2.getenv("SAFETY_EMBEDDING_API_KEY"):
        return  # already loaded
    _env_path = _os2.path.join(
        _os2.path.dirname(__file__), "..", "..", "..", "..", ".env.development",
    )
    _env_path = _os2.path.normpath(_env_path)
    if _os2.path.exists(_env_path):
        try:
            from dotenv import load_dotenv
            load_dotenv(_env_path, override=True)
            logger.debug("Loaded env from %s", _env_path)
        except Exception:
            pass  # dotenv not installed or IO error — env vars must be set by caller


RERANK_PROMPT = """你是一个安全生产法规检索专家。请评估以下法规条款与查询的相关性。

## 查询
{query}

## 待评估的法规条款
{candidates}

## 评分标准
- 8-10: 条款内容直接针对查询中的安全隐患，提供了明确的判定标准或整改要求
- 5-7: 条款内容与查询相关，但属于一般性规定，不够具体
- 1-4: 条款内容与查询有微弱关联，但不直接适用
- 0: 完全无关

## 输出格式
请严格以 JSON 对象格式返回，结构为：
{{"scores": [{{"index": 0, "score": 8, "reasoning": "条款明确规定了防爆电缆引入装置的密封要求"}}, ...]}}

只输出 JSON 对象，不要包含其他内容。"""


# ═══════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════


@dataclass
class RerankScore:
    """Single reranker score."""
    index: int
    score: float  # 0-1 for API, 0-10 for LLM (normalized downstream)
    reasoning: str = ""


# ═══════════════════════════════════════════════════════════════
# Rerank API Client (ZhipuAI)
# ═══════════════════════════════════════════════════════════════


class RerankAPIClient:
    """Thin HTTP client for ZhipuAI rerank API (rerank-pro).

    Calls POST /rerank on the ZhipuAI platform (open.bigmodel.cn).
    Uses the same API key and base URL as the embedding service.

    Usage::

        client = RerankAPIClient()  # reads env vars
        scores = await client.rerank(
            query="防爆堵头未封堵",
            documents=["doc1", "doc2", ...],
            top_n=8,
        )
        # -> [RerankScore(index=0, score=0.88), ...]
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout: int = _DEFAULT_RERANK_TIMEOUT,
    ):
        # Ensure .env.development is loaded (may not be loaded if this module
        # is imported before other modules that call load_dotenv).
        _ensure_env_loaded()
        # 默认值来源统一：参数优先 → AI 配置中心（DB→env→registry 默认）→ env 兜底。
        # registry env_map 已把 rerank api_key/base_url 指向 SAFETY_EMBEDDING_*
        # （兼容存量 RAG 链路，spec 决策），get_profile_config 已合并，直接消费。
        if not (api_key and base_url and model):
            try:
                from app.modules.safety.ai_config.resolver import get_profile_config

                cfg = get_profile_config("rerank")
            except Exception:
                cfg = {}
            api_key = (
                api_key
                or cfg.get("api_key")
                or _os.getenv("SAFETY_EMBEDDING_API_KEY", "")
            )
            base_url = (
                base_url
                or cfg.get("base_url")
                or _os.getenv("SAFETY_EMBEDDING_BASE_URL", "")
            ).rstrip("/")
            model = (
                model
                or cfg.get("model")
                or _os.getenv("SAFETY_RERANK_MODEL", _DEFAULT_RERANK_MODEL)
            )
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    @property
    def available(self) -> bool:
        """True if the API is configured (has key + base URL)."""
        return bool(self.api_key and self.base_url)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int = 8,
    ) -> list[RerankScore]:
        """Call the ZhipuAI rerank API and return scored results.

        Returns empty list on any failure (caller falls back to LLM).
        """
        if not self.available:
            return []

        client = await self._get_client()
        if client is None:
            return []

        # Truncate documents to avoid token overflow
        truncated = [d[:MAX_CHUNK_CHARS * 2] for d in documents]

        started = _time.monotonic()
        try:
            resp = await client.post(
                f"{self.base_url}/rerank",
                json={
                    "model": self.model,
                    "query": query,
                    "documents": truncated,
                    "top_n": min(top_n, len(truncated)),
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "Rerank API returned %d: %s", resp.status_code, resp.text[:300]
                )
                await _audit_rerank(
                    model=self.model,
                    input_text=f"query={query[:200]}, documents={len(documents)}",
                    usage=None,
                    latency_ms=int((_time.monotonic() - started) * 1000),
                    status="failed",
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                )
                return []

            data = resp.json()
            results: list[dict] = data.get("results", [])
            if not results:
                return []

            usage = data.get("usage")
            if usage:
                logger.info(
                    "Rerank API (%s): %d tokens (prompt=%d completion=%d)",
                    self.model,
                    usage.get("total_tokens", 0),
                    usage.get("prompt_tokens", 0),
                    usage.get("completion_tokens", 0),
                )

            # Audit logging
            await _audit_rerank(
                model=self.model,
                input_text=f"query={query[:200]}, documents={len(documents)}, top_n={top_n}",
                usage=usage,
                latency_ms=int((_time.monotonic() - started) * 1000),
                status="success",
            )

            # API returns results ordered by relevance_score DESC (not by input index).
            # We match by the returned document text to find the original index.
            # Build lookup: exact match → stripped match (API may normalize whitespace)
            doc_index_map: dict[str, int] = {}
            for i, d in enumerate(truncated):
                doc_index_map[d] = i
                doc_index_map[d.strip()] = i  # API may strip whitespace

            scores: list[RerankScore] = []
            for item in results:
                returned_doc = item.get("document", "")
                idx = item.get("index")
                if idx is None:
                    # Try exact match first, then stripped match
                    idx = doc_index_map.get(returned_doc, -1)
                    if idx < 0:
                        idx = doc_index_map.get(returned_doc.strip(), -1)
                if isinstance(idx, int) and 0 <= idx < len(documents):
                    scores.append(
                        RerankScore(
                            index=idx,
                            score=float(item.get("relevance_score", 0.0)),
                        )
                    )
                else:
                    logger.warning(
                        "Rerank API result unmatched — doc=%r (idx=%s, available_keys=%d)",
                        returned_doc[:100],
                        idx,
                        len(doc_index_map),
                    )
            return scores

        except Exception as e:
            logger.warning("Rerank API call failed: %s", e)
            await _audit_rerank(
                model=self.model,
                input_text=f"query={query[:200]}, documents={len(documents)}",
                usage=None,
                latency_ms=int((_time.monotonic() - started) * 1000),
                status="failed",
                error=f"{type(e).__name__}: {e}",
            )
            return []

    async def _get_client(self) -> httpx.AsyncClient | None:
        """Lazy-init HTTP client. No base_url — always pass full URL to avoid
        httpx URL resolution edge cases when base_url contains a path prefix."""
        if not self.api_key or not self.base_url:
            return None
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ═══════════════════════════════════════════════════════════════
# Reranker
# ═══════════════════════════════════════════════════════════════


def _ensure_scenario_enabled(scenario: str) -> None:
    """管道场景熔断守卫：停用 → raise ScenarioDisabledError。

    - 固定 key（``rerank``），无视 ctx.scenario 父场景（backend-design §5.3）；
    - 在 ``Reranker.rerank`` 最顶（``if not candidates`` 之前）抛 → retriever 既有
      ``try/except``（retriever.py:445）捕获，保留原 RRF 排序，**不**触发 LLM 重排。
    """
    from app.modules.safety.ai_config.scenario_store import scenario_store

    if not scenario_store.is_enabled(scenario):
        from app.modules.safety.ai_config.exceptions import ScenarioDisabledError

        raise ScenarioDisabledError(scenario)


class Reranker:
    """Cross-encoder reranker — API-first (rerank-pro), LLM fallback.

    Reranks the top candidates from hybrid search:
      ① Primary: ZhipuAI rerank API (rerank-pro) — fast, cheap, dedicated model
      ② Fallback: DeepSeek LLM prompt scoring — when API is unavailable

    If both fail, the original RRF ranking is used unchanged.
    """

    def __init__(
        self,
        ai_service: AIService | None = None,
        *,
        rerank_api: RerankAPIClient | None = None,
    ):
        self._ai = ai_service
        self._api = rerank_api or RerankAPIClient()
        logger.info(
            "Reranker init: api_backend=%s llm_backend=%s",
            self._api.available,
            self._ai is not None,
        )

    @property
    def available(self) -> bool:
        """True if at least one rerank backend is available."""
        return self._api.available or self._ai is not None

    async def rerank(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int = 8,
    ) -> list[RetrievalResult]:
        """Re-rank candidates using rerank API → LLM fallback.

        Args:
            query: Original user query or hazard description
            candidates: Top candidates from RRF fusion (usually 15-25)
            top_k: Number of results to return after reranking

        Returns:
            Re-ordered candidates with updated scores
        """
        _ensure_scenario_enabled("rerank")  # 入口熔断：停用 → raise（retriever 降级链捕获）

        if not candidates:
            return []

        if not self.available:
            return candidates[:top_k]

        # Limit candidates for reranking
        max_candidates = min(len(candidates), BATCH_SIZE * 2)
        candidates = candidates[:max_candidates]

        # ── Primary: Rerank API (fast, cheap) ──
        if self._api.available:
            try:
                documents = [(c.chunk_text or "")[:MAX_CHUNK_CHARS] for c in candidates]
                api_scores = await self._api.rerank(
                    query=query,
                    documents=documents,
                    top_n=top_k,
                )
                if api_scores:
                    logger.info(
                        "Rerank via API (%s): %d candidates → %d scores, query=%r",
                        self._api.model,
                        len(candidates),
                        len(api_scores),
                        query[:80],
                    )
                    return self._merge_api_scores(candidates, api_scores, top_k)
                else:
                    logger.info("Rerank API returned empty scores, falling back to LLM")
            except Exception as e:
                logger.warning("Rerank API failed, falling back to LLM: %s", e)

        # ── Fallback: LLM prompt scoring ──
        if self._ai is not None:
            logger.info("Rerank via LLM: %d candidates", len(candidates))
            return await self._rerank_via_llm(query, candidates, top_k)

        return candidates[:top_k]

    # ── API score merging ──

    @staticmethod
    def _merge_api_scores(
        candidates: list[RetrievalResult],
        api_scores: list[RerankScore],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Merge API relevance scores into candidates and re-sort.

        Blends 60% API score + 40% original RRF score for stability.
        """
        score_map: dict[int, float] = {}
        for s in api_scores:
            if 0 <= s.index < len(candidates):
                score_map[s.index] = s.score

        for i, c in enumerate(candidates):
            api_score = score_map.get(i, 0.0)
            # Blend: 60% API score + 40% original RRF score
            c.score = 0.6 * api_score + 0.4 * c.score

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_k]

    # ── LLM fallback ──

    async def _rerank_via_llm(
        self,
        query: str,
        candidates: list[RetrievalResult],
        top_k: int,
    ) -> list[RetrievalResult]:
        """Score candidates by LLM prompt (original behavior, now fallback)."""
        try:
            scores = await self._batch_score(query, candidates)
            # 按 LLM 返回的 index 写回（prompt 要求返回 index；LLM 可能乱序/漏报）。
            # 缺失 index（越界）时按 scores 列表位置兜底，并告警。
            score_map: dict[int, float] = {}
            for pos, s in enumerate(scores):
                idx = s.index if 0 <= s.index < len(candidates) else pos
                if idx >= len(candidates):
                    logger.warning(
                        "LLM reranker score dropped — index=%s pos=%d (candidates=%d)",
                        s.index, pos, len(candidates),
                    )
                    continue
                if idx != s.index:
                    logger.warning(
                        "LLM reranker score missing invalid index=%s, "
                        "falling back to position %d", s.index, pos,
                    )
                score_map[idx] = s.score

            # Merge scores back into candidates
            for i, c in enumerate(candidates):
                if i in score_map:
                    # Blend: 60% LLM score + 40% original RRF score
                    c.score = 0.6 * (score_map[i] / 10.0) + 0.4 * c.score
            candidates.sort(key=lambda c: c.score, reverse=True)
        except Exception as e:
            logger.warning("LLM reranker failed, using original ranking: %s", e)

        return candidates[:top_k]

    async def _batch_score(
        self, query: str, candidates: list[RetrievalResult],
    ) -> list[RerankScore]:
        """Score candidates in batches to stay under token limits."""
        all_scores: list[RerankScore] = []

        for batch_start in range(0, len(candidates), BATCH_SIZE):
            batch = candidates[batch_start:batch_start + BATCH_SIZE]

            # Build candidate descriptions
            candidate_lines = []
            for i, c in enumerate(batch):
                idx = batch_start + i
                text = (c.chunk_text or "")[:MAX_CHUNK_CHARS]
                candidate_lines.append(
                    f"[{idx}] 《{c.source_doc}》{c.source_article or ''}\n{text}"
                )

            prompt = RERANK_PROMPT.format(
                query=query,
                candidates="\n\n---\n\n".join(candidate_lines),
            )

            assert self._ai is not None
            raw = await self._ai.chat(
                messages=[{"role": "user", "content": prompt}],
                response_format="json_object",
                temperature=0.1,
                max_tokens=2048,
            )

            scores = self._parse_scores(raw)
            all_scores.extend(scores)

        return all_scores

    @staticmethod
    def _parse_scores(raw: str) -> list[RerankScore]:
        """Parse LLM JSON output into RerankScore list."""
        if not raw:
            return []

        raw = raw.strip()
        # Strip markdown code fences
        if raw.startswith("```"):
            lines = raw.split("\n")
            if len(lines) >= 3:
                lines = lines[1:-1]
            raw = "\n".join(lines)

        try:
            parsed = _json.loads(raw)
        except _json.JSONDecodeError:
            logger.debug("Reranker JSON parse failed: %s", raw[:200])
            return []

        if not isinstance(parsed, list):
            # Maybe wrapped in {"scores": [...]}
            if isinstance(parsed, dict):
                for key in ("scores", "results", "data"):
                    if key in parsed and isinstance(parsed[key], list):
                        parsed = parsed[key]
                        break
                else:
                    return []

        scores: list[RerankScore] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("index", -1))
                s = float(item.get("score", 0))
                reasoning = str(item.get("reasoning", ""))
                if idx >= 0 and 0 <= s <= 10:
                    scores.append(RerankScore(index=idx, score=s, reasoning=reasoning))
            except (TypeError, ValueError):
                continue

        return scores


# ── 审计日志（延迟 import 避免循环依赖）──


async def _audit_rerank(
    *,
    model: str,
    input_text: str,
    usage: dict | None,
    latency_ms: int,
    status: str,
    error: str | None = None,
) -> None:
    """重排模型调用审计落表。"""
    try:
        from app.modules.safety.ai_audit.audited_client import write_audit_record

        await write_audit_record(
            model=model,
            scenario="rerank",
            input_text=input_text[:64 * 1024] if input_text else None,
            usage=usage,
            latency_ms=latency_ms,
            status=status,
            error=error,
        )
    except Exception:
        logger.debug("Rerank audit write skipped")
