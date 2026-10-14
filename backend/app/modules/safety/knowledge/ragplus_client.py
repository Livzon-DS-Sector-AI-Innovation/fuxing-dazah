"""ragplus-x 知识层客户端 — 检索（Bearer token）与管理（JWT）双轨。

dazah 安全模块与 ragplus-x 知识层之间的唯一 HTTP 通道（一期壳换芯）：

- ``RagplusClient``：检索消费面用。Bearer ``ragflow-`` token 调
  ``POST /api/v1/retrieval``（高亮+重排，条款级命中），命中归一化为
  ``RagplusHit``；检索范围按库名单限定（已废止归档库不在名单内即被排除，
  retrieval API 缺省会搜 token 用户全部可见库）。连接类错误重试一次；
  连接失败/超时/5xx/鉴权失败统一抛 ``RagplusUnavailableError``，
  由壳层转成消费方显式报错（不静默空结果）。
- ``RagplusAdminClient``：入库面用（批量脚本 + 增量事件后台上传）。
  JWT 登录态（应急 admin 账密，env 可覆盖）操作文件管理 API：
  幂等建库 / 上传文档 / 批量解析 / 轮询就绪 / 删文档 / token 去重创建。
  失败抛 ``RagplusAdminError``（运维错误，与检索不可用语义分开）。

配置全部来自 app_config（SAFETY_RAGPLUS_*），经 ``get_ragplus_client()``
按配置指纹共享单例——bootstrap 脚本写入 token 后无需重启即生效。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 检索库名单解析结果缓存秒数（dataset_id 对建库操作稳定，短 TTL 只为
# 兜住「入库脚本刚建库、检索随即发起」的时序窗口）
_DATASET_CACHE_TTL = 300.0
# 连接类错误重试次数（仅一次：知识层本机直连，快速失败比长等待更可控）
_CONNECT_RETRIES = 1


class RagplusUnavailableError(RuntimeError):
    """ragplus-x 检索不可用（连接失败/超时/5xx/鉴权失败/知识库未就绪）。

    壳层据此向消费方显式报错：聊天入口返回报错话术，AI 管线产出标注。
    """


class RagplusAdminError(RuntimeError):
    """ragplus-x 管理操作失败（登录/建库/上传/解析/删除/token）。"""


@dataclass(frozen=True)
class RagplusHit:
    """归一化检索命中（/api/v1/retrieval chunk）。"""

    chunk_id: str
    content: str
    doc_name: str
    document_id: str
    dataset_id: str
    page: int | None
    similarity: float
    highlight: str


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RagplusClient:
    """检索客户端（Bearer ragflow- token，/api/v1/*）。"""

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = 10.0,
        dataset_names: list[str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.dataset_names = dataset_names or []
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._dataset_ids: list[str] | None = None
        self._dataset_ids_at: float = 0.0

    # ── HTTP ──

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        auth_failed_keyword: str = "鉴权",
    ) -> Any:
        """带一次连接重试的 JSON 请求；失败统一转 RagplusUnavailableError。"""
        client = self._http()
        last_error: Exception | None = None
        for attempt in range(_CONNECT_RETRIES + 1):
            try:
                resp = await client.request(method, path, json=json_body)
            except httpx.HTTPError as exc:
                last_error = exc
                if isinstance(exc, httpx.TransportError) and attempt < _CONNECT_RETRIES:
                    logger.warning(
                        "ragplus 请求连接失败（第 %d 次，重试）：%s %s: %s",
                        attempt + 1,
                        method,
                        path,
                        exc,
                    )
                    continue
                raise RagplusUnavailableError(
                    f"ragplus 知识层连接失败：{method} {path}: {exc}"
                ) from exc

            if resp.status_code in (401, 403):
                raise RagplusUnavailableError(
                    f"ragplus {auth_failed_keyword}失败（{resp.status_code}）："
                    "请检查 SAFETY_RAGPLUS_API_TOKEN 与 token 作用域"
                )
            if resp.status_code >= 500:
                last_error = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                if attempt < _CONNECT_RETRIES:
                    logger.warning(
                        "ragplus 返回 %d（第 %d 次，重试）：%s",
                        resp.status_code,
                        attempt + 1,
                        path,
                    )
                    continue
                raise RagplusUnavailableError(
                    f"ragplus 知识层服务异常：{method} {path}: HTTP {resp.status_code}"
                ) from last_error
            if resp.status_code >= 400:
                raise RagplusUnavailableError(
                    f"ragplus 请求失败：{method} {path}: HTTP {resp.status_code} {resp.text[:200]}"
                )
            return resp.json()

        raise RagplusUnavailableError(
            f"ragplus 知识层连接失败：{method} {path}: {last_error}"
        )

    # ── 检索 ──

    async def search(self, question: str, top_k: int = 6) -> list[RagplusHit]:
        """混合检索（BM25+向量+重排），返回归一化命中（按 similarity 降序）。"""
        ids = await self._resolve_dataset_ids()
        data = await self._request_json(
            "POST",
            "/api/v1/retrieval",
            json_body={
                "question": question,
                "dataset_ids": ids,
                "top_k": top_k,
                "rerank": True,
            },
        )
        chunks = (data or {}).get("chunks") or []
        hits: list[RagplusHit] = []
        for c in chunks:
            if not isinstance(c, dict):
                continue
            hits.append(
                RagplusHit(
                    chunk_id=str(c.get("chunk_id", "")),
                    content=str(c.get("content", "")),
                    doc_name=str(c.get("doc_name", "")),
                    document_id=str(c.get("document_id", "")),
                    dataset_id=str(c.get("dataset_id", "")),
                    page=_to_int(c.get("page")),
                    similarity=float(c.get("similarity") or 0.0),
                    highlight=str(c.get("highlight") or ""),
                )
            )
        return hits

    async def list_datasets(self) -> list[dict[str, Any]]:
        """列出 token 用户可见的知识库（/api/v1/datasets 原始列表）。

        页面引擎状态卡用：取名单内各库的 doc_count/chunk_count 实时总量。
        """
        kbs = await self._request_json("GET", "/api/v1/datasets")
        if isinstance(kbs, dict):
            kbs = kbs.get("data") or []
        return [kb for kb in kbs if isinstance(kb, dict)]

    async def _resolve_dataset_ids(self) -> list[str]:
        """按库名单解析 dataset_ids（/api/v1/datasets，进程内 TTL 缓存）。

        retrieval API 缺省会搜 token 用户全部可见库（含已废止归档库），
        必须显式限定；名单来自 SAFETY_RAGPLUS_DATASET_NAMES。
        """
        now = time.monotonic()
        if self._dataset_ids and now - self._dataset_ids_at < _DATASET_CACHE_TTL:
            return self._dataset_ids
        names = {n.strip() for n in self.dataset_names if n and n.strip()}
        kbs = await self._request_json("GET", "/api/v1/datasets")
        if isinstance(kbs, dict):
            kbs = kbs.get("data") or []
        ids = [
            str(kb.get("id") or "")
            for kb in kbs
            if isinstance(kb, dict) and kb.get("name") in names and kb.get("id")
        ]
        if not ids:
            raise RagplusUnavailableError(
                f"ragplus 知识库未就绪：名单 {sorted(names)} 中无任何库已建立"
            )
        self._dataset_ids = sorted(ids)
        self._dataset_ids_at = now
        return self._dataset_ids


class RagplusAdminClient:
    """管理客户端（JWT 登录态：建库/上传/解析/轮询/删除/token）。

    供存量批量入库脚本与增量事件后台上传共用；凭证为 ragplus 应急
    admin 账密（env RAGPLUS_ADMIN_USER/RAGPLUS_ADMIN_PASSWORD 可覆盖）。
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self._transport = transport
        self._jwt: str | None = None
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {}
            if self._jwt:
                headers["Authorization"] = f"Bearer {self._jwt}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                transport=self._transport,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _ensure_login(self) -> httpx.AsyncClient:
        if self._jwt is None:
            await self.login()
        return self._http()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = await self._ensure_login()
        resp = await client.request(method, path, json=json_body, files=files)
        if resp.status_code >= 400:
            raise RagplusAdminError(
                f"ragplus 管理操作失败：{method} {path}: "
                f"HTTP {resp.status_code} {resp.text[:200]}"
            )
        return resp

    async def login(self) -> None:
        """应急 admin 账密登录取 JWT（POST /api/auth/login）。"""
        client = self._http()
        resp = await client.post(
            "/api/auth/login",
            json={"username": self.username, "password": self.password},
        )
        if resp.status_code >= 400:
            raise RagplusAdminError(
                f"ragplus 管理端登录失败：HTTP {resp.status_code} {resp.text[:200]}"
            )
        token = (resp.json() or {}).get("token") or ""
        if not token:
            raise RagplusAdminError("ragplus 管理端登录失败：响应缺少 token")
        self._jwt = token
        self._client = None  # 重建客户端以带上 Authorization 头

    # ── 知识库 ──

    async def list_kbs(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/kbs")
        data = resp.json()
        return data if isinstance(data, list) else []

    async def ensure_kb(self, name: str, description: str = "") -> dict[str, Any]:
        """按名幂等建库（存在即复用）。"""
        for kb in await self.list_kbs():
            if kb.get("name") == name:
                return kb
        resp = await self._request(
            "POST",
            "/api/kbs",
            json_body={"name": name, "description": description},
        )
        kb = resp.json()
        if not isinstance(kb, dict) or not kb.get("id"):
            raise RagplusAdminError(f"ragplus 建库响应异常：{name}")
        return kb

    # ── 文档 ──

    async def upload_document(
        self,
        kb_id: int,
        filename: str,
        blob: bytes,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """上传文档入库（POST /api/kbs/{kb}/docs/upload，multipart）。"""
        resp = await self._request(
            "POST",
            f"/api/kbs/{kb_id}/docs/upload",
            files={"file": (filename, blob, content_type)},
        )
        data = resp.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict) or not data.get("id"):
            raise RagplusAdminError(f"ragplus 上传响应异常：{filename}")
        return data

    async def parse_documents(
        self,
        kb_id: int,
        doc_ids: list[int],
        mode: str = "parallel",
    ) -> None:
        await self._request(
            "POST",
            f"/api/kbs/{kb_id}/parse",
            json_body={"doc_ids": doc_ids, "mode": mode},
        )

    async def list_documents(self, kb_id: int) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"/api/kbs/{kb_id}/docs")
        data = resp.json()
        return data if isinstance(data, list) else []

    async def delete_document(self, kb_id: int, doc_id: int) -> None:
        await self._request("DELETE", f"/api/kbs/{kb_id}/docs/{doc_id}")

    async def wait_documents_ready(
        self,
        kb_id: int,
        doc_ids: list[int],
        *,
        poll: float = 4.0,
        deadline: float = 1800.0,
    ) -> dict[int, dict[str, Any]]:
        """轮询文档解析直至全部终止态（DONE/FAIL/CANCEL）。

        返回 {doc_id: {"status", "fail_reason", "chunk_count"}}；超时对未就绪
        文档以当时的最新状态返回（调用方按 status 判定成败）。
        """
        pending = set(doc_ids)
        result: dict[int, dict[str, Any]] = {}
        start = time.monotonic()
        while pending and time.monotonic() - start < deadline:
            await asyncio.sleep(poll)
            docs = await self.list_documents(kb_id)
            by_id = {d.get("id"): d for d in docs if isinstance(d, dict)}
            for doc_id in list(pending):
                doc = by_id.get(doc_id)
                if not doc:
                    continue  # 引擎侧尚未出现，继续等
                status = str(doc.get("status") or "")
                if status in ("DONE", "FAIL", "CANCEL"):
                    result[doc_id] = {
                        "status": status,
                        "fail_reason": doc.get("fail_reason"),
                        "chunk_count": doc.get("chunk_count") or 0,
                    }
                    pending.discard(doc_id)
        for doc_id in pending:
            result[doc_id] = {
                "status": "TIMEOUT",
                "fail_reason": "轮询超时",
                "chunk_count": 0,
            }
        return result

    # ── API Token ──

    async def list_tokens(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/api/tokens")
        data = resp.json()
        return data if isinstance(data, list) else []

    async def revoke_token(self, token_id: int) -> None:
        await self._request("DELETE", f"/api/tokens/{token_id}")

    async def create_token(
        self, name: str, scopes: tuple[str, ...] = ("retrieval",)
    ) -> str:
        resp = await self._request(
            "POST",
            "/api/tokens",
            json_body={"name": name, "scopes": list(scopes)},
        )
        token = (resp.json() or {}).get("token") or ""
        if not token:
            raise RagplusAdminError("ragplus token 创建响应缺少全文")
        return token

    async def ensure_token(
        self,
        name: str,
        scopes: tuple[str, ...] = ("retrieval",),
    ) -> str | None:
        """按名去重创建 token；已存在返回 None（全文仅创建时可见一次）。"""
        for row in await self.list_tokens():
            if row.get("name") == name:
                return None
        return await self.create_token(name, scopes)


# ── 配置工厂（app_config → 共享单例）──

_shared_client: RagplusClient | None = None
_shared_fingerprint: tuple[Any, ...] = ()


def _parse_dataset_names(raw: str) -> list[str]:
    return [n.strip() for n in raw.replace("，", ",").split(",") if n.strip()]


def get_ragplus_client() -> RagplusClient:
    """按当前 app_config 构建或复用共享检索客户端。

    配置指纹（base_url/token/timeout/库名单）变化即重建——bootstrap 脚本
    写入 token、改超时等无需重启进程。
    """
    global _shared_client, _shared_fingerprint

    from app.modules.safety.app_config.store import store

    base_url = store.get_str("SAFETY_RAGPLUS_BASE_URL") or "http://localhost:8085"
    token = store.get_str("SAFETY_RAGPLUS_API_TOKEN") or ""
    timeout = float(store.get_int("SAFETY_RAGPLUS_TIMEOUT_SECONDS") or 10)
    names = _parse_dataset_names(store.get_str("SAFETY_RAGPLUS_DATASET_NAMES") or "")

    fingerprint = (base_url, token, timeout, tuple(names))
    if _shared_client is None or _shared_fingerprint != fingerprint:
        if _shared_client is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_shared_client.aclose())
            except RuntimeError:
                pass  # 无运行循环（同步上下文），交由 GC 回收
        _shared_client = RagplusClient(base_url, token, timeout, names)
        _shared_fingerprint = fingerprint
    return _shared_client


def ragplus_search_enabled() -> bool:
    """总闸：检索内核与入库短路的唯一开关（逐次读 store，免重启翻转）。"""
    from app.modules.safety.app_config.store import store

    return store.get_bool("SAFETY_RAGPLUS_SEARCH_ENABLED")
