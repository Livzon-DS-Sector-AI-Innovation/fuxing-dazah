"""QA 知识库 HTTP 全链路回归：主数据 → 文件类型 → 文件 → 版本 → 关联/设当前/启停 →
内容/处理结果 → AI 提案 → 检索/审计。

qa 模块拆成子包后，大部分端点只在这里被真正打到一次；文件存储打到内存，
整条用例在一个最终回滚的会话里完成，不留数据库和磁盘残留。
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.main import app as fastapi_app
from app.modules.qa import file_service
from app.modules.qa.permissions import PERMISSIONS
from app.platform.identity.deps import get_current_user
from app.platform.identity.models import User
from tests.conftest import _test_session_factory

BASE = "/api/v1/qa"
PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


async def _ensure_test_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.is_deleted == False).limit(1)  # noqa: E712
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing:
        return existing
    user = User(name="qa流程测试用户", employee_no="QA-FLOW-TEST-001")
    session.add(user)
    await session.flush()
    return user


class _MemoryStorage:
    """替换 file_service 的落盘/MinIO 调用，保持 StoredFile 契约。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def store_file(
        self, filename: str | None, content_type: str | None, data: bytes
    ) -> file_service.StoredFile:
        safe_name, extension, mime = file_service.validate_file(
            filename, content_type, data
        )
        key = f"documents/{uuid.uuid4().hex}.{extension}"
        self.objects[key] = data
        return file_service.StoredFile(
            key, safe_name, extension, mime, len(data), hashlib.sha256(data).hexdigest()
        )

    def read_file(self, key: str) -> tuple[bytes, str] | None:
        return (self.objects[key], "application/pdf") if key in self.objects else None

    def delete_file(self, key: str) -> None:
        self.objects.pop(key, None)


@asynccontextmanager
async def _client() -> AsyncGenerator[tuple[AsyncClient, _MemoryStorage], None]:
    storage = _MemoryStorage()
    async with _test_session_factory() as session:
        user = await _ensure_test_user(session)

        async def _override_get_db() -> Any:
            yield session

        async def _override_user() -> Any:
            return user

        async def _all_qa_perms(user_id: str, db: object) -> set[str]:
            return {perm.code for perm in PERMISSIONS}

        fastapi_app.dependency_overrides[get_db] = _override_get_db
        fastapi_app.dependency_overrides[get_current_user] = _override_user
        try:
            with (
                patch(
                    "app.platform.permission.deps.get_user_permissions",
                    new=_all_qa_perms,
                ),
                patch.object(file_service, "store_file", storage.store_file),
                patch.object(file_service, "read_file", storage.read_file),
                patch.object(file_service, "delete_file", storage.delete_file),
                patch.object(file_service, "cleanup_stored_file", storage.delete_file),
            ):
                transport = ASGITransport(app=fastapi_app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    yield ac, storage
        finally:
            fastapi_app.dependency_overrides.clear()
            await session.rollback()


def _data(resp: Any, *, expect: int = 200) -> Any:
    assert resp.status_code == expect, (
        f"{resp.request.method} {resp.request.url.path} -> {resp.status_code} {resp.text[:300]}"
    )
    return resp.json()["data"]


async def test_qa_knowledge_base_full_flow() -> None:
    """知识库正向全链路：主数据→类型→台账→版本→设当前→内容/解析→AI→检索/审计。

    覆盖登记员的一天：建主数据挂别名、建类型建台账、逐版上传并
    切换现行版本、复制上一版关联、预览/下载受控文件、触发 AI 分析
    （未解析时被守卫拦截）、最后全局检索并核对审计可见。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, storage):
        assert (await ac.get(f"{BASE}/")).status_code == 200

        # ── 主数据 ──
        master = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "SUPPLIER",
                    "code": f"SUP-{tag}",
                    "name": f"供应商{tag}",
                    "aliases": ["别名A"],
                },
            )
        )
        master_id = master["id"]
        assert master["code"] == f"SUP-{tag}"
        _data(await ac.get(f"{BASE}/master-objects/{master_id}"))
        _data(
            await ac.put(
                f"{BASE}/master-objects/{master_id}", json={"name": f"供应商{tag}改"}
            )
        )
        _data(
            await ac.put(
                f"{BASE}/master-objects/{master_id}/aliases",
                json={"aliases": ["别名B", "别名C"]},
            )
        )
        _data(
            await ac.post(
                f"{BASE}/master-objects/{master_id}/aliases",
                json={"aliases": ["别名D"]},
            )
        )
        _data(await ac.post(f"{BASE}/master-objects/{master_id}/deactivate"))
        _data(await ac.post(f"{BASE}/master-objects/{master_id}/activate"))
        _data(
            await ac.post(
                f"{BASE}/master-objects/{master_id}/status", json={"status": "active"}
            )
        )
        listed = _data(await ac.get(f"{BASE}/master-objects", params={"keyword": tag}))
        assert any(row["id"] == master_id for row in listed)
        _data(await ac.get(f"{BASE}/references/departments"))
        _data(
            await ac.get(
                f"{BASE}/references/sources/EQUIPMENT", params={"page_size": 5}
            )
        )

        # ── 文件类型 ──
        doc_type = _data(
            await ac.post(
                f"{BASE}/document-types",
                json={"code": f"SOP-{tag}", "name": f"类型{tag}"},
            )
        )
        type_id = doc_type["id"]
        _data(
            await ac.put(f"{BASE}/document-types/{type_id}", json={"description": "x"})
        )
        _data(await ac.post(f"{BASE}/document-types/{type_id}/deactivate"))
        _data(await ac.post(f"{BASE}/document-types/{type_id}/activate"))
        _data(await ac.get(f"{BASE}/document-types"))

        # ── 文件台账 ──
        document = _data(
            await ac.post(
                f"{BASE}/documents",
                json={
                    "document_no": f"SOP.99.{tag}",
                    "title": f"文件{tag}",
                    "document_type_id": type_id,
                },
            )
        )
        document_id = document["id"]
        _data(await ac.get(f"{BASE}/documents/{document_id}"))
        _data(
            await ac.put(
                f"{BASE}/documents/{document_id}", json={"title": f"文件{tag}改"}
            )
        )
        assert any(
            row["id"] == document_id
            for row in _data(await ac.get(f"{BASE}/documents", params={"keyword": tag}))
        )
        _data(
            await ac.get(
                f"{BASE}/documents",
                params={
                    "sort_by": "title",
                    "document_type_id": type_id,
                    "include_inactive": True,
                },
            )
        )

        # ── 版本 / 关联 / 当前版本 ──
        v1 = _data(
            await ac.post(
                f"{BASE}/documents/{document_id}/versions",
                data={"version_label": "V1", "approved_declared": "true"},
                files={"file": ("核查.pdf", PDF_BYTES, "application/pdf")},
            )
        )
        assert len(storage.objects) == 1
        versions = _data(await ac.get(f"{BASE}/documents/{document_id}/versions"))
        assert [v["id"] for v in versions] == [v1["id"]]
        relations = _data(
            await ac.put(
                f"{BASE}/document-versions/{v1['id']}/relations",
                json={"master_object_ids": [master_id]},
            )
        )
        assert [r["master_object_id"] for r in relations] == [master_id]
        _data(
            await ac.post(
                f"{BASE}/documents/{document_id}/versions/{v1['id']}/make-current"
            )
        )
        assert (
            _data(await ac.get(f"{BASE}/documents/{document_id}"))["current_version_id"]
            == v1["id"]
        )

        v2 = _data(
            await ac.post(
                f"{BASE}/documents/{document_id}/versions",
                data={"version_label": "V2", "approved_declared": "true"},
                files={"file": ("核查2.pdf", PDF_BYTES, "application/pdf")},
            )
        )
        copied = _data(
            await ac.post(
                f"{BASE}/documents/{document_id}/versions/{v2['id']}/copy-relations"
            )
        )
        assert [r["master_object_id"] for r in copied] == [master_id]
        _data(
            await ac.post(
                f"{BASE}/documents/{document_id}/versions/{v2['id']}/make-current"
            )
        )
        _data(await ac.post(f"{BASE}/document-versions/{v1['id']}/deactivate"))
        _data(await ac.post(f"{BASE}/document-versions/{v1['id']}/activate"))
        _data(await ac.post(f"{BASE}/documents/{document_id}/deactivate"))
        _data(await ac.post(f"{BASE}/documents/{document_id}/activate"))

        # ── 文件内容与处理结果 ──
        file_id = v2["file"]["id"]
        content = await ac.get(f"{BASE}/document-files/{file_id}/content")
        assert content.status_code == 200 and content.content == PDF_BYTES
        assert "inline" in content.headers["content-disposition"]
        download = await ac.get(
            f"{BASE}/document-files/{file_id}/content", params={"download": True}
        )
        assert "attachment" in download.headers["content-disposition"]
        _data(await ac.get(f"{BASE}/document-files/{file_id}/processing-results"))
        _data(
            await ac.get(
                f"{BASE}/document-files/{file_id}/processing-results",
                params={"view": "chunks"},
            )
        )
        _data(await ac.get(f"{BASE}/document-files/{file_id}/artifacts"))
        assert (
            await ac.post(f"{BASE}/document-files/{file_id}/retry")
        ).status_code in (200, 409, 422)

        # ── AI / 提案：正文尚未解析时触发分析应被既有守卫拦下 ──
        blocked = await ac.post(
            f"{BASE}/document-versions/{v2['id']}/ai-analysis", json={}
        )
        assert blocked.status_code == 409 and "解析" in blocked.text
        assert (
            await ac.get(f"{BASE}/document-versions/{v2['id']}/ai-analysis/latest")
        ).status_code == 404
        _data(await ac.get(f"{BASE}/master-object-proposals"))
        _data(await ac.post(f"{BASE}/master-object-proposals/reject-all"))

        # ── 检索 / 审计 ──
        hits = _data(await ac.get(f"{BASE}/search", params={"q": tag}))
        assert any(hit.get("id") in {master_id, document_id} for hit in hits)
        _data(await ac.get(f"{BASE}/audit-logs", params={"page_size": 5}))
