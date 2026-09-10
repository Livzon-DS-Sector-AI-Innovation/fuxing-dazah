"""记忆编排层（S5，用户点名重点）。

自旧 ``memory/`` 目录（retriever / store / extractor / injector）重构：把「提取、冲突合并、
衰减检索、注入」编排到``core/memory.py``，底层复用旧 ``memory/`` 的 CRUD / LLM 提取基础设施，
但数据形态改为**事件化**（从 ``agent_session_events`` 取对话事件做提取，失败可重放）。

核心能力：
- ``extract_from_events``：从 session 事件流取 ``user_message`` + ``assistant_message`` 事件，
  复用 ``MemoryExtractor`` 的 AI 提取逻辑（不改 LLM prompt）；失败可重放（事件持久化）。
- ``merge_on_conflict``：新记忆入库前与同 user 同 type 的现有记忆做向量相似度比对（阈值 0.85，
  numpy cosine，与 retriever 一致）。超阈值 → 软删旧记忆 + 旧记忆 ``superseded_by`` 指向新记忆 +
  新建记忆；不超阈值 → 直接新建。返回新记忆 id。
- ``retrieve_with_decay``：复用 ``MemoryRetriever`` 的 numpy 检索 + 关键词，排序分
  ``similarity × importance × confidence × recency_decay``（半衰期 30 天），命中后更新
  ``last_accessed_at`` + ``access_count``。
- ``inject_to_prompt``：渲染为 ``prompt.py MemoriesSection`` 需要的 ``list[str]`` 格式，
  内容带 ``memory_type`` + 时间（如 ``[偏好] 我负责生产部 (2026-08-01)``）。

设计遵循 CLAUDE.md：只改 `app/modules/safety/`、不引入 pgvector（JSON TEXT + numpy）、
SQLAlchemy 2.0 typed ORM、async（INSERT 后 flush 返回即可，UPDATE 后 select re-fetch）。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.modules.safety.memory.models import AgentMemory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.safety.business_agent.schemas import SafetyDeps

logger = logging.getLogger(__name__)

# ── 衰减配置 ──
_HALF_LIFE_DAYS = 30.0  # 半衰期（天）：score 每 30 天折半
_DEDUP_SIMILARITY_THRESHOLD = 0.85  # 冲突合并阈值（沿用旧 store 常量）
_MEMORY_TYPE_LABELS: dict[str, str] = {
    "fact": "事实",
    "preference": "偏好",
    "episode": "行动",
    "workflow": "流程",
}


# ═══════════════════════════════════════════════════════════════
# 衰减评分
# ═══════════════════════════════════════════════════════════════


def recency_decay(
    last_accessed_at: datetime | None,
    now: datetime | None = None,
) -> float:
    """半衰期衰减：``0.5 ** (days_since_access / 30)``。

    - 从未访问（``last_accessed_at=None``）→ 视为刚访问（decay = 1.0）。
    - 距现在越久衰减越强，30 天 → 0.5，60 天 → 0.25。
    """
    now = now or datetime.now(UTC)
    ref = last_accessed_at or now
    days = max((now - ref).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (days / _HALF_LIFE_DAYS)


def memory_score(mem: AgentMemory, now: datetime | None = None) -> float:
    """加权评分 = importance × confidence × recency_decay。"""
    return float(mem.importance) * float(mem.confidence) * recency_decay(mem.last_accessed_at, now)


def _parse_embedding(raw: str | list | None) -> list[float]:
    """解析 JSON TEXT 或 list 形态的用户记忆 embedding 向量。"""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [float(v) for v in raw]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [float(v) for v in parsed]
        except (ValueError, TypeError, json.JSONDecodeError):
            pass
    return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """手工 numpy 余弦相似度（向量已 L2-normalize 时等价点积）。

    与 knowledge / vector_store 的检索口径一致（此处不用存量 EmbeddingService.cosine_similarity，
    以便在测试中注入任意维度向量，不依赖模型维度）。
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        import numpy as np
        va = np.asarray(a, dtype=np.float32)
        vb = np.asarray(b, dtype=np.float32)
        na = np.linalg.norm(va)
        nb = np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(va, vb) / (na * nb))
    except Exception:  # numpy 不可用时退化为纯 Python 点积
        norm_a = sum(v * v for v in a) ** 0.5
        norm_b = sum(v * v for v in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return sum(x * y for x, y in zip(a, b)) / (norm_a * norm_b)


# ═══════════════════════════════════════════════════════════════
# 冲突合并
# ═══════════════════════════════════════════════════════════════


async def _find_best_similar(
    db: AsyncSession,
    user_id: str,
    memory_type: str,
    embedding: list[float],
) -> tuple[AgentMemory, float] | None:
    """在同 user 同 type 的未删除、未取代记忆池中找最相似（含 score）。"""
    stmt = (
        select(AgentMemory)
        .where(
            AgentMemory.user_id == user_id,
            AgentMemory.memory_type == memory_type,
            AgentMemory.is_deleted == False,  # noqa: E712
            AgentMemory.superseded_by.is_(None),
            AgentMemory.embedding.isnot(None),
        )
        .limit(100)
    )
    result = await db.execute(stmt)
    best: tuple[AgentMemory, float] | None = None
    for c in result.scalars().all():
        cached = _parse_embedding(c.embedding)
        if not cached:
            continue
        score = _cosine_similarity(embedding, cached)
        if best is None or score > best[1]:
            best = (c, score)
    return best


async def merge_on_conflict(
    db: AsyncSession,
    user_id: str,
    fact,
    embedding: list[float],
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """冲突合并入库，返回 ``(新记忆 id, 被取代的旧记忆 id 列表)``。

    与同 user 同 type 现有（``is_deleted=False`` 且 ``superseded_by IS NULL``）记忆做向量
    相似度比对（阈值 0.85）：
    - 超阈值 → 软删旧记忆（``is_deleted=True``）+ 旧记忆 ``superseded_by`` 指向新记忆 + 新建记忆；
      返回 ``(new_id, [old_id])``；
    - 不超阈值 → 直接新建；返回 ``(new_id, [])``。
    """
    from app.modules.safety.memory.schemas import MemoryFact

    f: MemoryFact = fact

    # 先在同 user 同 type 的现有记忆中找最相似（排除即将插入的新记忆，避免软删自身）
    best_old = None
    if embedding:
        best_old = await _find_best_similar(db, user_id, f.memory_type, embedding)

    new_mem = AgentMemory(
        user_id=user_id,
        memory_type=f.memory_type,
        content=f.content,
        embedding=(json.dumps(embedding) if embedding else None),
        importance=float(f.importance),
        confidence=float(f.confidence),
    )
    db.add(new_mem)
    await db.flush()  # INSERT RETURNING 回填 id，无需 re-fetch

    if best_old is not None and best_old[1] >= _DEDUP_SIMILARITY_THRESHOLD:
        old = best_old[0]
        old.is_deleted = True
        old.superseded_by = new_mem.id
        await db.flush()
        # UPDATE → select re-fetch（async 铁律：UPDATE 后必须 eager re-fetch，避免 MissingGreenlet）
        fresh_old = (
            (await db.execute(
                select(AgentMemory)
                .where(AgentMemory.id == old.id)
                .execution_options(populate_existing=True)
            )).scalar_one_or_none()
        )
        logger.info(
            "Memory merge: soft-deleted old=%s superseded_by new=%s (sim=%.3f)",
            (fresh_old.id if fresh_old else old.id), new_mem.id, best_old[1],
        )
        return new_mem.id, [old.id]

    return new_mem.id, []


# ═══════════════════════════════════════════════════════════════
# 事件化提取
# ═══════════════════════════════════════════════════════════════


def _last_user_message(events) -> str:
    """取事件流中最近一条 user_message 事件的内容。"""
    for ev in reversed(events):
        if ev.event_type == "user_message":
            return str((ev.payload or {}).get("content", ""))
    return ""


def _last_assistant_message(events) -> str:
    """取事件流中最近一条 assistant_message 事件的内容。"""
    for ev in reversed(events):
        if ev.event_type == "assistant_message":
            return str((ev.payload or {}).get("content", ""))
    return ""


async def extract_from_events(
    db: AsyncSession,
    session_id: uuid.UUID,
    deps: SafetyDeps,
) -> int:
    """从事件流提取记忆（替代 executor._schedule_memory_extraction）。

    1. 从 ``agent_session_events`` 取最近一轮 ``user_message`` + ``assistant_message`` 事件；
    2. 复用 ``MemoryExtractor.extract``（不改 LLM prompt）得到候选 ``MemoryFact``；
    3. 对每条生成 embedding → ``merge_on_conflict`` 入库；返回实际保存条数。

    失败可重放：事件已持久化，重跑本函数即可恢复，不依赖任何瞬态 result 对象。
    """
    from app.modules.safety.business_agent.core.events import get_events
    from app.modules.safety.memory.extractor import MemoryExtractor

    # 1. 从事件流取最近一轮对话（事件已持久，可重放）
    events = await get_events(db, session_id)
    user_msg = _last_user_message(events)
    agent_reply = _last_assistant_message(events)
    if not user_msg or not agent_reply:
        return 0

    # 2. 复用现有 LLM 提取逻辑
    facts = await MemoryExtractor().extract(user_msg, agent_reply, deps)
    if not facts or not deps.person or not deps.person.user_id:
        return 0

    # 3. 生成 embedding → 冲突合并 → 入库
    embedder = await _get_embedder()
    user_id = deps.person.user_id
    saved = 0
    for f in facts:
        try:
            embedding = await embedder.embed(f.content)
        except Exception:
            logger.debug("Embedding failed for memory fact, using empty", exc_info=True)
            embedding = []
        try:
            # merge 返回 (新 id, 被取代旧 id 列表)；superseded 记录在 memory_write 事件 payload 中
            new_id, superseded_ids = await merge_on_conflict(db, user_id, f, embedding)
            if new_id:
                saved += 1
                # 留痕：写 memory_write 事件（事件持久，失败可重放，审计可追溯）
                try:
                    from app.modules.safety.business_agent.core.events import (
                        append_event,
                    )
                    await append_event(
                        db, session_id=session_id, event_type="memory_write",
                        payload={
                            "memory_id": str(new_id),
                            "memory_type": f.memory_type,
                            "content": f.content,
                            "superseded": [str(sid) for sid in superseded_ids],
                        },
                    )
                except Exception:
                    logger.debug("memory_write event append failed", exc_info=True)
        except Exception:
            logger.debug("Memory merge/save failed for fact", exc_info=True)
    if saved:
        await db.commit()
        logger.info("Memory extract_from_events: saved %d facts for user=%s", saved, user_id)
    return saved


async def _get_embedder():
    """懒加载 EmbeddingService 单例。"""
    from app.modules.safety.knowledge.embedding_service import EmbeddingService
    return EmbeddingService()


# ═══════════════════════════════════════════════════════════════
# 衰减检索
# ═══════════════════════════════════════════════════════════════


async def retrieve_with_decay(
    db: AsyncSession,
    user_id: str,
    query: str,
    top_k: int = 5,
    *,
    query_embedding: list[float] | None = None,
) -> list[dict]:
    """检索与查询相关记忆，排序用 ``score = similarity × importance × confidence × recency``。

    ``query_embedding`` 可显式传入（测试/调用方已知向量时），否则由 ``EmbeddingService`` 生成。

    Returns:
        [{"id": str, "content": str, "memory_type": str, "similarity": float,
          "importance": float, "confidence": float, "decay": float, "last_accessed_at": str|None}, ...]
        按 score 降序。
    """
    try:
        if query_embedding is not None:
            query_emb = query_embedding
        else:
            embedder = await _get_embedder()
            try:
                query_emb = await embedder.embed(query)
            except Exception:
                logger.debug("Embedding unavailable for memory retrieval", exc_info=True)
                return []

        stmt = (
            select(AgentMemory)
            .where(
                AgentMemory.user_id == user_id,
                AgentMemory.is_deleted == False,  # noqa: E712
                AgentMemory.superseded_by.is_(None),
                AgentMemory.embedding.isnot(None),
            )
            .limit(200)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        scored: list[dict] = []
        for m in rows:
            cached = _parse_embedding(m.embedding)
            if not cached:
                continue
            vec_sim = _cosine_similarity(query_emb, cached)
            decay = memory_score(m)  # importance × confidence × recency
            score = vec_sim * decay
            if score <= 0:
                continue
            scored.append({
                "id": str(m.id),
                "content": m.content,
                "memory_type": m.memory_type,
                "similarity": round(vec_sim, 4),
                "importance": m.importance,
                "confidence": m.confidence,
                "decay": round(decay, 4),
                "last_accessed_at": (
                    m.last_accessed_at.isoformat() if m.last_accessed_at else None
                ),
            })

        # 排序分 = 相似度 × decay（无相似度下限门槛，保证衰减可参与排序）
        scored.sort(key=lambda x: x["similarity"] * x["decay"], reverse=True)
        top = scored[:top_k]

        # 命中后更新 last_accessed_at + access_count（record_access）
        for item in top:
            try:
                await _record_access(db, uuid.UUID(item["id"]))
            except Exception:
                pass
        return top
    except Exception:
        logger.exception("retrieve_with_decay failed")
        return []


async def _record_access(db: AsyncSession, memory_id: uuid.UUID) -> None:
    """记录一次检索（access_count + 1，更新 last_accessed_at）。

    UPDATE → 写后 select re-fetch（async 铁律：UPDATE 后必须 eager re-fetch，
    避免后续 access 到未加载字段触发 MissingGreenlet）。
    """
    from sqlalchemy import update

    stmt = (
        update(AgentMemory)
        .where(AgentMemory.id == memory_id)
        .values(
            access_count=AgentMemory.access_count + 1,
            last_accessed_at=datetime.now(UTC),
        )
    )
    await db.execute(stmt)
    await db.flush()
    # UPDATE 后 select re-fetch（eager 覆盖缓存，与 repository.update_hazard 同法）
    await db.execute(
        select(AgentMemory)
        .where(AgentMemory.id == memory_id)
        .execution_options(populate_existing=True)
    )


# ═══════════════════════════════════════════════════════════════
# 注入渲染（供 prompt.py MemoriesSection）
# ═══════════════════════════════════════════════════════════════


def inject_to_prompt(memories: list[dict]) -> list[str]:
    """渲染检索到的记忆为 prompt.py MemoriesSection 需要的 list[str]。

    每条形如 ``[偏好] 我负责生产部 (2026-08-01)``——带 memory_type 中文标签 + 时间。
    """
    lines: list[str] = []
    for m in memories:
        label = _MEMORY_TYPE_LABELS.get(m.get("memory_type", ""), m.get("memory_type", "记忆"))
        content = m.get("content", "")
        when = _format_memory_time(m)
        lines.append(f"[{label}] {content} {when}")
    return lines


def _format_memory_time(m: dict) -> str:
    """从 last_accessed_at / 无记录时取 created 兜底，渲染为 ``(YYYY-MM-DD)``。

    last_accessed_at 反映最近被召回，优于默认 created_at 展示。
    """
    iso = m.get("last_accessed_at")
    if iso:
        try:
            dt = datetime.fromisoformat(iso)
            return f"({dt.strftime('%Y-%m-%d')})"
        except (ValueError, TypeError):
            pass
    return "(未知时间)"
