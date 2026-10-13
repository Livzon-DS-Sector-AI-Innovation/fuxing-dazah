"""ragplus-x 知识层客户端单测 — 唯一主接缝：HTTP 边界（httpx.MockTransport）。

只测外部行为：命中归一化、dataset 名单限定、重试与不可用异常、管理端
登录/建库幂等/上传/轮询/删除/token 去重。不测内部实现细节。
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.modules.safety.app_config.registry import REGISTRY
from app.modules.safety.knowledge.ragplus_client import (
    RagplusAdminClient,
    RagplusAdminError,
    RagplusClient,
    RagplusUnavailableError,
)

_BASE = "http://ragplus.test"

_DATASETS_BODY: list[dict[str, Any]] = [
    {"id": "ds-law", "name": "安全法规标准", "kb_id": 1},
    {"id": "ds-msds", "name": "MSDS", "kb_id": 2},
    {"id": "ds-archived", "name": "已废止", "kb_id": 3},
]

_CHUNKS_BODY: list[dict[str, Any]] = [
    {
        "chunk_id": "ck-1",
        "content": "动火作业应办理作业票",
        "document_id": "doc-9",
        "doc_name": "GB 30871-2022 危险化学品企业特殊作业安全规范.pdf",
        "dataset_id": "ds-law",
        "page": 12,
        "similarity": 0.87,
        "highlight": "动火作业应办理<em>作业票</em>",
    },
]


def _retrieval_client(
    handler: Any,
    dataset_names: list[str] | None = None,
) -> RagplusClient:
    return RagplusClient(
        base_url=_BASE,
        token="ragflow-test",
        timeout=5,
        dataset_names=dataset_names or ["安全法规标准", "MSDS"],
        transport=httpx.MockTransport(handler),
    )


class TestRagplusClientSearch:
    async def test_search_normalizes_hits_and_scopes_datasets(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json=_DATASETS_BODY)
            assert request.url.path == "/api/v1/retrieval"
            return httpx.Response(200, json={"code": 0, "chunks": _CHUNKS_BODY})

        client = _retrieval_client(handler)
        hits = await client.search("动火作业有什么要求？", top_k=6)

        assert len(hits) == 1
        hit = hits[0]
        assert hit.chunk_id == "ck-1"
        assert hit.content == "动火作业应办理作业票"
        assert hit.doc_name.startswith("GB 30871-2022")
        assert hit.document_id == "doc-9"
        assert hit.dataset_id == "ds-law"
        assert hit.page == 12
        assert hit.similarity == pytest.approx(0.87)
        assert "作业票" in hit.highlight

        retrieval_req = next(r for r in calls if r.url.path == "/api/v1/retrieval")
        body = __import__("json").loads(retrieval_req.content)
        assert body["question"] == "动火作业有什么要求？"
        assert body["top_k"] == 6
        assert body["rerank"] is True
        # 已废止归档库不在名单内，必须被排除
        assert sorted(body["dataset_ids"]) == ["ds-law", "ds-msds"]
        assert retrieval_req.headers["Authorization"] == "Bearer ragflow-test"

    async def test_search_without_matching_datasets_raises(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/datasets"
            return httpx.Response(200, json=[{"id": "ds-archived", "name": "已废止"}])

        client = _retrieval_client(handler)
        with pytest.raises(RagplusUnavailableError, match="安全法规标准"):
            await client.search("任意问题")

    async def test_search_retries_once_on_connect_error(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json=_DATASETS_BODY)
            if attempts["n"] == 2:  # 首次 retrieval 连接失败
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(200, json={"code": 0, "chunks": _CHUNKS_BODY})

        client = _retrieval_client(handler)
        hits = await client.search("问题")
        assert len(hits) == 1
        assert attempts["n"] == 3  # datasets + 失败 1 次 + 成功 1 次

    async def test_search_transport_failure_raises_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json=_DATASETS_BODY)
            raise httpx.ConnectTimeout("timed out", request=request)

        client = _retrieval_client(handler)
        with pytest.raises(RagplusUnavailableError):
            await client.search("问题")

    async def test_search_5xx_raises_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json=_DATASETS_BODY)
            return httpx.Response(500, text="engine down")

        client = _retrieval_client(handler)
        with pytest.raises(RagplusUnavailableError):
            await client.search("问题")

    async def test_search_401_raises_without_retry(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if request.url.path == "/api/v1/datasets":
                return httpx.Response(200, json=_DATASETS_BODY)
            return httpx.Response(401, text="unauthorized")

        client = _retrieval_client(handler)
        with pytest.raises(RagplusUnavailableError, match="鉴权"):
            await client.search("问题")
        assert attempts["n"] == 2  # datasets + retrieval（无重试）


class TestRagplusRegistryKeys:
    def test_five_keys_registered_with_defaults(self) -> None:
        enabled = REGISTRY["SAFETY_RAGPLUS_SEARCH_ENABLED"]
        assert enabled.default is False
        assert enabled.type == "bool"

        assert REGISTRY["SAFETY_RAGPLUS_BASE_URL"].default == "http://localhost:8085"

        token = REGISTRY["SAFETY_RAGPLUS_API_TOKEN"]
        assert token.default == ""
        assert token.secret is True

        timeout = REGISTRY["SAFETY_RAGPLUS_TIMEOUT_SECONDS"]
        assert timeout.default == 10
        assert timeout.type == "int"

        names = REGISTRY["SAFETY_RAGPLUS_DATASET_NAMES"]
        assert names.default == "安全法规标准,MSDS"


def _admin_client(handler: Any) -> RagplusAdminClient:
    return RagplusAdminClient(
        base_url=_BASE,
        username="admin",
        password="secret",
        timeout=30,
        transport=httpx.MockTransport(handler),
    )


_LOGIN_OK = httpx.Response(200, json={"token": "jwt-1", "user": {"id": 1}})


class TestRagplusAdminClient:
    async def test_ensure_kb_existing_no_create(self) -> None:
        posts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs" and request.method == "GET":
                return httpx.Response(
                    200,
                    json=[{"id": 7, "name": "安全法规标准", "dataset_id": "ds-law"}],
                )
            if request.url.path == "/api/kbs" and request.method == "POST":
                posts.append(request.url.path)
                return httpx.Response(200, json={"id": 9})
            raise AssertionError(f"unexpected {request.method} {request.url.path}")

        admin = _admin_client(handler)
        kb = await admin.ensure_kb("安全法规标准")
        assert kb["id"] == 7
        assert posts == []

    async def test_ensure_kb_creates_when_missing(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs" and request.method == "GET":
                return httpx.Response(200, json=[])
            if request.url.path == "/api/kbs" and request.method == "POST":
                return httpx.Response(
                    200, json={"id": 9, "name": "MSDS", "dataset_id": "ds-9"}
                )
            raise AssertionError(f"unexpected {request.method} {request.url.path}")

        admin = _admin_client(handler)
        kb = await admin.ensure_kb("MSDS")
        assert kb["id"] == 9

    async def test_upload_document_posts_multipart(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs/7/docs/upload":
                seen["ct"] = request.headers.get("content-type", "")
                seen["body"] = request.content
                return httpx.Response(
                    200, json=[{"id": 11, "name": "a.pdf", "status": "UNSTART"}]
                )
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        doc = await admin.upload_document(7, "a.pdf", b"%PDF-fake")
        assert doc["id"] == 11
        assert "multipart/form-data" in seen["ct"]
        assert b"%PDF-fake" in seen["body"]
        assert b"a.pdf" in seen["body"]

    async def test_wait_documents_ready_polls_until_done(self) -> None:
        polls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs/7/docs":
                polls["n"] += 1
                status = "RUNNING" if polls["n"] == 1 else "DONE"
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 11,
                            "name": "a.pdf",
                            "status": status,
                            "progress": 0.5,
                            "fail_reason": None,
                        }
                    ],
                )
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        result = await admin.wait_documents_ready(7, [11], poll=0.01, deadline=5)
        assert result[11]["status"] == "DONE"
        assert polls["n"] == 2

    async def test_wait_documents_ready_reports_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs/7/docs":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 11,
                            "name": "a.pdf",
                            "status": "FAIL",
                            "fail_reason": "解析超时",
                        }
                    ],
                )
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        result = await admin.wait_documents_ready(7, [11], poll=0.01, deadline=5)
        assert result[11]["status"] == "FAIL"
        assert result[11]["fail_reason"] == "解析超时"

    async def test_delete_document(self) -> None:
        methods: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs/7/docs/11":
                methods.append(request.method)
                return httpx.Response(200, json={"ok": True})
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        await admin.delete_document(7, 11)
        assert methods == ["DELETE"]

    async def test_admin_http_error_raises_admin_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/kbs" and request.method == "GET":
                return httpx.Response(500, text="boom")
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        with pytest.raises(RagplusAdminError):
            await admin.list_kbs()

    async def test_ensure_token_creates_then_dedupes(self) -> None:
        creates = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/tokens" and request.method == "GET":
                if creates["n"]:
                    return httpx.Response(
                        200,
                        json=[
                            {
                                "id": 1,
                                "name": "dazah-safety-service",
                                "scopes": ["retrieval"],
                            }
                        ],
                    )
                return httpx.Response(200, json=[])
            if request.url.path == "/api/tokens" and request.method == "POST":
                creates["n"] += 1
                return httpx.Response(
                    200,
                    json={"id": 1, "token": "ragflow-created", "prefix": "ragflow-c"},
                )
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        first = await admin.ensure_token("dazah-safety-service")
        assert first == "ragflow-created"

        second = await admin.ensure_token("dazah-safety-service")
        assert second is None  # 已存在（按名去重），不再创建
        assert creates["n"] == 1

    async def test_revoke_token(self) -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/auth/login":
                return httpx.Response(200, json={"token": "jwt-1"})
            if request.url.path == "/api/tokens/3":
                calls.append(request.method)
                return httpx.Response(200, json={"ok": True})
            raise AssertionError(f"unexpected {request.url.path}")

        admin = _admin_client(handler)
        await admin.revoke_token(3)
        assert calls == ["DELETE"]
