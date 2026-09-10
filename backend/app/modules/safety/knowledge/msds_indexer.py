"""MSDS 台账 → 知识库文章 + RAG chunk 索引。

让 MSDS 可被知识库检索：将每条 msds_documents 记录映射为
knowledge_articles（category='sds'，source=法规标准库、tags=化学品管理），
并复用 rebuild_article_chunks 生成 chunk + embedding（幂等：删旧重建）。

触发点：
- service/msds.py 写回管线（_create_registry_entries）
- feishu/msds_bitable_handler.py 事件镜像（created/changed/deleted）
- scripts/backfill_msds_to_knowledge.py 存量回填

注：当前全部非删除台账均纳入（审核流未上线）；未来如按 review_status
收紧，可在 sync_msds_document_to_knowledge 入口处加过滤。
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from app.core.database import async_session_factory
from app.modules.safety.knowledge.chunk_service import rebuild_article_chunks
from app.modules.safety.models import (
    MsdsDocument,
    RegulationChunk,
    SafetyKnowledgeArticle,
)

logger = logging.getLogger(__name__)

# ── 知识文章归属（对齐前端 KNOWLEDGE_MENU「法规标准库>化学品管理」）──
MSDS_ARTICLE_SOURCE = "法规标准库"
MSDS_ARTICLE_TAG = "化学品管理"
MSDS_ARTICLE_CATEGORY = "sds"  # KnowledgeCategory.SDS 化学品安全技术说明书

# 28 字段 → 全文拼接顺序（中文标签）
MSDS_FIELD_LABELS: list[tuple[str, str]] = [
    # 基础标识
    ("物质名称", "name"),
    ("CAS号", "cas_no"),
    ("分子式", "molecular_formula"),
    ("UN编号", "un_no"),
    # 危险性概述
    ("危险性说明", "hazard_statement"),
    ("标签要素", "label_elements"),
    # 理化特性
    ("外观与现状", "appearance"),
    ("溶解性", "solubility"),
    ("熔点", "melting_point"),
    ("沸点", "boiling_point"),
    ("闪点", "flash_point"),
    ("相对密度", "relative_density"),
    ("爆炸上限(%)", "explosion_upper_limit"),
    ("爆炸下限(%)", "explosion_lower_limit"),
    ("自燃温度", "autoignition_temperature"),
    ("分解温度", "decomposition_temperature"),
    # 职业接触限值
    ("PC-TWA", "pc_twa"),
    ("PC-STEL", "pc_stel"),
    ("MAC", "mac"),
    # 健康与环境危害
    ("健康危害", "health_hazard"),
    ("环境危害", "environmental_hazard"),
    # 应急响应
    ("急救措施", "first_aid"),
    ("消防措施", "fire_fighting"),
    ("泄漏应急处理", "leakage_response"),
    ("废弃处置", "waste_disposal"),
    # 防护与控制
    ("接触控制与个体防护", "exposure_controls"),
    ("操作处置与储存注意事项", "handling_storage"),
    ("稳定性和反应性", "stability_reactivity"),
]


def build_msds_full_text(doc: MsdsDocument) -> str:
    """28 字段 → 结构化全文（仅非空字段，`中文标签：值` 逐行）。"""
    parts: list[str] = []
    for label, attr in MSDS_FIELD_LABELS:
        value = getattr(doc, attr, None)
        if value:
            parts.append(f"{label}：{value}")
    return "\n".join(parts)


def _article_title(doc: MsdsDocument) -> str:
    if doc.name:
        return doc.name.strip()
    if doc.cas_no:
        return f"MSDS-{doc.cas_no.strip()}"
    return f"MSDS-{str(doc.id)[:8]}"


async def _find_article_by_msds(
    session, doc: MsdsDocument
) -> SafetyKnowledgeArticle | None:
    """按 feishu_record_id + source 查找已同步的文章（幂等键）。

    feishu_record_id 为空时退化为 title + source 查重。
    """
    if doc.feishu_record_id:
        stmt = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.feishu_record_id == doc.feishu_record_id,
            SafetyKnowledgeArticle.source == MSDS_ARTICLE_SOURCE,
            SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
        )
    else:
        stmt = select(SafetyKnowledgeArticle).where(
            SafetyKnowledgeArticle.title == _article_title(doc),
            SafetyKnowledgeArticle.source == MSDS_ARTICLE_SOURCE,
            SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
        )
    return await session.scalar(stmt)


async def sync_msds_document_to_knowledge(
    document_id: uuid.UUID,
    session=None,
) -> dict:
    """同步一条 MSDS 台账到知识库（幂等）。

    创建/更新 knowledge_articles 后调用 rebuild_article_chunks
    重建 chunk + embedding（删旧重建）。失败仅记日志，不抛异常。

    Args:
        document_id: msds_documents.id
        session: 可选已有 AsyncSession（调用方负责 commit）；缺省自建。

    Returns:
        dict: {document_id, title, article_id, action, chunks_created, error}
    """
    stats: dict = {
        "document_id": str(document_id),
        "title": "",
        "article_id": None,
        "action": "skipped",
        "chunks_created": 0,
        "error": None,
    }

    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        doc = await session.get(MsdsDocument, document_id)
        if not doc or doc.is_deleted:
            stats["error"] = f"MsdsDocument not found or deleted: {document_id}"
            return stats

        title = _article_title(doc)
        stats["title"] = title

        # ── 幂等查重 → 创建/更新文章 ──
        article = await _find_article_by_msds(session, doc)
        if article:
            stats["action"] = "updated"
        else:
            article = SafetyKnowledgeArticle(title=title)
            session.add(article)
            stats["action"] = "created"

        full_text = build_msds_full_text(doc)
        article.title = title
        article.summary = (doc.hazard_statement or "")[:300] or None
        article.category = MSDS_ARTICLE_CATEGORY
        article.source = MSDS_ARTICLE_SOURCE
        article.tags = MSDS_ARTICLE_TAG
        article.status = "published"
        if doc.feishu_record_id:
            article.feishu_record_id = doc.feishu_record_id
        if doc.cas_no:
            article.article_no = doc.cas_no.strip()
        article.full_text = full_text
        await session.flush()
        stats["article_id"] = str(article.id)

        # ── 重建 chunk + embedding（幂等：内部删旧重建）──
        rebuilt = await rebuild_article_chunks(article.id, session=session)
        stats["chunks_created"] = rebuilt.get("chunks_created", 0)
        if rebuilt.get("error"):
            stats["error"] = rebuilt["error"]
            logger.warning(
                "MSDS 知识索引 chunk 重建失败: doc=%s error=%s",
                document_id, rebuilt["error"],
            )

        if own_session:
            await session.commit()
    except Exception as e:
        logger.exception("sync_msds_document_to_knowledge failed: %s", document_id)
        stats["error"] = str(e)
        if own_session:
            await session.rollback()
    finally:
        if own_session:
            await session.close()

    return stats


async def remove_msds_from_knowledge(
    document_id: uuid.UUID,
    session=None,
) -> dict:
    """移除 MSDS 台账对应的知识文章（软删）及其 chunks。

    配合台账删除调用；幂等（文章不存在时静默跳过）。
    """
    stats: dict = {"document_id": str(document_id), "removed": 0}

    own_session = session is None
    if own_session:
        session = async_session_factory()

    try:
        doc = await session.get(MsdsDocument, document_id)
        if not doc or not doc.feishu_record_id:
            stats["error"] = f"MsdsDocument not found: {document_id}"
            return stats

        article = await _find_article_by_msds(session, doc)
        if not article:
            stats["removed"] = 0
            return stats

        await session.execute(
            sa_delete(RegulationChunk).where(
                RegulationChunk.article_id == article.id,
                RegulationChunk.is_deleted == False,  # noqa: E712
            )
        )
        article.is_deleted = True
        stats["removed"] = 1
        logger.info("MSDS 知识索引移除: doc=%s article=%s", document_id, article.id)

        if own_session:
            await session.commit()
    except Exception as e:
        logger.exception("remove_msds_from_knowledge failed: %s", document_id)
        stats["error"] = str(e)
        if own_session:
            await session.rollback()
    finally:
        if own_session:
            await session.close()

    return stats
