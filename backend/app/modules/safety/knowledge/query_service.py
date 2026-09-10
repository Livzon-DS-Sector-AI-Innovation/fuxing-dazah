"""Knowledge query service — reusable RAG pipeline for API and Feishu bot.

Extracted from info_query.py so both the web endpoint and the Feishu bot
handler can share the same retrieval + AI generation logic.
"""

from __future__ import annotations

import logging
import os
from collections import OrderedDict
from uuid import UUID as _UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.bitable_config.store import ConnectionView, store
from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever
from app.modules.safety.knowledge.web_search import WebSearchResult, WebSearchService
from app.modules.safety.knowledge.web_search_prompt import (
    HYBRID_SYSTEM_PROMPT,
    WEB_SEARCH_SYSTEM_PROMPT,
)
from app.modules.safety.models import SafetyKnowledgeArticle
from app.modules.safety.service.config import create_ai_service

logger = logging.getLogger(__name__)

# ── Feishu Bitable link config（凭证延迟读 store：改表 ID 后链接立即用新值）──

_FEISHU_BASE_URL = os.getenv("FEISHU_BASE_URL", "https://livzon.feishu.cn")


def _knowledge_conn() -> ConnectionView | None:
    """knowledge 域连接视图（同步读 store 缓存）。"""
    return store.get_connection("knowledge", "collection")

# ── AI system prompt ──

SYSTEM_PROMPT = """你是一个安全生产法规知识库助手，专门回答关于中国安全生产法律法规、标准规范的问题。

## 你的能力
- 基于提供的法规原文条款回答问题
- 解释法规条款的具体含义和适用场景
- 帮助用户查找特定主题的相关法规

## 回答规则

### 引用标注规则（严格遵守）

1. **[N] 仅标注在法规名称旁**：[N] 标记**只能**紧跟在法规/标准/制度名称的后面，格式为 `《法规名》[N]`。**禁止**在任何其他位置添加 [N]。
   - [N] 内**仅**包含数字编号，不得加入条款号、章节号等其他内容。
   - ✅ 正确：根据《GB 3836.1-2021》[1] 第6.2条规定，防爆堵头应使用金属材质。
   - ❌ 错误（标在内容后）：防爆堵头应使用金属或高强度非金属材质 [1]。
   - ❌ 错误（多个编号）：防爆堵头应使用金属材质 [1][2]。
   - ❌ 错误（非纯数字）：根据《特种作业规定》[3 第1.3条] 要求…

2. **编号从 [1] 开始按顺序排列**：正文中第一次出现的法规用 [1]，第二次出现的另一部法规用 [2]，以此类推。**禁止出现跳号**（如 [1]、[3]、[5]）。

3. **同一法规始终用同一编号**：即使多次引用同一法规的不同条款，始终使用该法规第一次出现时的编号。

4. **编号范围限制**：只能使用 [1] 到 [N_max] 范围内的编号。N_max = 参考法规文档总数。不得使用超出范围的编号。

5. **每段最多标注一次**：同一个段落内，同一部法规只需在首次提及时标注编号，后续提及同一法规可省略编号。

### 内容规则

6. **基于原文**：所有回答必须基于用户消息中「参考法规」部分的条款原文，不得使用训练记忆中的信息。
7. **诚实回应**：如果检索到的法规条款不足以回答问题，请明确说明「根据当前知识库中的资料，未找到相关法规条款」，不要编造内容。
8. **简洁专业**：用简洁、专业的语言回答，避免冗余。使用分点或表格组织多方面内容。
9. **追问支持**：如果用户追问之前的回答，结合对话历史和法规原文进行回应。

### ⚠️ 禁止事项

10. **禁止在回答末尾添加任何形式的「参考法规」「📚 参考法规」「📚 参考来源」等法规列表区块**。引用信息只需在正文法规名称旁标注 [N] 即可。
11. **禁止输出**用户消息中「参考法规」部分的原文内容或编号范围提示（如"共 N 篇引用文档"）。
12. **禁止**使用「[A1]」「[B1]」等非标准编号格式。

## 引用格式示例

```
根据《GB 3836.1-2021》[1] 第6.2条规定，防爆堵头应使用金属或高强度非金属材质，并满足IP防护等级要求。

按照《特种设备安全管理制度》[2] 第5.1.4条要求，设备操作人员必须持证上岗。该制度同时规定每年至少进行一次安全培训。
```

## 对话规则
- 如果用户问的是无关话题（如天气、娱乐），礼貌引导用户回到安全生产法规咨询。
- 回答中法规标准编号使用标准格式：GB（国家标准）、GB/T（推荐性国标）、AQ（安全生产行标）、HG（化工行标）等。"""


# ── Source URL building ──


def _build_bitable_url(feishu_record_id: str, feishu_table_id: str | None = None) -> str:
    """Build a clickable Bitable record URL for a knowledge article.

    Uses the article's specific table_id if available, otherwise falls back
    to the store-configured knowledge table (hazard/hazard 同级改造：改表 ID 立即生效).
    """
    if not feishu_record_id:
        return ""
    conn = _knowledge_conn()
    if conn is None or conn.status == "disabled" or not conn.app_token:
        return ""
    table_id = feishu_table_id or conn.table_id
    if not table_id:
        return ""
    return (
        f"{_FEISHU_BASE_URL}/base/{conn.app_token}"
        f"/{table_id}?record={feishu_record_id}"
    )


# ── Document-level deduplication ──


def _group_chunks_by_document(chunks: list) -> OrderedDict:
    """Group retrieved chunks by unique document.

    Uses source_doc (title) as the primary dedup key, because the same
    regulation may have duplicate article records with different UUIDs.
    Collects all distinct article_ids for feishu URL resolution.

    Returns an ordered dict mapping title → {title, article_ids, doc_category, chunks}.
    Insertion order follows first appearance in the chunk list.
    """
    groups: OrderedDict[str, dict] = OrderedDict()
    for r in chunks:
        key = r.source_doc  # dedup by document title, not article_id
        if key not in groups:
            groups[key] = {
                "title": r.source_doc,
                "article_ids": [],
                "doc_category": r.doc_category,
                "chunks": [],
            }
        # Collect all unique article_ids for this document
        if r.article_id and r.article_id not in groups[key]["article_ids"]:
            groups[key]["article_ids"].append(r.article_id)
        groups[key]["chunks"].append(r)
    return groups


def _build_document_context(doc_groups: dict[str, dict]) -> str:
    """Build AI prompt context with document-level numbering.

    One [N] per unique document. If a document has multiple chunks,
    they are listed as sub-items under the same document number.
    """
    if not doc_groups:
        return "（知识库中暂无与查询相关的法规条款）"

    count = len(doc_groups)
    parts = [
        f"（共 {count} 篇引用文档，有效编号范围：[1] 到 [{count}]）",
        "",
    ]
    for i, (key, doc) in enumerate(doc_groups.items(), 1):
        title = doc["title"]
        chunks = doc["chunks"]

        # Document header
        lines = [f"[{i}] {title}"]

        for chunk in chunks:
            ref = f" — {chunk.source_article}" if chunk.source_article else ""
            lines.append(f"    {ref}\n    {_clean_chunk_text(chunk.chunk_text)}")

        parts.append("\n".join(lines))

    return "\n\n---\n\n".join(parts)


async def _build_sources(
    db: AsyncSession,
    doc_groups: dict[str, dict],
) -> list[dict]:
    """Build deduplicated source dicts with feishu_url.

    One source per unique document (not per chunk).
    Lookup chain (in priority order):
      1. article_id → knowledge_articles (most precise)
      2. doc_title → knowledge_articles (fallback for orphan chunks)
    """
    # Collect all unique article_ids across all groups
    all_article_ids = set()
    for key, doc in doc_groups.items():
        for aid in doc.get("article_ids", []):
            if aid:
                try:
                    all_article_ids.add(_UUID(aid))
                except ValueError:
                    pass

    # ── Pass 1: article_id → feishu URL ──
    feishu_map: dict[str, str] = {}
    if all_article_ids:
        stmt = select(
            SafetyKnowledgeArticle.id,
            SafetyKnowledgeArticle.feishu_record_id,
            SafetyKnowledgeArticle.feishu_table_id,
            SafetyKnowledgeArticle.feishu_shared_url,
        ).where(SafetyKnowledgeArticle.id.in_(all_article_ids))
        result = await db.execute(stmt)
        for row in result.all():
            url = row.feishu_shared_url or _build_bitable_url(
                row.feishu_record_id or "", row.feishu_table_id
            )
            feishu_map[str(row.id)] = url

    # ── Pass 2: title → feishu_url (fallback) ──
    title_url_map: dict[str, str] = {}
    orphan_titles: set[str] = set()
    for key, doc in doc_groups.items():
        has_url = any(feishu_map.get(aid, "") for aid in doc.get("article_ids", []))
        if not has_url:
            orphan_titles.add(doc["title"])

    if orphan_titles:
        stmt = select(
            SafetyKnowledgeArticle.title,
            SafetyKnowledgeArticle.feishu_record_id,
            SafetyKnowledgeArticle.feishu_table_id,
            SafetyKnowledgeArticle.feishu_shared_url,
        ).where(
            SafetyKnowledgeArticle.title.in_(list(orphan_titles)),
            SafetyKnowledgeArticle.feishu_record_id.isnot(None),
        )
        result = await db.execute(stmt)
        for row in result.all():
            url = row.feishu_shared_url or _build_bitable_url(
                row.feishu_record_id or "", row.feishu_table_id
            )
            if url and row.title not in title_url_map:
                title_url_map[row.title] = url

    # ── Assemble source list ──
    sources = []
    for key, doc in doc_groups.items():
        chunks = doc["chunks"]
        # Merge article_refs from all chunks of this document
        refs = []
        for c in chunks:
            ref = _clean_article_ref(c.source_article)
            if ref and ref not in refs:
                refs.append(ref)

        # Use the first chunk's text as preview
        preview = _clean_chunk_text(chunks[0].chunk_text) if chunks else ""

        # Try all article_ids — use the first one that has a feishu URL
        feishu_url = ""
        for aid in doc.get("article_ids", []):
            url = feishu_map.get(aid, "")
            if url:
                feishu_url = url
                break

        # Fallback: search by document title
        if not feishu_url and doc["title"] in title_url_map:
            feishu_url = title_url_map[doc["title"]]

        sources.append({
            "doc_title": doc["title"],
            "article_ref": "; ".join(refs),
            "chunk_text": preview,
            "doc_category": doc["doc_category"],
            "feishu_url": feishu_url,
        })
    return sources


# ── Text cleaning ──

_DIMENSION_HEADERS = [
    "hazard_type_definitions",
    "hazard_category_criteria",
    "hazard_level_criteria",
    "key_defect_examples",
    "rectification_requirements",
    "legal_basis_clauses",
]


def _clean_chunk_text(text: str) -> str:
    """Strip knowledge-card dimension headers from chunk text."""
    import re

    cleaned = text.strip()
    for header in _DIMENSION_HEADERS:
        cleaned = re.sub(rf"^##\s*{header}\s*\n?", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _clean_article_ref(ref: str) -> str:
    """Convert dimension-header article_ref to a readable label, or keep as-is."""
    if not ref:
        return ""
    dim_map = {
        "hazard_type_definitions": "危险源定义",
        "hazard_category_criteria": "分类标准",
        "hazard_level_criteria": "分级标准",
        "key_defect_examples": "典型缺陷",
        "rectification_requirements": "整改要求",
        "legal_basis_clauses": "法规依据",
    }
    cleaned = ref.strip().lstrip("#").strip()
    if cleaned in dim_map:
        return dim_map[cleaned]
    return ref.strip()


# ── Web search source builder ──


def _build_web_sources(web_results: list[WebSearchResult]) -> list[dict]:
    """Build source dicts from web search results.

    These differ from RAG sources:
      - ``source_kind`` = "web" (instead of implicit "knowledge_base")
      - ``url`` field contains the public web URL (instead of feishu_url)
      - ``doc_title`` = search result title
      - ``chunk_text`` = search result snippet
    """
    sources: list[dict] = []
    for r in web_results:
        sources.append({
            "doc_title": r.title,
            "article_ref": "",
            "chunk_text": r.snippet,
            "doc_category": "",
            "feishu_url": "",
            "url": r.url,
            "source_kind": "web",
            "source_name": r.source_name,
        })
    return sources


# ── Main query function ──


async def run_knowledge_chat(
    query: str,
    history: list[dict[str, str]] | None = None,
    db: AsyncSession | None = None,
    channel: str | None = None,
    user_id: str | None = None,
    enable_web_search: bool = True,
) -> tuple[str, list[dict]]:
    """Run the full RAG pipeline: retrieve → build context → AI chat → collect sources.

    Args:
        query: The user's natural-language question.
        history: Previous conversation turns as [{"role": "...", "content": "..."}, ...].
        db: An active async database session (required).
        user_id: 当前用户标识（涉私查询时用于缓存隔离，None 则跳过私有缓存）。
        enable_web_search: 是否自动触发联网搜索（默认 True）。
            False 时仅使用内部知识库，无结果时 answer 为空提示。

    Returns:
        (answer: str, sources: list[dict]) where each source dict has:
          doc_title, article_ref, chunk_text, doc_category, feishu_url
    """
    if db is None:
        raise ValueError("db session is required for run_knowledge_chat")

    from app.modules.safety.ai_audit import ai_audit_scope
    from app.modules.safety.knowledge.cache import get_chat_cache, set_chat_cache

    # ═══ Chat 缓存检查 ═══
    cached = await get_chat_cache(query=query, history=history, user_id=user_id)
    if cached is not None:
        answer: str = cached.get("answer", "")
        sources: list[dict] = cached.get("sources", [])
        logger.debug("Knowledge chat cache HIT for query=%r", query[:60])
        return answer, sources

    # channel 未显式传入时不覆盖（Agent 工具路径下继承外层 agent_chat 作用域的渠道/用户）
    _scope_kwargs: dict = {"scenario": "knowledge_chat"}
    if channel is not None:
        _scope_kwargs["channel"] = channel

    with ai_audit_scope(**_scope_kwargs):
        # 1. Retrieve relevant regulation chunks (with AI service for reranker + entity extraction)
        ai_service = create_ai_service("text")
        try:
            retriever = SafetyKnowledgeRetriever(db, ai_service=ai_service)
            context = await retriever.retrieve(
                description=query,
                target_chunks=6,
            )
    
            # 2. Deduplicate chunks by document
            doc_groups = _group_chunks_by_document(context.chunks)
    
            # 3. ═══ 联网搜索模式判断 ═══
            if not enable_web_search:
                # 仅内部知识库，不触发联网
                mode = "kb_only"
            else:
                # 三模式判断：KB 质量 → 是否触发联网
                #   "kb_only"   — 强向量命中（KB 足够），或全量检索正常但无任何命中（回答"未找到"）
                #   "supplement"— 弱向量命中，或 embedding 降级（text_only/llm_expanded）
                #                 但 BM25 有命中：知识库结果有效,由联网补足
                #   "replace"   — 检索已降级且无任何 chunks:只能联网
                _VECTOR_THRESHOLD = 0.55  # noqa: N806
                top_vector_score = max(
                    (c.vector_score for c in context.chunks), default=0,
                )

                if top_vector_score >= _VECTOR_THRESHOLD:
                    # 强向量命中：知识库质量足够,不触发联网
                    mode = "kb_only"
                elif top_vector_score > 0:
                    # 弱向量命中：知识库 + 联网补充
                    mode = "supplement"
                elif context.chunks:
                    # 无向量但有文本命中（embedding 降级/无向量命中）：知识库结果仍有效,联网补充
                    mode = "supplement"
                elif context.degradation == "full":
                    # 全量检索正常但无任何命中：仅知识库(回答"未找到")
                    mode = "kb_only"
                else:
                    # 检索已降级且无结果：只能联网
                    mode = "replace"
    
                logger.info(
                    "Web search mode=%s for query=%r "
                    "(degradation=%s, top_vec=%.3f, chunks=%d)",
                    mode, query[:80], context.degradation,
                    top_vector_score, len(context.chunks),
                )
    
            # 4. Run web search if needed (supplement or replace mode)
            web_results: list[WebSearchResult] = []
            if mode in ("supplement", "replace"):
                try:
                    web_service = WebSearchService()
                    web_results = await web_service.search(query, num_results=5)
                    if web_results:
                        logger.info(
                            "Web search returned %d results for query=%r (mode=%s)",
                            len(web_results), query[:60], mode,
                        )
                    else:
                        logger.info(
                            "Web search returned 0 results for query=%r (mode=%s)",
                            query[:60], mode,
                        )
                except Exception:
                    logger.exception(
                        "Web search failed for query=%r, continuing without it",
                        query[:60],
                    )
    
            # 5. Build context and select system prompt by mode
            if mode == "replace":
                # Web-only: KB found nothing useful
                system_prompt = WEB_SEARCH_SYSTEM_PROMPT
                user_context = (
                    f"## 互联网搜索结果\n\n"
                    f"{WebSearchService.build_prompt_context(web_results)}\n\n"
                )
            elif mode == "supplement":
                # Hybrid: KB has weak matches, supplement with web
                system_prompt = HYBRID_SYSTEM_PROMPT
                kb_context = _build_document_context(doc_groups)
                web_context = WebSearchService.build_prompt_context(web_results)
                user_context = (
                    f"## 知识库参考法规\n\n{kb_context}\n\n"
                    f"---\n\n"
                    f"## 互联网补充信息\n\n{web_context}\n\n"
                )
            else:
                # KB-only: normal RAG path
                system_prompt = SYSTEM_PROMPT
                user_context = (
                    f"## 参考法规\n\n"
                    f"{_build_document_context(doc_groups)}\n\n"
                )
    
            # 6. Build messages for AI chat
            messages: list[dict] = [
                {"role": "system", "content": system_prompt},
            ]
    
            # Add conversation history (last N turns)
            for msg in (history or []):
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })
    
            # Add current query with context appended
            user_msg = f"{user_context}---\n\n## 问题\n\n{query}"
            messages.append({"role": "user", "content": user_msg})
    
            # 7. Call AI service
            try:
                answer = await ai_service.chat(
                    messages=messages,
                    response_format="text",
                    temperature=0.3,
                    max_tokens=4096,
                )
                ai_ok = True
            except Exception as e:
                logger.exception("AI chat failed for knowledge query")
                answer = f"抱歉，AI 服务暂时不可用，请稍后重试。错误信息：{e}"
                ai_ok = False
        finally:
            await ai_service.close()

    # 8. Build source list
    if mode == "replace":
        sources = _build_web_sources(web_results)
    elif mode == "supplement":
        # Merge: KB sources first, then web sources
        kb_sources = await _build_sources(db, doc_groups)
        web_sources = _build_web_sources(web_results)
        sources = kb_sources + web_sources
    else:
        sources = await _build_sources(db, doc_groups)

    # 9. 写入 Chat 缓存（仅 AI 调用成功时缓存，错误不缓存）
    if ai_ok:
        await set_chat_cache(
            query=query, answer=answer, sources=sources,
            history=history, user_id=user_id,
        )

    return answer, sources
