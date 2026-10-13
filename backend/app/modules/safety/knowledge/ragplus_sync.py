"""ragplus-x 增量同步编排（事件驱动入库：上传/替换/归档 + 映射登记）。

供三处共用（一期壳换芯）：
- knowledge_bitable_handler：法规事件 create/update → 上传主库（替换旧文档）；
  delete → 主库删 + 移入已废止归档库（统一归档口径：被替代/废止均留档）。
- msds_collection_handler：供应商资料事件 → PDF 上传 MSDS 库。
- scripts/tmp/ragplus_bulk_ingest.py：存量批量入库（常量/映射 upsert 复用）。

全部为后台任务体内执行（调用方 asyncio.create_task），失败不抛出——
落 ragplus_doc_map status=failed + last_error，日志 ERROR，可由批量
脚本重跑兜底。总闸与检索同一开关（SAFETY_RAGPLUS_SEARCH_ENABLED）。
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.knowledge.ragplus_client import RagplusAdminClient

logger = logging.getLogger(__name__)

# ragplus 库名（一期三库；检索名单默认含前两个，归档库检索隔离）
KB_REGULATION = "安全法规标准"
KB_MSDS = "MSDS"
KB_ARCHIVE = "已废止"
TOKEN_NAME = "dazah-safety-service"

# 单文档增量解析轮询上限（秒）
_INGEST_POLL_DEADLINE = 600.0


def build_admin_client() -> RagplusAdminClient:
    """按 app_config + env 构建管理客户端（应急 admin 账密，env 可覆盖）。"""
    from app.modules.safety.app_config.store import store

    base = store.get_str("SAFETY_RAGPLUS_BASE_URL") or "http://localhost:8085"
    return RagplusAdminClient(
        base_url=base,
        username=os.getenv("RAGPLUS_ADMIN_USER", "admin"),
        password=os.getenv("RAGPLUS_ADMIN_PASSWORD", "admin123"),
    )


# ═══════════════════════════════════════════════════════════════
# 映射表
# ═══════════════════════════════════════════════════════════════


async def find_ragplus_map(
    session: AsyncSession,
    domain: str,
    biz_key: str,
) -> Any | None:
    from sqlalchemy import select

    from app.modules.safety.models import RagplusDocMap

    return (
        await session.execute(
            select(RagplusDocMap).where(
                RagplusDocMap.domain == domain,
                RagplusDocMap.biz_key == biz_key,
                RagplusDocMap.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()


async def upsert_ragplus_map(
    session: AsyncSession,
    *,
    domain: str,
    biz_key: str,
    dataset_name: str,
    status: str,
    kb_doc_id: int | None = None,
    engine_doc_id: str | None = None,
    dataset_id: str | None = None,
    title: str = "",
    file_name: str = "",
    last_error: str | None = None,
) -> None:
    """单行映射 upsert：新行入库或既有行按生命周期更新（version 随换档递增）。"""
    from app.modules.safety.models import RagplusDocMap

    title = (title or "").strip()
    file_name = (file_name or "").strip()
    row = await find_ragplus_map(session, domain, biz_key)
    if row is None:
        session.add(
            RagplusDocMap(
                domain=domain,
                biz_key=biz_key,
                dataset_name=dataset_name,
                kb_doc_id=kb_doc_id,
                engine_doc_id=engine_doc_id,
                dataset_id=dataset_id,
                title=title[:255],
                file_name=file_name[:512],
                status=status,
                last_error=last_error,
                synced_at=datetime.now(UTC) if status == "active" else None,
            )
        )
        return
    if kb_doc_id is not None and kb_doc_id != row.kb_doc_id:
        row.version = (row.version or 1) + 1
    row.dataset_name = dataset_name
    row.kb_doc_id = kb_doc_id or row.kb_doc_id
    row.engine_doc_id = engine_doc_id or row.engine_doc_id
    row.dataset_id = dataset_id or row.dataset_id
    row.title = title[:255] or row.title
    row.file_name = file_name[:512] or row.file_name
    row.status = status
    row.last_error = last_error
    if status == "active":
        row.synced_at = datetime.now(UTC)


# ═══════════════════════════════════════════════════════════════
# 同步动作（后台任务体）
# ═══════════════════════════════════════════════════════════════


async def upload_document_to_ragplus(
    *,
    domain: str,
    biz_key: str,
    title: str,
    file_name: str,
    blob: bytes,
    content_type: str = "application/pdf",
    kb_name: str = KB_REGULATION,
    admin: RagplusAdminClient | None = None,
    session: AsyncSession | None = None,
) -> bool:
    """上传文档到主库 + 解析 + 映射登记（成功 True/失败 False 并落 failed 映射）。

    replace 语义：映射已有 active 文档（附件换版）时，先删旧文档再传新，
    检索无旧版残留。admin/session 缺省自建自管（后台任务用），测试可注入。
    """
    from app.core.database import async_session_factory

    own_admin = admin is None
    admin = admin or build_admin_client()
    own_session = session is None
    sess: AsyncSession = session if session is not None else async_session_factory()
    try:
        kb = await admin.ensure_kb(kb_name)

        # 旧版替换：删主库旧文档（映射行当前 dataset_name 指向的库）
        row = await find_ragplus_map(sess, domain, biz_key)
        if row is not None and row.status == "active" and row.kb_doc_id:
            try:
                old_kb = next(
                    (
                        k
                        for k in await admin.list_kbs()
                        if k.get("name") == row.dataset_name
                    ),
                    None,
                )
                if old_kb and old_kb.get("id"):
                    await admin.delete_document(int(old_kb["id"]), int(row.kb_doc_id))
                    logger.info(
                        "ragplus 旧文档已删（换版）：%s/%s doc=%s",
                        domain,
                        biz_key,
                        row.kb_doc_id,
                    )
            except Exception as exc:
                logger.warning(
                    "ragplus 旧文档删除失败（继续传新）：%s/%s: %s",
                    domain,
                    biz_key,
                    exc,
                )

        doc = await admin.upload_document(kb["id"], file_name, blob, content_type)
        await admin.parse_documents(kb["id"], [doc["id"]], mode="parallel")
        results = await admin.wait_documents_ready(
            kb["id"],
            [doc["id"]],
            poll=4,
            deadline=_INGEST_POLL_DEADLINE,
        )
        r = results.get(doc["id"]) or {"status": "UNKNOWN", "fail_reason": "无解析结果"}
        parse_status = str(r.get("status") or "")
        ok = parse_status == "DONE"
        engine_doc_id = None
        try:
            for d in await admin.list_documents(kb["id"]):
                if d.get("id") == doc["id"] and d.get("engine_doc_id"):
                    engine_doc_id = str(d["engine_doc_id"])
                    break
        except Exception:
            pass
        await upsert_ragplus_map(
            sess,
            domain=domain,
            biz_key=biz_key,
            dataset_name=kb_name,
            status="active" if ok else "failed",
            kb_doc_id=doc["id"],
            engine_doc_id=engine_doc_id,
            dataset_id=str(kb.get("dataset_id") or "") or None,
            title=title,
            file_name=file_name,
            last_error=None if ok else str(r.get("fail_reason") or parse_status)[:500],
        )
        if own_session:
            await sess.commit()
        if ok:
            logger.info(
                "ragplus 增量入库完成：%s/%s → %s doc=%s",
                domain,
                biz_key,
                kb_name,
                doc["id"],
            )
        else:
            logger.error(
                "ragplus 增量解析失败：%s/%s doc=%s reason=%s",
                domain,
                biz_key,
                doc["id"],
                r.get("fail_reason"),
            )
        return ok
    except Exception as exc:
        logger.exception("ragplus 增量入库异常：%s/%s", domain, biz_key)
        try:
            await upsert_ragplus_map(
                sess,
                domain=domain,
                biz_key=biz_key,
                dataset_name=kb_name,
                status="failed",
                title=title,
                file_name=file_name,
                last_error=str(exc)[:500],
            )
            if own_session:
                await sess.commit()
        except Exception:
            logger.exception("ragplus 失败映射登记异常：%s/%s", domain, biz_key)
        return False
    finally:
        if own_admin:
            await admin.aclose()
        if own_session:
            await sess.close()


async def archive_document_to_ragplus(
    *,
    domain: str,
    biz_key: str,
    title: str,
    file_name: str,
    blob: bytes | None = None,
    content_type: str = "application/pdf",
    admin: RagplusAdminClient | None = None,
    session: AsyncSession | None = None,
) -> bool:
    """delete 事件：主库删文档 + PDF 移入已废止归档库 + 映射 archived。

    统一归档口径：被替代（爬虫删旧写新）与人工废止事件层不可区分，
    均归档留档。归档库不在检索名单内，不触发解析（溯源回放用原文）。
    blob 为空（附件缺失/下载失败）时仅删主库文档并标记映射 deleted。
    """
    from app.core.database import async_session_factory

    own_admin = admin is None
    admin = admin or build_admin_client()
    own_session = session is None
    sess: AsyncSession = session if session is not None else async_session_factory()
    try:
        row = await find_ragplus_map(sess, domain, biz_key)
        kbs = {kb.get("name"): kb for kb in await admin.list_kbs()}

        # 1. 主库删文档
        if row is not None and row.kb_doc_id:
            main_kb = kbs.get(row.dataset_name)
            if main_kb and main_kb.get("id"):
                try:
                    await admin.delete_document(int(main_kb["id"]), int(row.kb_doc_id))
                    logger.info(
                        "ragplus 主库文档已删：%s/%s %s doc=%s",
                        domain,
                        biz_key,
                        row.dataset_name,
                        row.kb_doc_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "ragplus 主库删除失败（继续归档）：%s/%s: %s",
                        domain,
                        biz_key,
                        exc,
                    )

        # 2. PDF 移入归档库（有 blob 才归档；不解析）
        archive_doc_id: int | None = None
        if blob:
            archive_kb = await admin.ensure_kb(KB_ARCHIVE)
            try:
                doc = await admin.upload_document(
                    int(archive_kb["id"]),
                    file_name,
                    blob,
                    content_type,
                )
                archive_doc_id = doc["id"]
            except Exception as exc:
                logger.error("ragplus 归档上传失败：%s/%s: %s", domain, biz_key, exc)

        # 3. 映射登记
        await upsert_ragplus_map(
            sess,
            domain=domain,
            biz_key=biz_key,
            dataset_name=KB_ARCHIVE
            if archive_doc_id
            else (row.dataset_name if row else KB_ARCHIVE),
            status="archived" if archive_doc_id else "deleted",
            kb_doc_id=archive_doc_id,
            title=title or (row.title if row else ""),
            file_name=file_name or (row.file_name if row else ""),
        )
        if own_session:
            await sess.commit()
        logger.info(
            "ragplus 归档完成：%s/%s → %s",
            domain,
            biz_key,
            KB_ARCHIVE if archive_doc_id else "deleted",
        )
        return True
    except Exception as exc:
        logger.exception("ragplus 归档异常：%s/%s", domain, biz_key)
        try:
            await upsert_ragplus_map(
                sess,
                domain=domain,
                biz_key=biz_key,
                dataset_name=KB_ARCHIVE,
                status="failed",
                title=title,
                file_name=file_name,
                last_error=str(exc)[:500],
            )
            if own_session:
                await sess.commit()
        except Exception:
            logger.exception("ragplus 归档失败映射登记异常：%s/%s", domain, biz_key)
        return False
    finally:
        if own_admin:
            await admin.aclose()
        if own_session:
            await sess.close()


# ═══════════════════════════════════════════════════════════════
# 调度助手（事件 handler 侧）
# ═══════════════════════════════════════════════════════════════


def _log_task_exception(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("ragplus 后台同步任务异常：%s", exc)


def schedule_upload_from_attachment(
    *,
    domain: str,
    biz_key: str,
    title: str,
    stored_path: str | None,
    file_name: str | None,
    content_type: str = "application/pdf",
    kb_name: str = KB_REGULATION,
) -> asyncio.Task | None:  # type: ignore[type-arg]
    """从统一存储（本地/MinIO）物化附件字节，后台上传 ragplus 主库。

    事件回调内调用（须在运行中的事件循环）；返回创建的任务（测试可等待），
    无循环/无附件返回 None。附件换版由 upload 的 replace 语义处理。
    """
    if not stored_path:
        return None

    async def _task() -> None:
        from app.modules.safety.attachment_store import materialize

        suffix = Path(file_name or "").suffix or ".pdf"
        local = materialize(stored_path, suffix=suffix)
        if local is None or not Path(local).exists() or Path(local).stat().st_size == 0:
            logger.error(
                "ragplus 增量上传附件不可读：%s/%s path=%s",
                domain,
                biz_key,
                stored_path,
            )
            return
        blob = Path(local).read_bytes()
        if str(local) != stored_path:
            Path(local).unlink(missing_ok=True)  # MinIO 临时物化文件清理
        await upload_document_to_ragplus(
            domain=domain,
            biz_key=biz_key,
            title=title or file_name or biz_key,
            file_name=file_name or Path(stored_path).name,
            blob=blob,
            content_type=content_type,
            kb_name=kb_name,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("无运行中的事件循环，ragplus 上传不调度：%s/%s", domain, biz_key)
        return None
    task = loop.create_task(_task())
    task.add_done_callback(_log_task_exception)
    return task


def schedule_archive_from_attachment(
    *,
    domain: str,
    biz_key: str,
    title: str,
    stored_path: str | None,
    file_name: str | None,
    content_type: str = "application/pdf",
) -> asyncio.Task | None:  # type: ignore[type-arg]
    """delete 事件后归档：物化附件字节 → 主库删 + 移入已废止库。"""

    async def _task() -> None:
        from app.modules.safety.attachment_store import materialize

        blob: bytes | None = None
        if stored_path:
            suffix = Path(file_name or "").suffix or ".pdf"
            local = materialize(stored_path, suffix=suffix)
            if (
                local is not None
                and Path(local).exists()
                and Path(local).stat().st_size > 0
            ):
                blob = Path(local).read_bytes()
                if str(local) != stored_path:
                    Path(local).unlink(missing_ok=True)
        await archive_document_to_ragplus(
            domain=domain,
            biz_key=biz_key,
            title=title or file_name or biz_key,
            file_name=file_name or (Path(stored_path).name if stored_path else biz_key),
            blob=blob,
            content_type=content_type,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("无运行中的事件循环，ragplus 归档不调度：%s/%s", domain, biz_key)
        return None
    task = loop.create_task(_task())
    task.add_done_callback(_log_task_exception)
    return task
