"""QA 知识库业务规则 API 测试：唯一性、启停守卫、版本纪律、检索可见性、审计留痕。

与 test_api_flow 的正向全链路互补，这里从业务约束角度打真实 HTTP 端点：
同类型编码/文件编号/版本标签不可重复，停用对象挡住后续业务动作，
受控文件的预览下载必须留审计痕迹。文件存储打到内存，整条用例在
一个最终回滚的会话里完成；需要外部模块前置数据（如产品来源）时
直接在会话内造 ORM 行作为业务前置条件。
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
from app.modules.production.models import Product
from app.modules.qa import file_service
from app.modules.qa.models import (
    DocumentAIAnalysisRun,
    DocumentEntityObservation,
    DocumentExtractionArtifact,
    DocumentFile,
    DocumentRelationSuggestion,
    MasterObjectProposal,
)
from app.modules.qa.permissions import PERMISSIONS
from app.modules.qa.service import ai_analysis as ai_analysis_service
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
    user = User(name="qa规则测试用户", employee_no="QA-RULE-TEST-001")
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

    def read_object(self, key: str) -> tuple[bytes, str] | None:
        return (self.objects[key], "application/octet-stream") if key in self.objects else None

    def delete_file(self, key: str) -> None:
        self.objects.pop(key, None)


@asynccontextmanager
async def _client() -> AsyncGenerator[tuple[AsyncClient, AsyncSession, _MemoryStorage], None]:
    """全权限客户端 + 同一事务会话：用例内的 ORM 行对端点可见，结束统一回滚。"""
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
                # ai_analysis 以 from-import 方式持有权限函数引用，需单独打补丁
                patch(
                    "app.modules.qa.service.ai_analysis.get_user_permissions",
                    new=_all_qa_perms,
                ),
                patch.object(file_service, "store_file", storage.store_file),
                patch.object(file_service, "read_file", storage.read_file),
                patch.object(file_service, "read_object", storage.read_object),
                patch.object(file_service, "delete_file", storage.delete_file),
                patch.object(file_service, "cleanup_stored_file", storage.delete_file),
            ):
                transport = ASGITransport(app=fastapi_app)
                async with AsyncClient(
                    transport=transport, base_url="http://test"
                ) as ac:
                    yield ac, session, storage
        finally:
            fastapi_app.dependency_overrides.clear()
            await session.rollback()


def _data(resp: Any, *, expect: int = 200) -> Any:
    assert resp.status_code == expect, (
        f"{resp.request.method} {resp.request.url.path} -> {resp.status_code} {resp.text[:300]}"
    )
    return resp.json()["data"]


async def _make_type(ac: AsyncClient, tag: str) -> str:
    """造一个启用的文件类型，返回 type_id。"""
    doc_type = _data(
        await ac.post(
            f"{BASE}/document-types", json={"code": f"DT-{tag}", "name": f"类型{tag}"}
        )
    )
    return str(doc_type["id"])


async def _make_document(ac: AsyncClient, type_id: str, document_no: str) -> str:
    """造一条启用的文件台账，返回 document_id。"""
    document = _data(
        await ac.post(
            f"{BASE}/documents",
            json={
                "document_no": document_no,
                "title": f"文件{document_no}",
                "document_type_id": type_id,
            },
        )
    )
    return str(document["id"])


async def _make_type_and_document(ac: AsyncClient, tag: str) -> tuple[str, str]:
    """造一对启用的文件类型 + 台账，返回 (type_id, document_id)。"""
    type_id = await _make_type(ac, tag)
    return type_id, await _make_document(ac, type_id, f"SOP.{tag}")


async def _upload_version(
    ac: AsyncClient, document_id: str, label: str, *, approved: bool = True
) -> Any:
    return await ac.post(
        f"{BASE}/documents/{document_id}/versions",
        data={"version_label": label, "approved_declared": "true" if approved else "false"},
        files={"file": (f"{label}.pdf", PDF_BYTES, "application/pdf")},
    )


# ───────────────────────── 主数据 ─────────────────────────


async def test_master_code_unique_within_type_and_alias_unique_within_object() -> None:
    """主数据编码按类型唯一，别名在同一主数据内唯一。

    编码是检索和 AI 对齐的主键口径，同类型撞码会把两份档案混在一起；
    别名重复则会让检索命中成倍膨胀。不同类型之间允许各自编号体系
    复用同一串编码。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        first = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "SUPPLIER",
                    "code": f"SUP-{tag}",
                    "name": f"供应商{tag}",
                },
            )
        )
        duplicate = await ac.post(
            f"{BASE}/master-objects",
            json={
                "object_type": "SUPPLIER",
                "code": f"sup-{tag}",  # 大小写不同仍视为同一编码
                "name": f"供应商重复{tag}",
            },
        )
        assert duplicate.status_code == 409

        other_type = await ac.post(
            f"{BASE}/master-objects",
            json={
                "object_type": "MATERIAL",
                "code": f"SUP-{tag}",
                "name": f"物料复用编码{tag}",
            },
        )
        assert other_type.status_code == 200

        _data(
            await ac.post(
                f"{BASE}/master-objects/{first['id']}/aliases",
                json={"aliases": [f"俗称{tag}"]},
            )
        )
        repeated_alias = await ac.post(
            f"{BASE}/master-objects/{first['id']}/aliases",
            json={"aliases": [f"俗称{tag}"]},
        )
        assert repeated_alias.status_code == 409


async def test_master_sources_snapshot_external_object_and_replace() -> None:
    """主数据可挂外部来源关联：登记时保存快照，替换语义换掉整组。

    来源实体必须与主数据类型匹配（产品档案挂产品、物料档案挂中间体），
    防止跨域引用串档；快照保证外部系统改码/改名后 QA 侧展示仍可读；
    关联不存在的来源必须被拒，防止把脏引用写进档案。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, session, _storage):
        product = Product(
            product_code=f"PRD-{tag}", product_name=f"来源产品{tag}", unit="kg"
        )
        second = Product(
            product_code=f"PRD2-{tag}", product_name=f"替换产品{tag}", unit="kg"
        )
        session.add_all([product, second])
        await session.flush()

        master = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "PRODUCT",
                    "code": f"PRD-M-{tag}",
                    "name": f"产品主数据{tag}",
                },
            )
        )
        linked = _data(
            await ac.post(
                f"{BASE}/master-objects/{master['id']}/sources",
                json={
                    "sources": [
                        {
                            "source_module": "production",
                            "source_entity": "product",
                            "source_id": str(product.id),
                        }
                    ]
                },
            )
        )
        assert [row["source_code_snapshot"] for row in linked] == [f"PRD-{tag}"]
        assert [row["source_name_snapshot"] for row in linked] == [f"来源产品{tag}"]

        replaced = _data(
            await ac.put(
                f"{BASE}/master-objects/{master['id']}/sources",
                json={
                    "sources": [
                        {
                            "source_module": "production",
                            "source_entity": "product",
                            "source_id": str(second.id),
                        }
                    ]
                },
            )
        )
        assert [row["source_code_snapshot"] for row in replaced] == [f"PRD2-{tag}"]
        detail = _data(await ac.get(f"{BASE}/master-objects/{master['id']}"))
        assert [row["source_id"] for row in detail["sources"]] == [str(second.id)]

        missing = await ac.post(
            f"{BASE}/master-objects/{master['id']}/sources",
            json={
                "sources": [
                    {
                        "source_module": "production",
                        "source_entity": "product",
                        "source_id": str(uuid.uuid4()),
                    }
                ]
            },
        )
        assert missing.status_code == 422

        material = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "MATERIAL",
                    "code": f"MAT-{tag}",
                    "name": f"物料{tag}",
                },
            )
        )
        mismatched = await ac.post(
            f"{BASE}/master-objects/{material['id']}/sources",
            json={
                "sources": [
                    {
                        "source_module": "production",
                        "source_entity": "product",
                        "source_id": str(product.id),
                    }
                ]
            },
        )
        assert mismatched.status_code == 422


async def test_master_list_defaults_to_active_and_supports_filters() -> None:
    """主数据台账默认只展示启用行，支持类型过滤、状态过滤与分页。

    台账是登记入口的候选集：停用档案不该再出现在默认列表里干扰
    选择，但仍可通过 include_inactive 追溯历史。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        kept = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "SUPPLIER",
                    "code": f"SUP-{tag}A",
                    "name": f"启用供应商{tag}",
                },
            )
        )
        stopped = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "SUPPLIER",
                    "code": f"SUP-{tag}B",
                    "name": f"停用供应商{tag}",
                },
            )
        )
        material = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "MATERIAL",
                    "code": f"MAT-{tag}C",
                    "name": f"物料{tag}",
                },
            )
        )
        _data(await ac.post(f"{BASE}/master-objects/{stopped['id']}/deactivate"))

        active_suppliers = _data(
            await ac.get(
                f"{BASE}/master-objects", params={"kind": "supplier", "keyword": tag}
            )
        )
        assert [row["id"] for row in active_suppliers] == [kept["id"]]

        with_inactive = _data(
            await ac.get(
                f"{BASE}/master-objects",
                params={"kind": "supplier", "keyword": tag, "include_inactive": True},
            )
        )
        assert {row["id"] for row in with_inactive} == {kept["id"], stopped["id"]}

        inactive_only = _data(
            await ac.get(
                f"{BASE}/master-objects", params={"status": "inactive", "keyword": tag}
            )
        )
        assert [row["id"] for row in inactive_only] == [stopped["id"]]

        paged = (
            await ac.get(
                f"{BASE}/master-objects",
                params={"keyword": tag, "include_inactive": True, "page_size": 1},
            )
        ).json()
        assert paged["meta"]["total"] == 3
        assert len(paged["data"]) == 1
        assert material["is_active"] is True


# ───────────────────────── 文件类型与台账 ─────────────────────────


async def test_document_type_code_unique_and_deactivated_type_blocks_documents() -> None:
    """文件类型编码唯一；类型停用后不再接受新台账登记。

    类型是文件治理的分组维度，撞码会让权限与 AI 策略挂错组；停用
    表示该治理口径退役，新文件应改挂到现行类型上。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        doc_type = _data(
            await ac.post(
                f"{BASE}/document-types", json={"code": f"DT-{tag}", "name": f"类型{tag}"}
            )
        )
        duplicate = await ac.post(
            f"{BASE}/document-types", json={"code": f"DT-{tag}", "name": f"重复{tag}"}
        )
        assert duplicate.status_code == 409

        _data(
            await ac.post(
                f"{BASE}/documents",
                json={
                    "document_no": f"SOP.{tag}",
                    "title": f"文件{tag}",
                    "document_type_id": doc_type["id"],
                },
            )
        )
        _data(await ac.post(f"{BASE}/document-types/{doc_type['id']}/deactivate"))
        blocked = await ac.post(
            f"{BASE}/documents",
            json={
                "document_no": f"SOP.{tag}B",
                "title": f"文件B{tag}",
                "document_type_id": doc_type["id"],
            },
        )
        assert blocked.status_code == 422

        default_list = _data(await ac.get(f"{BASE}/document-types"))
        assert all(row["id"] != doc_type["id"] for row in default_list)
        full_list = _data(
            await ac.get(f"{BASE}/document-types", params={"include_inactive": True})
        )
        assert any(row["id"] == doc_type["id"] for row in full_list)


async def test_document_no_unique_and_current_version_filter() -> None:
    """台账编号唯一；列表可按「是否已有现行版本」筛选。

    编号是纸质档案与电子台账的对账键，重复即对账断裂；按现行版本
    筛选支撑「有据可查 / 尚无现行版本」两类工作清单。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        type_id, document_id = await _make_type_and_document(ac, tag)
        duplicate = await ac.post(
            f"{BASE}/documents",
            json={
                "document_no": f"SOP.{tag}",
                "title": f"重复{tag}",
                "document_type_id": type_id,
            },
        )
        assert duplicate.status_code == 409

        other = await _make_document(ac, type_id, f"SOP.{tag}2")
        version = _data(await _upload_version(ac, document_id, "V1"))
        _data(
            await ac.post(
                f"{BASE}/documents/{document_id}/versions/{version['id']}/make-current"
            )
        )

        with_current = _data(
            await ac.get(
                f"{BASE}/documents",
                params={"keyword": tag, "has_current_version": True},
            )
        )
        assert [row["id"] for row in with_current] == [document_id]
        without_current = _data(
            await ac.get(
                f"{BASE}/documents",
                params={"keyword": tag, "has_current_version": False},
            )
        )
        assert [row["id"] for row in without_current] == [other]


# ───────────────────────── 版本纪律 ─────────────────────────


async def test_version_registration_discipline() -> None:
    """版本登记纪律：必须声明外部批准、标签唯一、序号自增、文件真实。

    「已批准」是受控文件入库的合规前提，由上传人声明而非系统补齐；
    标签重复会破坏版本对外的可读性；文件魔数校验挡住改扩展名的
    伪装文件。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        _, document_id = await _make_type_and_document(ac, tag)

        unapproved = await _upload_version(ac, document_id, "V0", approved=False)
        assert unapproved.status_code == 422

        v1 = _data(await _upload_version(ac, document_id, "V1"))
        assert v1["version_sequence"] == 1
        assert v1["approved_declared"] is True

        duplicate_label = await _upload_version(ac, document_id, "V1")
        assert duplicate_label.status_code == 409

        v2 = _data(await _upload_version(ac, document_id, "V2"))
        assert v2["version_sequence"] == 2

        disguised = await ac.post(
            f"{BASE}/documents/{document_id}/versions",
            data={"version_label": "V3", "approved_declared": "true"},
            files={"file": ("report.pdf", b"MZ not a pdf", "application/pdf")},
        )
        assert disguised.status_code == 422


async def test_deactivated_document_rejects_version_actions() -> None:
    """台账停用后既不能登记新版本，也不能切换现行版本。

    停用代表该文件退出受控流通，任何继续追加内容的动作都要被
    挡下，防止「停而仍在用」的失控状态。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        _, document_id = await _make_type_and_document(ac, tag)
        version = _data(await _upload_version(ac, document_id, "V1"))
        _data(await ac.post(f"{BASE}/documents/{document_id}/deactivate"))

        new_version = await _upload_version(ac, document_id, "V2")
        assert new_version.status_code == 422
        blocked = await ac.post(
            f"{BASE}/documents/{document_id}/versions/{version['id']}/make-current"
        )
        assert blocked.status_code == 422


# ───────────────────────── 检索可见性 ─────────────────────────


async def test_search_requires_query_and_hides_inactive_by_default() -> None:
    """全局检索必须带关键词；停用档案默认不出现在结果里。

    检索是知识库的主入口：空关键词等于拖全库；停用档案默认隐藏，
    但审计/追溯场景可以显式打开 include_inactive 找回。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        master = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "SUPPLIER",
                    "code": f"SUP-{tag}",
                    "name": f"检索供应商{tag}",
                },
            )
        )
        missing_query = await ac.get(f"{BASE}/search")
        assert missing_query.status_code == 422

        assert any(
            hit["id"] == master["id"]
            for hit in _data(await ac.get(f"{BASE}/search", params={"q": tag}))
        )
        _data(await ac.post(f"{BASE}/master-objects/{master['id']}/deactivate"))
        hidden = _data(await ac.get(f"{BASE}/search", params={"q": tag}))
        assert all(hit["id"] != master["id"] for hit in hidden)
        visible = _data(
            await ac.get(
                f"{BASE}/search", params={"q": tag, "include_inactive": True}
            )
        )
        assert any(hit["id"] == master["id"] for hit in visible)


# ───────────────────────── 审计留痕 ─────────────────────────


async def test_file_preview_and_download_leave_audit_trail() -> None:
    """受控文件的每次预览和下载都写入审计日志，且可按条件追溯。

    审计是受控文件「谁看过、谁拿走过」的合规底账：动作与资源要能
    双向过滤，否则事后查证只能翻全量日志。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, _, _storage):
        _, document_id = await _make_type_and_document(ac, tag)
        version = _data(await _upload_version(ac, document_id, "V1"))
        file_id = version["file"]["id"]

        preview = await ac.get(f"{BASE}/document-files/{file_id}/content")
        assert preview.status_code == 200
        download = await ac.get(
            f"{BASE}/document-files/{file_id}/content", params={"download": True}
        )
        assert download.status_code == 200

        by_resource = (
            await ac.get(
                f"{BASE}/audit-logs",
                params={"resource_type": "document_file", "resource_id": file_id},
            )
        ).json()
        actions = [row["action"] for row in by_resource["data"]]
        assert sorted(actions) == ["download", "preview"]

        downloads_only = (
            await ac.get(
                f"{BASE}/audit-logs",
                params={
                    "action": "download",
                    "resource_type": "document_file",
                    "resource_id": file_id,
                },
            )
        ).json()
        assert [row["action"] for row in downloads_only["data"]] == ["download"]


# ───────────────────────── AI 分析与提案 ─────────────────────────


async def test_ai_analysis_blocked_when_type_policy_disables_ai() -> None:
    """文件类型把 AI 来源策略设为停用时，该类型下的文件拒绝 AI 分析。

    某些外部文件（客户提供的法规文件等）不允许进入 AI 管线，治理
    开关挂在类型上统一生效，而不是逐文件配置。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, session, _storage):
        doc_type = _data(
            await ac.post(
                f"{BASE}/document-types",
                json={
                    "code": f"DT-{tag}",
                    "name": f"禁AI类型{tag}",
                    "ai_source_policy": "disabled",
                },
            )
        )
        document = _data(
            await ac.post(
                f"{BASE}/documents",
                json={
                    "document_no": f"SOP.{tag}",
                    "title": f"文件{tag}",
                    "document_type_id": doc_type["id"],
                },
            )
        )
        version = _data(await _upload_version(ac, document["id"], "V1"))

        # 业务前置：文件已完成解析/分块（管线产物在测试里不真实存在，
        # 直接把状态就绪写到文件行上，验证的是策略开关这道闸）。
        file_row = (
            await session.execute(
                select(DocumentFile).where(DocumentFile.version_id == version["id"])
            )
        ).scalar_one()
        file_row.extraction_status = "ready"
        file_row.current_extraction_run_id = uuid.uuid4()
        file_row.current_chunk_run_id = uuid.uuid4()
        await session.flush()

        blocked = await ac.post(
            f"{BASE}/document-versions/{version['id']}/ai-analysis", json={}
        )
        assert blocked.status_code == 409
        assert "停用 AI" in blocked.text


async def test_master_proposal_reject_once_and_leaves_pending_box() -> None:
    """AI 主数据提案拒绝一次即落定：软删除移出待审箱，重复请求不可再触达。

    提案是 AI 产出的待审清单，人工裁决后必须落定：拒绝即软删除，
    待审箱不再显示，再次处理同一提案只能得到「不存在」——不允许
    同一提案被处理两次，否则状态与审计互相矛盾。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, session, _storage):
        user = await _ensure_test_user(session)
        _, document_id = await _make_type_and_document(ac, tag)
        version = _data(await _upload_version(ac, document_id, "V1"))
        file_id = version["file"]["id"]

        # 业务前置：一次已完成的 AI 分析产出一个待审提案（AI 出题、
        # 人工答题，这里只搭「已有待审提案」这个业务状态）。
        run = DocumentAIAnalysisRun(
            version_id=version["id"],
            file_id=file_id,
            status="ready",
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            catalog_fingerprint="c" * 64,
            input_fingerprint="i" * 64,
            source_policy="authoritative",
            requested_by=user.id,
        )
        session.add(run)
        await session.flush()
        proposal = MasterObjectProposal(
            analysis_run_id=run.id,
            proposal_type="create",
            object_type="SUPPLIER",
            proposed_payload={
                "object_type": "SUPPLIER",
                "code": f"SUP-{tag}",
                "name": f"提案供应商{tag}",
            },
            status="pending",
        )
        session.add(proposal)
        await session.flush()

        pending = (
            await ac.get(
                f"{BASE}/master-object-proposals", params={"status": "pending"}
            )
        ).json()
        assert any(row["id"] == str(proposal.id) for row in pending["data"])

        rejected = await ac.post(
            f"{BASE}/master-object-proposals/{proposal.id}/reject"
        )
        assert rejected.status_code == 200
        double = await ac.post(
            f"{BASE}/master-object-proposals/{proposal.id}/reject"
        )
        assert double.status_code == 404

        after = (
            await ac.get(
                f"{BASE}/master-object-proposals", params={"status": "pending"}
            )
        ).json()
        assert all(row["id"] != str(proposal.id) for row in after["data"])


# ───────────────────────── 提取产物与来源选择器 ─────────────────────────


async def test_extraction_artifacts_listing_and_content() -> None:
    """提取产物（图片/结构文件等）可列表、可预览下载，重解析期间不展示旧产物。

    产物是解析批次的附件证据：列表绑定明确的解析运行，新一轮解析
    排队/进行中时旧产物必须隐藏，否则前端会误判当前批次已完成；
    图片可内联预览，不可内联类型强制按附件下载。
    """
    tag = uuid.uuid4().hex[:6].upper()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    async with _client() as (ac, session, storage):
        _, document_id = await _make_type_and_document(ac, tag)
        version = _data(await _upload_version(ac, document_id, "V1"))
        file_row = (
            await session.execute(
                select(DocumentFile).where(DocumentFile.version_id == version["id"])
            )
        ).scalar_one()
        run_id = uuid.uuid4()
        storage.objects[f"artifacts/{tag}.png"] = png
        artifact = DocumentExtractionArtifact(
            file_id=file_row.id,
            extraction_run_id=run_id,
            artifact_type="image",
            source_name=f"{tag}.png",
            storage_key=f"artifacts/{tag}.png",
            mime_type="image/png",
            size_bytes=len(png),
            sha256=hashlib.sha256(png).hexdigest(),
        )
        session.add(artifact)
        file_row.extraction_status = "ready"
        file_row.current_extraction_run_id = run_id
        file_row.current_chunk_run_id = uuid.uuid4()
        await session.flush()

        listed = _data(await ac.get(f"{BASE}/document-files/{file_row.id}/artifacts"))
        assert [row["source_name"] for row in listed["items"]] == [f"{tag}.png"]

        preview = await ac.get(
            f"{BASE}/document-files/{file_row.id}/artifacts/{artifact.id}/content"
        )
        assert preview.status_code == 200
        assert preview.content == png
        assert "inline" in preview.headers["content-disposition"]
        download = await ac.get(
            f"{BASE}/document-files/{file_row.id}/artifacts/{artifact.id}/content",
            params={"download": True},
        )
        assert "attachment" in download.headers["content-disposition"]

        file_row.extraction_status = "processing"
        await session.flush()
        during = _data(await ac.get(f"{BASE}/document-files/{file_row.id}/artifacts"))
        assert during["items"] == []

        missing = await ac.get(
            f"{BASE}/document-files/{file_row.id}/artifacts/{uuid.uuid4()}/content"
        )
        assert missing.status_code == 404


async def test_reference_selectors_expose_production_sources() -> None:
    """来源选择器覆盖生产域：产品与中间体类型可作为主数据外部来源。"""
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, session, _storage):
        session.add(
            Product(
                product_code=f"PRD-{tag}", product_name=f"选择器产品{tag}", unit="kg"
            )
        )
        await session.flush()

        products = _data(
            await ac.get(
                f"{BASE}/references/sources/PRODUCT", params={"keyword": tag}
            )
        )
        assert [row["code"] for row in products] == [f"PRD-{tag}"]
        assert products[0]["source_module"] == "production"
        assert products[0]["source_entity"] == "product"

        intermediates = _data(
            await ac.get(
                f"{BASE}/references/sources/MATERIAL", params={"keyword": tag}
            )
        )
        assert intermediates == []


async def test_ai_confirm_relations_accepts_candidates_and_guards_repeat() -> None:
    """AI 候选关联的确认：勾选写入正式关联、运行详情可查、重复提交被拒。

    AI 只产候选，正式关系必须人工勾选落库；每轮候选只允许首次
    决定，重复提交要求重新分析或走人工维护入口。未完成或不存在
    的运行不能确认。
    """
    tag = uuid.uuid4().hex[:6].upper()
    async with _client() as (ac, session, _storage):
        _, document_id = await _make_type_and_document(ac, tag)
        version = _data(await _upload_version(ac, document_id, "V1"))
        file_row = (
            await session.execute(
                select(DocumentFile).where(DocumentFile.version_id == version["id"])
            )
        ).scalar_one()
        extraction_run_id = uuid.uuid4()
        chunk_run_id = uuid.uuid4()
        file_row.extraction_status = "ready"
        file_row.current_extraction_run_id = extraction_run_id
        file_row.current_chunk_run_id = chunk_run_id
        master = _data(
            await ac.post(
                f"{BASE}/master-objects",
                json={
                    "object_type": "EQUIPMENT",
                    "code": f"EQ-{tag}",
                    "name": f"候选设备{tag}",
                },
            )
        )
        # 前置条件对齐：目录指纹取当前主数据目录的实际值（须在全部
        # 主数据就位后再取），让本轮分析处于「未过期」业务状态。
        _, _, catalog_fingerprint = await ai_analysis_service._catalog(session)
        run = DocumentAIAnalysisRun(
            version_id=version["id"],
            file_id=file_row.id,
            extraction_run_id=extraction_run_id,
            chunk_run_id=chunk_run_id,
            status="ready",
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            catalog_fingerprint=catalog_fingerprint,
            input_fingerprint="i" * 64,
            source_policy="authoritative",
        )
        session.add(run)
        await session.flush()

        observation = DocumentEntityObservation(
            analysis_run_id=run.id,
            mention_text=f"设备EQ-{tag}",
            normalized_text=f"EQ-{tag}",
            entity_type="equipment",
            quote=f"使用设备EQ-{tag}进行清洁",
            evidence_hash="e" * 64,
            locator="page:1/block:1",
        )
        session.add(observation)
        await session.flush()
        suggestion = DocumentRelationSuggestion(
            analysis_run_id=run.id,
            observation_id=observation.id,
            master_object_id=uuid.UUID(master["id"]),
            match_method="exact_code",
        )
        session.add(suggestion)
        await session.flush()

        detail = _data(await ac.get(f"{BASE}/ai-analysis/{run.id}"))
        assert detail["status"] == "ready"

        confirmed = _data(
            await ac.post(
                f"{BASE}/ai-analysis/{run.id}/confirm-relations",
                json={"accepted_suggestion_ids": [str(suggestion.id)]},
            )
        )
        assert [row["master_object_id"] for row in confirmed] == [master["id"]]

        repeat = await ac.post(
            f"{BASE}/ai-analysis/{run.id}/confirm-relations",
            json={"accepted_suggestion_ids": [str(suggestion.id)]},
        )
        assert repeat.status_code == 409
        assert "不能重复" in repeat.text

        unknown = await ac.post(
            f"{BASE}/ai-analysis/{uuid.uuid4()}/confirm-relations",
            json={"accepted_suggestion_ids": []},
        )
        assert unknown.status_code == 404

        unfinished = DocumentAIAnalysisRun(
            version_id=version["id"],
            file_id=file_row.id,
            extraction_run_id=extraction_run_id,
            chunk_run_id=chunk_run_id,
            status="processing",
            provider="test",
            model="test-model",
            prompt_version="v1",
            schema_version="v1",
            catalog_fingerprint=catalog_fingerprint,
            input_fingerprint="i" * 64,
            source_policy="authoritative",
        )
        session.add(unfinished)
        await session.flush()
        blocked = await ac.post(
            f"{BASE}/ai-analysis/{unfinished.id}/confirm-relations",
            json={"accepted_suggestion_ids": []},
        )
        assert blocked.status_code == 409
        assert "尚未完成" in blocked.text
