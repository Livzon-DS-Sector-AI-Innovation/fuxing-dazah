"""MSDS 台账 → 知识检索索引（ragplus 通路 / 本地旧管线双态）。

让 MSDS 可被知识检索。ragplus 总闸（SAFETY_RAGPLUS_SEARCH_ENABLED）决定走向：

- 开（现行）：台账 28 字段结构化全文 → .md 文档上传 ragplus「MSDS」库
  （换版 replace 语义；删除归「已废止」库留痕）。本函数是台账侧唯一
  收口——三条触发链（service/msds.py 写回管线 _create_registry_entries、
  feishu/msds_bitable_handler.py 事件镜像 created/changed/deleted、
  scripts/tmp/backfill_msds_to_ragplus.py 存量回填）零改动接入。
- 关（回退路径）：本地旧管线——映射 knowledge_articles
  （category='sds'，source=法规标准库、tags=化学品管理）+ chunk embedding。

注：当前全部非删除台账均纳入（审核流未上线）；未来如按 review_status
收紧，可在 sync_msds_document_to_knowledge 入口处加过滤。
"""

from __future__ import annotations

import asyncio
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


def _ragplus_biz_key(doc: MsdsDocument) -> str:
    """ragplus 映射幂等键（registry 前缀=台账行；采集 PDF 侧用 collection: 前缀）。"""
    rid = (doc.feishu_record_id or "").strip()
    return f"registry:{rid}" if rid else f"registry:db-{doc.id}"


async def _schedule_registry_ragplus_sync(
    document_id: uuid.UUID, session=None,
) -> dict:
    """ragplus 通路：读 doc 构造 md blob → 后台任务上传 MSDS 库。

    blob 在调度前于调用方 session 可见状态下构造（闭包携带），后台任务
    自建 admin/session——不依赖调用方未提交事务，规避竞态。上传失败由
    upload_document_to_ragplus 内部落 failed 映射 + 日志，不抛出。
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
        biz_key = _ragplus_biz_key(doc)
        blob = build_msds_full_text(doc).encode("utf-8")
    finally:
        if own_session:
            await session.close()

    if not blob:
        stats["error"] = "empty full_text"
        return stats
    stats["title"] = title

    from app.modules.safety.knowledge.ragplus_sync import (
        KB_MSDS,
        upload_document_to_ragplus,
    )

    async def _task() -> None:
        try:
            await upload_document_to_ragplus(
                domain="msds", biz_key=biz_key, title=title,
                file_name=f"{title}.md", blob=blob,
                content_type="text/markdown", kb_name=KB_MSDS,
            )
        except Exception:
            logger.exception("MSDS ragplus 后台上传异常: %s", biz_key)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "无运行中的事件循环，MSDS ragplus 上传不调度: %s", biz_key,
        )
        stats["error"] = "no running event loop"
        return stats
    stats["task"] = loop.create_task(_task())
    stats["action"] = "scheduled_ragplus"
    return stats


async def sync_msds_document_to_knowledge(
    document_id: uuid.UUID,
    session=None,
) -> dict:
    """同步一条 MSDS 台账到知识检索（幂等）。

    ragplus 开：后台上传 .md 全文到 ragplus「MSDS」库（换版 replace）。
    ragplus 关：本地旧管线——创建/更新 knowledge_articles 后调用
    rebuild_article_chunks 重建 chunk + embedding（删旧重建）。
    失败仅记日志，不抛异常。

    Args:
        document_id: msds_documents.id
        session: 可选已有 AsyncSession（调用方负责 commit）；缺省自建。

    Returns:
        dict: {document_id, title, article_id, action, chunks_created, error}
    """
    from app.modules.safety.knowledge.ragplus_client import ragplus_search_enabled

    if ragplus_search_enabled():
        return await _schedule_registry_ragplus_sync(document_id, session)

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


async def _schedule_registry_ragplus_archive(
    document_id: uuid.UUID, session=None,
) -> dict:
    """ragplus 通路：后台任务归档（主库删 + md 全文移「已废止」库留痕）。

    调用方（msds_bitable_handler._handle_deleted）已先软删镜像行——doc
    仍可读（含 is_deleted 行），据此重建 md blob 归档。blob 缺失时
    archive_document_to_ragplus 仅删主库 + 映射标 deleted（法规同款）。
    """
    stats: dict = {"document_id": str(document_id), "removed": 0}

    own_session = session is None
    if own_session:
        session = async_session_factory()
    try:
        doc = await session.get(MsdsDocument, document_id)
        if not doc:
            stats["error"] = f"MsdsDocument not found: {document_id}"
            return stats
        title = _article_title(doc)
        biz_key = _ragplus_biz_key(doc)
        blob = build_msds_full_text(doc).encode("utf-8") or None
    finally:
        if own_session:
            await session.close()

    from app.modules.safety.knowledge.ragplus_sync import (
        archive_document_to_ragplus,
    )

    async def _task() -> None:
        try:
            await archive_document_to_ragplus(
                domain="msds", biz_key=biz_key, title=title,
                file_name=f"{title}.md", blob=blob,
                content_type="text/markdown",
            )
        except Exception:
            logger.exception("MSDS ragplus 后台归档异常: %s", biz_key)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "无运行中的事件循环，MSDS ragplus 归档不调度: %s", biz_key,
        )
        stats["error"] = "no running event loop"
        return stats
    stats["task"] = loop.create_task(_task())
    stats["action"] = "scheduled_ragplus_archive"
    return stats


async def remove_msds_from_knowledge(
    document_id: uuid.UUID,
    session=None,
) -> dict:
    """移除 MSDS 台账对应的知识索引（幂等）。

    ragplus 开：后台归档——主库删文档 + md 全文移「已废止」库（对齐
    法规删除口径）。ragplus 关：本地旧管线——软删知识文章及其 chunks。
    """
    from app.modules.safety.knowledge.ragplus_client import ragplus_search_enabled

    if ragplus_search_enabled():
        return await _schedule_registry_ragplus_archive(document_id, session)

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
