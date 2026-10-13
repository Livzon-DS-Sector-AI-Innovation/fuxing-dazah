"""ragplus 增量入库单测 — 接缝：ragplus_sync 公开动作 + 各挂点开关短路。

只测外部行为：上传/归档对映射表与 ragplus 管理端的效果；开关开时本地
切片向量化/图谱重建/msds_indexer 短路；开关关时调度函数不触发上传。
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.modules.safety.feishu import (
    knowledge_bitable_handler as kb_handler,
)
from app.modules.safety.feishu import msds_collection_handler as msds_handler
from app.modules.safety.knowledge import ragplus_sync
from app.modules.safety.knowledge.msds_indexer import (
    sync_msds_document_to_knowledge,
)
from app.modules.safety.models import RagplusDocMap

_SWITCH = "SAFETY_RAGPLUS_SEARCH_ENABLED"


@pytest.fixture(autouse=True)
def _switch_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(_SWITCH, raising=False)
    yield


def _fake_admin() -> MagicMock:
    admin = MagicMock()
    admin.ensure_kb = AsyncMock(
        side_effect=lambda name, desc="": {
            "id": 8 if name == ragplus_sync.KB_ARCHIVE else 7,
            "name": name,
            "dataset_id": "ds-x",
        }
    )
    admin.list_kbs = AsyncMock(
        return_value=[
            {"id": 7, "name": ragplus_sync.KB_REGULATION, "dataset_id": "ds-law"},
            {"id": 8, "name": ragplus_sync.KB_ARCHIVE, "dataset_id": "ds-arch"},
        ]
    )
    admin.upload_document = AsyncMock(
        return_value={"id": 11, "name": "a.pdf", "status": "UNSTART"}
    )
    admin.parse_documents = AsyncMock(return_value=None)
    admin.wait_documents_ready = AsyncMock(
        return_value={
            11: {"status": "DONE", "fail_reason": None, "chunk_count": 3},
        }
    )
    admin.list_documents = AsyncMock(
        return_value=[
            {"id": 11, "name": "a.pdf", "engine_doc_id": "eng-11", "status": "DONE"},
        ]
    )
    admin.delete_document = AsyncMock(return_value=None)
    return admin


async def _get_map(db_session, domain: str, biz_key: str) -> RagplusDocMap | None:
    return (
        await db_session.execute(
            select(RagplusDocMap).where(
                RagplusDocMap.domain == domain,
                RagplusDocMap.biz_key == biz_key,
            )
        )
    ).scalar_one_or_none()


class TestUploadDocument:
    async def test_upload_registers_active_map(self, db_session) -> None:
        admin = _fake_admin()
        ok = await ragplus_sync.upload_document_to_ragplus(
            domain="regulation",
            biz_key="rec-new",
            title="GB 30871",
            file_name="gb30871.pdf",
            blob=b"%PDF-1",
            admin=admin,
            session=db_session,
        )
        assert ok is True
        admin.upload_document.assert_awaited_once()
        admin.parse_documents.assert_awaited_once_with(7, [11], mode="parallel")

        row = await _get_map(db_session, "regulation", "rec-new")
        assert row is not None and row.status == "active"
        assert row.kb_doc_id == 11
        assert row.engine_doc_id == "eng-11"
        assert row.dataset_name == ragplus_sync.KB_REGULATION

    async def test_upload_replaces_old_document(self, db_session) -> None:
        db_session.add(
            RagplusDocMap(
                domain="regulation",
                biz_key="rec-v1",
                dataset_name=ragplus_sync.KB_REGULATION,
                kb_doc_id=99,
                status="active",
                title="旧版",
            )
        )
        await db_session.flush()

        admin = _fake_admin()
        ok = await ragplus_sync.upload_document_to_ragplus(
            domain="regulation",
            biz_key="rec-v1",
            title="新版",
            file_name="v2.pdf",
            blob=b"%PDF-2",
            admin=admin,
            session=db_session,
        )
        assert ok is True
        # 旧文档从主库删除（换版无残留）
        admin.delete_document.assert_awaited_once_with(7, 99)

        row = await _get_map(db_session, "regulation", "rec-v1")
        assert row.kb_doc_id == 11
        assert row.version == 2  # 换档递增

    async def test_upload_parse_failure_marks_failed(self, db_session) -> None:
        admin = _fake_admin()
        admin.wait_documents_ready = AsyncMock(
            return_value={
                11: {"status": "FAIL", "fail_reason": "解析超时", "chunk_count": 0},
            }
        )
        ok = await ragplus_sync.upload_document_to_ragplus(
            domain="msds",
            biz_key="msds-1",
            title="MSDS-x",
            file_name="x.pdf",
            blob=b"%PDF",
            admin=admin,
            session=db_session,
            kb_name=ragplus_sync.KB_MSDS,
        )
        assert ok is False
        row = await _get_map(db_session, "msds", "msds-1")
        assert row.status == "failed"
        assert "解析超时" in (row.last_error or "")


class TestArchiveDocument:
    async def test_archive_deletes_main_and_uploads_archive(self, db_session) -> None:
        db_session.add(
            RagplusDocMap(
                domain="regulation",
                biz_key="rec-del",
                dataset_name=ragplus_sync.KB_REGULATION,
                kb_doc_id=99,
                status="active",
                title="废止法规",
                file_name="old.pdf",
            )
        )
        await db_session.flush()

        admin = _fake_admin()
        ok = await ragplus_sync.archive_document_to_ragplus(
            domain="regulation",
            biz_key="rec-del",
            title="废止法规",
            file_name="old.pdf",
            blob=b"%PDF-old",
            admin=admin,
            session=db_session,
        )
        assert ok is True
        admin.delete_document.assert_awaited_once_with(7, 99)  # 主库删除
        admin.upload_document.assert_awaited_once()  # 归档库上传

        row = await _get_map(db_session, "regulation", "rec-del")
        assert row.status == "archived"
        assert row.dataset_name == ragplus_sync.KB_ARCHIVE
        assert row.kb_doc_id == 11

    async def test_archive_without_blob_marks_deleted(self, db_session) -> None:
        db_session.add(
            RagplusDocMap(
                domain="regulation",
                biz_key="rec-nofile",
                dataset_name=ragplus_sync.KB_REGULATION,
                kb_doc_id=98,
                status="active",
            )
        )
        await db_session.flush()

        admin = _fake_admin()
        ok = await ragplus_sync.archive_document_to_ragplus(
            domain="regulation",
            biz_key="rec-nofile",
            title="无附件",
            file_name="",
            blob=None,
            admin=admin,
            session=db_session,
        )
        assert ok is True
        admin.upload_document.assert_not_awaited()
        row = await _get_map(db_session, "regulation", "rec-nofile")
        assert row.status == "deleted"


class TestScheduleFromAttachment:
    async def test_schedule_upload_reads_blob_and_uploads(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-blob")

        uploaded = AsyncMock(return_value=True)
        monkeypatch.setattr(ragplus_sync, "upload_document_to_ragplus", uploaded)

        task = ragplus_sync.schedule_upload_from_attachment(
            domain="regulation",
            biz_key="rec-x",
            title="标题",
            stored_path=str(pdf),
            file_name="doc.pdf",
        )
        assert task is not None
        await task

        uploaded.assert_awaited_once()
        kwargs = uploaded.await_args.kwargs
        assert kwargs["blob"] == b"%PDF-blob"
        assert kwargs["biz_key"] == "rec-x"
        assert kwargs["domain"] == "regulation"

    async def test_schedule_archive_moves_to_archive_kb(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        pdf = tmp_path / "old.pdf"
        pdf.write_bytes(b"%PDF-old")

        archived = AsyncMock(return_value=True)
        monkeypatch.setattr(ragplus_sync, "archive_document_to_ragplus", archived)

        task = ragplus_sync.schedule_archive_from_attachment(
            domain="regulation",
            biz_key="rec-y",
            title="旧法",
            stored_path=str(pdf),
            file_name="old.pdf",
        )
        assert task is not None
        await task

        archived.assert_awaited_once()
        assert archived.await_args.kwargs["blob"] == b"%PDF-old"


class TestIngestShortCircuits:
    async def test_msds_indexer_short_circuits_when_enabled(self, monkeypatch) -> None:
        """开关开：msds_indexer 入口直接短路，不触达 chunk 重建。"""
        monkeypatch.setenv(_SWITCH, "true")
        from app.modules.safety.knowledge import chunk_service

        def _fail(*a, **kw):  # noqa: ANN001
            raise AssertionError("开关开时不应执行本地 chunk 重建")

        monkeypatch.setattr(chunk_service, "rebuild_article_chunks", _fail)

        stats = await sync_msds_document_to_knowledge(uuid.uuid4())
        assert stats["action"] == "skipped_ragplus"

    async def test_msds_indexer_runs_when_disabled(self, monkeypatch) -> None:
        """开关关：走旧路径（document 不存在 → 记 error 返回，不异常）。"""
        stats = await sync_msds_document_to_knowledge(uuid.uuid4())
        assert stats["action"] in ("skipped", "created", "updated")
        assert stats["error"]  # 本地库无此 msds_documents 行 → not found

    async def test_graph_rebuild_short_circuits_when_enabled(self, monkeypatch) -> None:
        """开关开：图谱重建短路（redis 防抖都不碰）。"""
        monkeypatch.setenv(_SWITCH, "true")
        redis_set = AsyncMock(return_value=True)
        monkeypatch.setattr(kb_handler, "redis_client", MagicMock(set=redis_set))

        await kb_handler._schedule_graph_rebuild()
        redis_set.assert_not_awaited()

    async def test_graph_rebuild_schedules_when_disabled(self, monkeypatch) -> None:
        """开关关：防抖闸门照常（redis set 被调用并创建重建任务）。"""
        created: list = []
        monkeypatch.setattr(
            asyncio,
            "create_task",
            lambda coro: created.append(coro) or coro.close(),
        )
        redis_set = AsyncMock(return_value=True)
        monkeypatch.setattr(kb_handler, "redis_client", MagicMock(set=redis_set))

        await kb_handler._schedule_graph_rebuild()
        redis_set.assert_awaited_once()
        assert len(created) == 1


class TestMsdsCollectionHook:
    async def test_collection_upload_task_invoked_when_enabled(
        self,
        monkeypatch,
    ) -> None:
        """开关开：供应商资料事件构造的后台任务下载附件并上传 MSDS 库。"""
        monkeypatch.setenv(_SWITCH, "true")

        uploaded = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "app.modules.safety.knowledge.ragplus_sync.upload_document_to_ragplus",
            uploaded,
        )
        client = MagicMock()
        client.download_attachment = AsyncMock(return_value=b"%PDF-msds")
        monkeypatch.setattr(
            msds_handler,
            "SafetyBitableClient",
            MagicMock(return_value=client),
        )

        pg_id = uuid.uuid4()
        task = msds_handler._schedule_ragplus_upload(
            pg_id,
            [{"file_token": "ft-1", "name": "供应商A.pdf", "type": "application/pdf"}],
        )
        assert task is not None
        await task

        client.download_attachment.assert_awaited_once_with("ft-1")
        uploaded.assert_awaited_once()
        kwargs = uploaded.await_args.kwargs
        assert kwargs["domain"] == "msds"
        assert kwargs["biz_key"] == str(pg_id)
        assert kwargs["kb_name"] == ragplus_sync.KB_MSDS

    async def test_collection_upload_skipped_when_disabled(self, monkeypatch) -> None:
        """开关关：不调度任何上传。"""
        uploaded = AsyncMock(return_value=True)
        monkeypatch.setattr(
            "app.modules.safety.knowledge.ragplus_sync.upload_document_to_ragplus",
            uploaded,
        )
        assert (
            msds_handler._schedule_ragplus_upload(
                uuid.uuid4(),
                [{"file_token": "ft-1", "name": "a.pdf"}],
            )
            is None
        )
        uploaded.assert_not_awaited()
