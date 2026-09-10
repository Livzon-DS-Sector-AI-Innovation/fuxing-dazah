"""Chunk rebuild service — single-article chunk + embedding rebuild.

Extracted from scripts/tmp/build_regulation_index.py so it can be called from:
- build_regulation_index.py (batch rebuild)
- knowledge_bitable_handler.py (real-time auto rebuild on Bitable change)
"""

from __future__ import annotations

import hashlib
import json as _json
import logging
import os
import uuid as _uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.knowledge.chunker import ArticleChunker
from app.modules.safety.knowledge.document_loader import DocumentLoader
from app.modules.safety.knowledge.embedding_service import EmbeddingService
from app.modules.safety.models import RegulationChunk, SafetyKnowledgeArticle

# 扫描型标准 PDF 的 OCR 回退：PyMuPDF 抽取不到文字（无文字层）时，
# 用 qwen-vl 视觉模型逐页 OCR 还原全文。仅作为降级路径，避免全覆盖拉高成本。
_OCR_MAX_PAGES = 40  # 单个文档最多 OCR 页数（防止超长标准）
_OCR_BATCH_SIZE = 6  # 每次视觉调用处理的页数


async def _try_ocr_pdf(local_path: str, title: str) -> str:
    """对扫描型 PDF（无文字层）做 qwen-vl OCR，返回全文文本。失败返回空串。"""
    if not local_path or not os.path.isfile(local_path):
        return ""
    try:
        import fitz as _fitz

        doc = _fitz.open(local_path)
        total_pages = min(doc.page_count, _OCR_MAX_PAGES)
        page_imgs: list[str] = []
        try:
            for pi in range(total_pages):
                pix = doc[pi].get_pixmap(dpi=150)
                img_path = (
                    f"uploads/safety/knowledge/ocr_tmp_{_uuid.uuid4().hex[:8]}_{pi}.png"
                )
                pix.save(img_path)
                page_imgs.append(img_path)
        finally:
            doc.close()

        if not page_imgs:
            return ""

        # OCR（分批，避免单次图片过多）
        from app.modules.safety.ai_audit import ai_audit_scope
        from app.modules.safety.service.config import create_ai_service
        from app.modules.safety.vision.service import VisionService

        vision = VisionService(create_ai_service("vision"))
        chunks_text: list[str] = []
        # 审计归因：扫描件 OCR 属系统自动化流程（channel=system）
        with ai_audit_scope(scenario="regulation_ocr", channel="system"):
            for start in range(0, len(page_imgs), _OCR_BATCH_SIZE):
                batch = page_imgs[start:start + _OCR_BATCH_SIZE]
                try:
                    t = await vision.analyze(
                        text_prompt=(
                            "这是中国国家标准或行业标准的扫描页。请逐字、完整地提取每一页的所有"
                            "中文文本（含汉字、数字、标点、标准号），不要做任何解释、总结或格式变换，"
                            "直接按页输出原文，每页之间用换行分隔。"
                        ),
                        image_urls=batch,
                    )
                except Exception:
                    logger.exception("OCR 批次失败: %s", title)
                    t = None
                if t and t.strip():
                    chunks_text.append(t.strip())

        # 清理临时图片
        for p in page_imgs:
            try:
                os.remove(p)
            except OSError:
                pass

        full = "\n".join(chunks_text)
        if full.strip():
            logger.info("OCR 提取成功: %s (%d chars, %d 页)", title, len(full), total_pages)
            return full.strip()
    except Exception:
        logger.exception("OCR 回退失败: %s", title)
    return ""

logger = logging.getLogger(__name__)

# ── Config ──

# embedding 配置（api_key/base_url/model/dims）经 AI 配置中心函数级解析
# （DB→env→registry 默认），不再使用模块级常量——改配置后下次重建即生效。
BATCH_SIZE = 20  # chunks per embedding API call


def _sanitize_text(text: str) -> str:
    """Remove NULL bytes and other characters unsafe for PostgreSQL UTF-8."""
    if not text:
        return text
    return text.replace("\x00", "")


def _extract_file_token(path: str) -> str:
    """Extract Feishu Drive file_token from attachment path.

    Supports formats:
    1. knowledge_sync_{record_id}_{file_token}_{name}
    2. Bare file_token (20-40 char alphanumeric)
    3. Path ending with bare token
    """
    import re

    if not path or not path.strip():
        return ""
    path = path.strip()

    # Format 1: knowledge_sync_{record_id}_{file_token}_{name}
    m = re.search(r"knowledge_sync_[^_]+_([A-Za-z0-9]+)_", path)
    if m:
        return m.group(1)

    # Format 2: bare file_token
    if re.match(r"^[A-Za-z0-9]{20,40}$", path):
        return path

    # Format 3: path ending with bare token
    if "/" in path:
        last_segment = path.rsplit("/", 1)[-1]
        if re.match(r"^[A-Za-z0-9]{20,40}$", last_segment):
            return last_segment

    logger.warning("_extract_file_token: unrecognized path format: %s", path[:80])
    return ""


def _extract_text_from_card(card: dict | str) -> str:
    """Extract full text from knowledge_card JSON."""
    if isinstance(card, str):
        try:
            card = _json.loads(card)
        except _json.JSONDecodeError:
            return ""

    fields = [
        "hazard_type_definitions",
        "hazard_category_criteria",
        "hazard_level_criteria",
        "key_defect_examples",
        "rectification_requirements",
        "legal_basis_clauses",
    ]
    parts = []
    for f in fields:
        v = card.get(f, "") if isinstance(card, dict) else ""
        if v:
            parts.append(str(v))
    return "\n\n".join(parts)


async def rebuild_article_chunks(
    article_id: _uuid.UUID,
    session=None,
    dry_run: bool = False,
) -> dict:
    """Rebuild chunks + embeddings for a single knowledge article.

    Deletes old chunks, downloads/parses full text (if needed), re-chunks,
    and generates new embeddings. Safe to call multiple times (idempotent).

    Args:
        article_id: UUID of the SafetyKnowledgeArticle.
        session: Optional existing AsyncSession. If None, creates + commits
                 its own session. Callers doing batch rebuild should pass
                 their session and commit externally.
        dry_run: If True, count only — no writes.

    Returns:
        dict with keys: title, chunks_created, embedded, deleted, error
    """
    stats: dict = {
        "title": "",
        "chunks_created": 0,
        "embedded": 0,
        "deleted": 0,
        "error": None,
    }

    # 向量配置经 AI 配置中心解析（函数级读取：DB→env→registry 默认，每次重建取新值）
    from app.modules.safety.ai_config.resolver import get_profile_config

    embed_cfg = get_profile_config("embedding")
    embedder = EmbeddingService(
        api_key=embed_cfg["api_key"],
        base_url=embed_cfg["base_url"],
        model=embed_cfg["model"],
        dims=embed_cfg["dims"],
    )

    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        # ── Load article ──
        stmt = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.id == article_id,
            SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
        )
        result = await session.execute(stmt)
        article = result.scalar_one_or_none()

        if not article:
            stats["error"] = f"Article not found: {article_id}"
            return stats

        title = article.title or "(untitled)"
        stats["title"] = title

        loader = DocumentLoader()
        chunker = ArticleChunker()

        # ── Get full text ──
        full_text = article.full_text or article.content or ""

        if not full_text:
            if article.attachment_path:
                import asyncio as _asyncio

                # ── 优先读取本地文件（已在 _create_knowledge_from_bitable 下载）──
                local_path = article.attachment_path
                if os.path.isfile(local_path):
                    try:
                        import fitz as _fitz
                        doc = _fitz.open(local_path)
                        full_text = ""
                        for page in doc:
                            t = page.get_text()
                            if t and t.strip():
                                full_text += t + "\n"
                        doc.close()
                        if full_text.strip():
                            full_text = full_text.strip()
                            logger.info("从本地文件读取成功: %s (%d chars)", title, len(full_text))
                        else:
                            # 扫描型 PDF（无文字层）→ qwen-vl OCR 回退
                            full_text = await _try_ocr_pdf(local_path, title)
                    except Exception as e:
                        logger.warning("本地文件读取失败: %s, path=%s, error=%s", title, local_path, e)

                # ── MinIO 分支：本地未命中时按 object key 物化临时文件（保留 .pdf 后缀）解析 ──
                if not full_text and not os.path.isfile(local_path):
                    tmp_path = None
                    try:
                        from app.modules.safety.attachment_store import (
                            cleanup_temp,
                            materialize,
                        )

                        ext = os.path.splitext(local_path)[1].lower() or ".pdf"
                        tmp_path = materialize(local_path, suffix=ext)
                        if tmp_path is not None:
                            import fitz as _fitz
                            doc = _fitz.open(str(tmp_path))
                            full_text = ""
                            for page in doc:
                                t = page.get_text()
                                if t and t.strip():
                                    full_text += t + "\n"
                            doc.close()
                            if full_text.strip():
                                full_text = full_text.strip()
                                logger.info("从 MinIO 读取成功: %s (%d chars)", title, len(full_text))
                            else:
                                # 扫描型 PDF（无文字层）→ qwen-vl OCR 回退
                                full_text = await _try_ocr_pdf(str(tmp_path), title)
                    except Exception as e:
                        logger.warning(
                            "附件存储回读失败（本地与 MinIO 均未命中）: %s, path=%s, error=%s",
                            title, local_path, e,
                        )
                    finally:
                        if tmp_path is not None:
                            cleanup_temp(tmp_path)

                # ── 回退：从 Drive 下载（带重试）──
                if not full_text:
                    file_token = _extract_file_token(article.attachment_path)
                    for dl_attempt in range(3):
                        try:
                            full_text, _ = await loader.download_and_parse(
                                file_token=file_token,
                                title=title,
                                max_chars=100000,
                            )
                        except Exception as e:
                            logger.warning("Drive download failed for '%s': %s", title, e)
                            full_text = ""

                        if full_text:
                            break

                        if dl_attempt < 2:
                            delay = (dl_attempt + 1) * 3
                            logger.info(
                                "Drive 下载未就绪，%ds 后重试 (%d/3): %s",
                                delay, dl_attempt + 1, title,
                            )
                            await _asyncio.sleep(delay)

            if not full_text and article.knowledge_card:
                full_text = _extract_text_from_card(article.knowledge_card)

        if not full_text:
            stats["error"] = f"No text available for '{title}'"
            return stats

        # ── Delete old chunks ──
        if not dry_run:
            deleted = await session.execute(
                sa_delete(RegulationChunk).where(
                    RegulationChunk.article_id == article.id,
                    RegulationChunk.is_deleted == False,  # noqa: E712
                )
            )
            stats["deleted"] = deleted.rowcount
            if deleted.rowcount:
                logger.info(
                    "Deleted %d old chunks for '%s'", deleted.rowcount, title,
                )
        else:
            from sqlalchemy import func as sqlfunc

            cnt_stmt = (
                select(sqlfunc.count())
                .select_from(RegulationChunk)
                .where(
                    RegulationChunk.article_id == article.id,
                    RegulationChunk.is_deleted == False,  # noqa: E712
                )
            )
            cnt_result = await session.execute(cnt_stmt)
            stats["deleted"] = cnt_result.scalar() or 0

        # ── Chunk ──
        chunks = chunker.chunk(
            full_text,
            title=title,
            category=article.category or "",
            priority="P1",
        )

        if not chunks:
            stats["error"] = f"Chunking produced nothing for '{title}'"
            return stats

        logger.info(
            "'%s': %d chars → %d chunks", title, len(full_text), len(chunks),
        )

        # ── Embed + store ──
        if not dry_run:
            for batch_start in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[batch_start : batch_start + BATCH_SIZE]
                texts = [c.text for c in batch]
                try:
                    embeddings = await embedder.embed_batch(texts, use_cache=False)
                except Exception as e:
                    logger.warning(
                        "Embedding batch failed for '%s': %s", title, e,
                    )
                    embeddings = [None] * len(batch)

                for i, chunk in enumerate(
                    chunks[batch_start : batch_start + BATCH_SIZE]
                ):
                    emb_json = (
                        _json.dumps(embeddings[i])
                        if i < len(embeddings) and embeddings[i]
                        else None
                    )
                    db_chunk = RegulationChunk(
                        article_id=article.id,
                        chunk_text=_sanitize_text(chunk.text),
                        chunk_index=chunk.index,
                        doc_title=title,
                        doc_category=article.category or "",
                        chapter_title=chunk.chapter_title or "",
                        article_ref=chunk.article_ref or "",
                        embedding=emb_json,
                        priority=chunk.priority,
                    )
                    session.add(db_chunk)
                    stats["chunks_created"] += 1
                    if (
                        embeddings
                        and i < len(embeddings)
                        and embeddings[i]
                    ):
                        stats["embedded"] += 1

                await session.flush()

            # Update article metadata
            text_hash = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
            article.full_text = _sanitize_text(full_text)
            article.full_text_hash = text_hash
            article.chunk_count = len(chunks)
            await session.flush()
        else:
            stats["chunks_created"] = len(chunks)
            stats["embedded"] = len(chunks)

        if own_session and not dry_run:
            await session.commit()

    except Exception as e:
        logger.exception("rebuild_article_chunks failed for %s", article_id)
        stats["error"] = str(e)
        if own_session:
            await session.rollback()
    finally:
        if own_session:
            await session.close()

    return stats
