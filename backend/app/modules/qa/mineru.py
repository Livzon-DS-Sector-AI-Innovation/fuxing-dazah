"""MinerU v4 异步 HTTP 适配器。

MinerU 的调用被刻意拆成四个单步接口：申请上传地址、上传字节、轮询批次、
下载结果。服务会在每个步骤之间提交 ``DocumentExtractionRun`` 状态，便于
前端展示、失败审计和后续调度续跑；令牌不会写入运行上下文。
"""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx

from app.core.config import get_settings
from app.modules.qa import file_service
from app.modules.qa.document_processing import (
    ExtractionDocument,
    parse_extracted_document,
)

MINERU_BASE_URL = "https://mineru.net/api/v4"
MINERU_MODEL_VERSION = "vlm"
MINERU_REQUEST_TIMEOUT_SECONDS = 120
MINERU_POLL_INTERVAL_SECONDS = 2.0
# 轮询预算按时间算（见 service 里的 poll_deadline），所以退避只影响这段时间
# 内打多少次远端：前 30 次按秒级跟进，小文件几秒内拿到结果；之后退到慢档，
# 否则 30 分钟全程按 2s 跟就是九百次调用。
MINERU_SLOW_POLL_INTERVAL_SECONDS = 10.0
MINERU_FAST_POLL_COUNT = 30
MINERU_PARSER_VERSION = "mineru-v4"
# 结果包上限。原件本身最大 50MB，结果包还要装 Markdown、结构化 JSON 和
# 全部图片，所以留了余量；再大就判失败，不把未知大小的归档读进内存。
MAX_RESULT_ARCHIVE_BYTES = 200 * 1024 * 1024
_ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}


class MineruError(RuntimeError):
    """MinerU 请求或响应协议错误。"""


@dataclass(frozen=True, slots=True)
class MineruUploadSession:
    batch_id: str
    upload_url: str
    file_name: str
    data_id: str


@dataclass(frozen=True, slots=True)
class MineruPollResult:
    batch_id: str
    file_name: str
    state: str
    task_id: str | None = None
    full_zip_url: str | None = None
    markdown_url: str | None = None
    error: str | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MineruArtifact:
    source_name: str
    data: bytes
    artifact_type: str
    mime_type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class MineruResult:
    task_id: str
    batch_id: str
    markdown: str
    document: ExtractionDocument
    artifacts: tuple[MineruArtifact, ...]
    statistics: dict[str, Any] = field(default_factory=dict)


def _settings_values() -> tuple[str, str, str]:
    settings = get_settings()
    token = settings.QA_MD_EXTRACT_API_TOKEN.strip()
    if not token:
        raise MineruError("QA_MD_EXTRACT_API_TOKEN 未配置")
    provider = settings.QA_MD_EXTRACT_PROVIDER.strip().casefold()
    if provider and provider != "mineru":
        raise MineruError(f"不支持的 QA_MD_EXTRACT_PROVIDER: {provider}")
    return token, MINERU_BASE_URL, MINERU_MODEL_VERSION


def _auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _json_response(response: httpx.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise MineruError(f"MinerU {operation} HTTP {response.status_code}") from exc
    try:
        body = response.json()
    except ValueError as exc:
        raise MineruError(f"MinerU {operation} 返回了无效 JSON") from exc
    if not isinstance(body, dict):
        raise MineruError(f"MinerU {operation} 返回结构无效")
    code = body.get("code")
    if code not in (None, 0, "0"):
        message = str(body.get("msg") or "请求失败")[:500]
        raise MineruError(f"MinerU {operation} 失败: {message}")
    return body


async def _with_client(client: httpx.AsyncClient | None) -> tuple[httpx.AsyncClient, bool]:
    if client is not None:
        return client, False
    return httpx.AsyncClient(timeout=MINERU_REQUEST_TIMEOUT_SECONDS), True


async def request_upload(
    data: bytes,
    filename: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> MineruUploadSession:
    """申请一次批量上传地址；不上传文件字节。"""
    token, base_url, model_version = _settings_values()
    http, own_client = await _with_client(client)
    data_id = hashlib.sha256(data).hexdigest()
    try:
        response = await http.post(
            f"{base_url}/file-urls/batch",
            headers=_auth_headers(token),
            json={"files": [{"name": filename, "data_id": data_id}], "model_version": model_version},
        )
        body = _json_response(response, "申请上传地址")
        payload = body.get("data")
        if not isinstance(payload, dict):
            raise MineruError("MinerU 申请上传地址响应缺少 data")
        batch_id = str(payload.get("batch_id") or "").strip()
        urls = payload.get("file_urls")
        upload_url = str(urls[0] or "").strip() if isinstance(urls, list) and urls else ""
        if not batch_id or not upload_url:
            raise MineruError("MinerU 申请上传地址响应缺少 batch_id/file_urls")
        return MineruUploadSession(batch_id, upload_url, filename, data_id)
    except httpx.TimeoutException as exc:
        raise MineruError("MinerU 申请上传地址超时") from exc
    except httpx.RequestError as exc:
        raise MineruError("MinerU 申请上传地址网络请求失败") from exc
    finally:
        if own_client:
            await http.aclose()


async def upload_bytes(
    session: MineruUploadSession,
    data: bytes,
    *,
    client: httpx.AsyncClient | None = None,
) -> None:
    """向 MinerU 返回的签名地址上传文件；签名地址不附带 API token。"""
    http, own_client = await _with_client(client)
    try:
        response = await http.put(session.upload_url, content=data)
        if response.status_code < 200 or response.status_code >= 300:
            raise MineruError(f"MinerU 文件上传 HTTP {response.status_code}")
    except httpx.TimeoutException as exc:
        raise MineruError("MinerU 文件上传超时") from exc
    except httpx.RequestError as exc:
        raise MineruError("MinerU 文件上传网络请求失败") from exc
    finally:
        if own_client:
            await http.aclose()


async def poll_result(
    batch_id: str,
    filename: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> MineruPollResult:
    """执行一次状态查询；调用方按 ``MINERU_POLL_INTERVAL_SECONDS`` 调度下一次。"""
    token, base_url, _ = _settings_values()
    http, own_client = await _with_client(client)
    try:
        response = await http.get(
            f"{base_url}/extract-results/batch/{batch_id}",
            headers=_auth_headers(token),
        )
        body = _json_response(response, "查询解析结果")
        payload = body.get("data")
        if not isinstance(payload, dict):
            raise MineruError("MinerU 查询响应缺少 data")
        values = payload.get("extract_result")
        if isinstance(values, dict):
            candidates = [values]
        elif isinstance(values, list):
            candidates = [item for item in values if isinstance(item, dict)]
        else:
            candidates = []
        result = next(
            (item for item in candidates if str(item.get("file_name") or "") == filename),
            candidates[0] if candidates else {},
        )
        state = str(result.get("state") or "pending").casefold()
        task_id = str(result.get("task_id") or result.get("data_id") or "").strip() or None
        error = str(result.get("err_msg") or "").strip()[:500] or None
        progress = result.get("extract_progress")
        return MineruPollResult(
            batch_id=batch_id,
            file_name=filename,
            state=state,
            task_id=task_id,
            full_zip_url=str(result.get("full_zip_url") or "").strip() or None,
            markdown_url=str(result.get("markdown_url") or "").strip() or None,
            error=error,
            progress=progress if isinstance(progress, dict) else {},
            raw=result,
        )
    except httpx.TimeoutException as exc:
        raise MineruError("MinerU 状态查询超时") from exc
    except httpx.RequestError as exc:
        raise MineruError("MinerU 状态查询网络请求失败") from exc
    finally:
        if own_client:
            await http.aclose()


def _normalise_name(name: str) -> str:
    value = str(PurePosixPath(name.replace("\\", "/")))
    parts = [part for part in value.lstrip("/").split("/") if part not in {"", ".", ".."}]
    return "/".join(parts)[:512] or "artifact"


def _artifact_type(name: str) -> str:
    lowered = name.casefold()
    suffix = PurePosixPath(lowered).suffix
    if suffix == ".md" or lowered.endswith("full.md"):
        return "markdown"
    if suffix == ".json":
        return "structure"
    # 图片单独成类。原先两个分支都返回 "asset"，_ASSET_SUFFIXES 和前端
    # artifactTypeLabel 里那条 image 分支都是死的，图片在界面上显示成
    # 英文原文 "asset"。
    if suffix in _ASSET_SUFFIXES:
        return "image"
    return "asset"


def _markdown_document(
    markdown: str, structured: Any = None
) -> ExtractionDocument:
    """使用 QA 统一 Markdown/JSON 归一化和分块算法。"""

    return parse_extracted_document(markdown, structured)


def _unzip_artifacts(zip_data: bytes) -> tuple[list[MineruArtifact], str | None, Any]:
    artifacts: list[MineruArtifact] = []
    markdown: str | None = None
    markdown_is_full = False
    structured: Any = None
    try:
        archive = ZipFile(BytesIO(zip_data))
    except (BadZipFile, OSError) as exc:
        raise MineruError("MinerU 结果 ZIP 无法读取") from exc
    with archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size > 100 * 1024 * 1024:
                continue
            source_name = _normalise_name(info.filename)
            content = archive.read(info)
            artifact_type = _artifact_type(source_name)
            artifacts.append(MineruArtifact(
                source_name=source_name, data=content, artifact_type=artifact_type,
                mime_type=mimetypes.guess_type(source_name)[0] or "application/octet-stream",
                metadata={"archive_member": source_name},
            ))
            if artifact_type == "markdown":
                # ZIP 成员顺序不保证 full.md 在前。先到先得会把分页 md 之类
                # 的旁支当正文，之后每一段、每个 chunk、每次 AI 抽取都跑在
                # 错的文本上；没有 full.md 时才退回第一个 markdown 成员。
                is_full = source_name.casefold().endswith("full.md")
                if markdown is None or (is_full and not markdown_is_full):
                    markdown = content.decode("utf-8-sig", errors="replace")
                    markdown_is_full = is_full
            elif artifact_type == "structure" and structured is None and (
                "content_list" in source_name.casefold()
                or "middle" in source_name.casefold()
                or "layout" in source_name.casefold()
            ):
                try:
                    import json

                    structured = json.loads(content.decode("utf-8-sig"))
                except (UnicodeDecodeError, ValueError):
                    structured = None
    return artifacts, markdown, structured


def poll_interval(poll_number: int) -> float:
    """第 ``poll_number`` 次轮询之后等待多久（``poll_number`` 从 1 开始）。"""

    return (
        MINERU_POLL_INTERVAL_SECONDS
        if poll_number <= MINERU_FAST_POLL_COUNT
        else MINERU_SLOW_POLL_INTERVAL_SECONDS
    )


async def _download_limited(http: httpx.AsyncClient, url: str, *, limit: int) -> bytes:
    """流式下载结果包并累计上限，不把未知大小的归档整体读进内存。

    只看 Content-Length 不够：它可能缺失，也可能不实。压缩炸弹能把 worker
    OOM 掉，而且每轮重试都会再下一次、再炸一次。原件上限 50MB，结果包还要
    装 Markdown、结构化 JSON 和全部图片，所以留了余量。
    """

    chunks: list[bytes] = []
    total = 0
    async with http.stream("GET", url, follow_redirects=True) as response:
        if response.status_code < 200 or response.status_code >= 300:
            raise MineruError(f"MinerU 下载结果 ZIP HTTP {response.status_code}")
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise MineruError(f"MinerU 结果包超过 {limit // 1024 // 1024}MB 上限")
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > limit:
                raise MineruError(f"MinerU 结果包超过 {limit // 1024 // 1024}MB 上限")
            chunks.append(chunk)
    return b"".join(chunks)


async def download_result(
    poll: MineruPollResult,
    *,
    client: httpx.AsyncClient | None = None,
) -> MineruResult:
    """下载已完成批次的 ZIP，并转换为统一 Markdown/raw block 结果。"""
    if poll.state != "done":
        raise MineruError(f"MinerU 任务尚未完成: {poll.state}")
    if not poll.full_zip_url:
        raise MineruError("MinerU 完成响应缺少 full_zip_url")
    http, own_client = await _with_client(client)
    try:
        # CDN 可能先返回 302；该请求不附加 MinerU Authorization，避免
        # 令牌随跨域跳转泄露。
        archive_bytes = await _download_limited(
            http, poll.full_zip_url, limit=MAX_RESULT_ARCHIVE_BYTES
        )
        artifacts, markdown, structured = _unzip_artifacts(archive_bytes)
        artifacts.insert(0, MineruArtifact(
            source_name="full.zip", data=archive_bytes, artifact_type="zip",
            mime_type="application/zip", metadata={"batch_id": poll.batch_id},
        ))
        if markdown is None and poll.markdown_url:
            markdown_response = await http.get(poll.markdown_url, follow_redirects=True)
            if 200 <= markdown_response.status_code < 300:
                markdown_data = bytes(markdown_response.content)
                markdown = markdown_data.decode("utf-8-sig", errors="replace")
                artifacts.append(MineruArtifact(
                    source_name="full.md", data=markdown_data, artifact_type="markdown",
                    mime_type="text/markdown", metadata={"download": "markdown_url"},
                ))
        if markdown is None:
            raise MineruError("MinerU 结果中未找到 full.md")
        task_id = poll.task_id or poll.batch_id
        document = _markdown_document(markdown, structured)
        statistics = {
            **document.statistics, "provider": "mineru", "batch_id": poll.batch_id,
            "task_id": task_id, "artifact_count": len(artifacts),
        }
        return MineruResult(
            task_id=task_id, batch_id=poll.batch_id, markdown=markdown,
            document=document, artifacts=tuple(artifacts), statistics=statistics,
        )
    except httpx.TimeoutException as exc:
        raise MineruError("MinerU 下载结果超时") from exc
    except httpx.RequestError as exc:
        raise MineruError("MinerU 下载结果网络请求失败") from exc
    finally:
        if own_client:
            await http.aclose()


async def persist_artifacts(
    result: MineruResult,
    file_id: Any,
    extraction_run_id: Any,
    rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """将产物写入 QA 对象存储，返回可直接构造 ORM 的字段。

    ``rows`` 传进来时就地追加，调用方在写入过程中就能看到已经落盘的键。
    对象存储不参与数据库事务，中途失败或被取消时这些对象没有 DB 记录、
    也没有任何回收路径，只能由调用方按这份进度清理；等函数返回再交出去
    就已经漏了。
    """

    output = rows if rows is not None else []
    for artifact in result.artifacts:
        source_name = _normalise_name(artifact.source_name)
        key = f"extraction-artifacts/{file_id}/{extraction_run_id}/{source_name}"
        await asyncio.to_thread(file_service.store_object, key, artifact.data, artifact.mime_type)
        output.append({
            "file_id": file_id, "extraction_run_id": extraction_run_id,
            "artifact_type": artifact.artifact_type, "source_name": source_name,
            "storage_key": key, "mime_type": artifact.mime_type,
            "size_bytes": artifact.size_bytes, "sha256": artifact.sha256,
            "artifact_metadata": {
                **artifact.metadata, "batch_id": result.batch_id, "task_id": result.task_id,
            },
        })
    return output


__all__ = [
    "MINERU_MODEL_VERSION", "MINERU_PARSER_VERSION", "MINERU_POLL_INTERVAL_SECONDS",
    "MineruArtifact", "MineruError", "MineruPollResult", "MineruResult",
    "MineruUploadSession", "download_result", "persist_artifacts", "poll_interval",
    "poll_result", "request_upload", "upload_bytes",
]
