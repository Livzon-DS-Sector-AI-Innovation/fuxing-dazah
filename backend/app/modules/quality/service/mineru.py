"""MinerU VLM 适配器（质量模块自建，参照 qa 模块 mineru 适配器协议，不跨模块 import）。

仅封装与 MinerU 服务的 HTTP 交互（申请上传地址 → PUT 上传字节 → 轮询结果 →
下载 full.md）；峰表提取等业务解析在 chromatogram.py。
"""

import asyncio
import hashlib
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import httpx

from app.core.config import get_settings

MINERU_BASE_URL = "https://mineru.net/api/v4"
MINERU_MODEL_VERSION = "vlm"
MINERU_POLL_SECONDS = 3.0
MINERU_MAX_POLLS = 60


class ChromatogramParseError(RuntimeError):
    """图谱解析失败（凭证/网络/服务端错误/超时）。"""


def _settings_token() -> str:
    settings = get_settings()
    token = settings.QA_MD_EXTRACT_API_TOKEN.strip()
    if not token:
        raise ChromatogramParseError("MinerU API token 未配置（QA_MD_EXTRACT_API_TOKEN）")
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _check_body(body: dict[str, Any], operation: str) -> dict[str, Any]:
    code = body.get("code")
    if code not in (None, 0, "0"):
        raise ChromatogramParseError(f"MinerU {operation} 失败: {str(body.get('msg') or '')[:300]}")
    payload = body.get("data")
    if not isinstance(payload, dict):
        raise ChromatogramParseError(f"MinerU {operation} 响应缺少 data")
    return payload


async def parse_chromatogram_markdown(data: bytes, filename: str) -> str:
    """MinerU VLM 四步调用，返回结果包中的 full.md 正文。"""
    token = _settings_token()
    headers = _auth_headers(token) | {"Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=120) as http:
            # 1. 申请上传地址
            data_id = hashlib.sha256(data).hexdigest()
            resp = await http.post(
                f"{MINERU_BASE_URL}/file-urls/batch",
                headers=headers,
                json={
                    "files": [{"name": filename, "data_id": data_id}],
                    "model_version": MINERU_MODEL_VERSION,
                },
            )
            payload = _check_body(resp.json(), "申请上传地址")
            batch_id = str(payload.get("batch_id") or "")
            urls = payload.get("file_urls")
            upload_url = str(urls[0] or "") if isinstance(urls, list) and urls else ""
            if not batch_id or not upload_url:
                raise ChromatogramParseError("MinerU 申请上传地址响应缺少 batch_id/file_urls")
            # 2. 上传字节（签名地址，不带 API token）
            resp = await http.put(upload_url, content=data)
            if resp.status_code < 200 or resp.status_code >= 300:
                raise ChromatogramParseError(f"MinerU 文件上传 HTTP {resp.status_code}")
            # 3. 轮询结果
            state = "pending"
            item: dict[str, Any] = {}
            for _ in range(MINERU_MAX_POLLS):
                await asyncio.sleep(MINERU_POLL_SECONDS)
                resp = await http.get(
                    f"{MINERU_BASE_URL}/extract-results/batch/{batch_id}", headers=headers,
                )
                payload = _check_body(resp.json(), "查询解析结果")
                values = payload.get("extract_result")
                if isinstance(values, dict):
                    candidates = [values]
                elif isinstance(values, list):
                    candidates = [v for v in values if isinstance(v, dict)]
                else:
                    candidates = []
                item = next(
                    (v for v in candidates if str(v.get("file_name") or "") == filename),
                    candidates[0] if candidates else {},
                )
                state = str(item.get("state") or "pending").casefold()
                if state in ("done", "failed"):
                    break
            if state != "done":
                raise ChromatogramParseError(
                    f"MinerU 解析未完成（{state}）: {str(item.get('err_msg') or '')[:200]}"
                )
            zip_url = str(item.get("full_zip_url") or "")
            if not zip_url:
                raise ChromatogramParseError("MinerU 结果缺少 full_zip_url")
            # 4. 下载结果包（优先带 token，失败回落裸 URL）
            resp = await http.get(zip_url, headers=headers)
            if resp.status_code != 200:
                resp = await http.get(zip_url)
            if resp.status_code != 200:
                raise ChromatogramParseError(f"MinerU 结果下载 HTTP {resp.status_code}")
            zip_data = resp.content
    except httpx.TimeoutException as exc:
        raise ChromatogramParseError("MinerU 请求超时") from exc
    except httpx.RequestError as exc:
        raise ChromatogramParseError("MinerU 网络请求失败") from exc
    try:
        archive = ZipFile(BytesIO(zip_data))
    except Exception as exc:  # noqa: BLE001 — zip 损坏统一转业务错误
        raise ChromatogramParseError("MinerU 结果 ZIP 无法读取") from exc
    with archive:
        markdown: str | None = None
        markdown_is_full = False
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".md"):
                continue
            is_full = info.filename.casefold().endswith("full.md")
            if markdown is None or (is_full and not markdown_is_full):
                markdown = archive.read(info).decode("utf-8-sig", errors="replace")
                markdown_is_full = is_full
    if markdown is None:
        raise ChromatogramParseError("MinerU 结果中未找到 Markdown 正文")
    return markdown
