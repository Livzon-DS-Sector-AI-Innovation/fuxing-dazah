"""点检表 Bitable 数据端口：读记录 / 下载附件 / 上传回填。

走安全模块专属飞书凭证（安全管理机器人）+ httpx 直调 OpenAPI（房内
list_feishu_chats 模式）。解析逻辑与 IO 分离：parse_* / ensure_ok /
build_append_body 为纯函数可单测，IO 函数保持薄。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from app.modules.safety.feishu.client import get_safety_tenant_token

logger = logging.getLogger(__name__)

_BASE_URL = "https://open.feishu.cn"

# 目标表：灭火器点检「数据表」，可用环境变量覆盖（本地/演练指向别表时用）
FIRE_INSPECTION_APP_TOKEN = os.getenv(
    "SAFETY_FIRE_INSPECTION_APP_TOKEN", "BlktbbYg1abyIesUQ17cYFqrn4e"
)
FIRE_INSPECTION_TABLE_ID = os.getenv(
    "SAFETY_FIRE_INSPECTION_TABLE_ID", "tblUB2sT3b3GBerU"
)

# 「巡检记录」附件字段 ID（回填目标），随表覆盖
FIELD_REPORT_ID = os.getenv("SAFETY_FIRE_INSPECTION_REPORT_FIELD_ID", "fldpZSHrTd")

_PAGE_SIZE = 500
# base v3 新端点用字符串码，v1 用整数 0；缺 code 视为成功
_OK_CODES: tuple[object, ...] = (0, "0", "Ok", "Success", "ok", "success")


class BitableError(RuntimeError):
    """Bitable/drive 调用失败（含业务错误码）。"""


def ensure_ok(envelope: dict[str, Any]) -> dict[str, Any]:
    """校验响应信封；失败抛 BitableError，成功返回原信封。"""
    code = envelope.get("code", 0)
    if code not in _OK_CODES:
        raise BitableError(f"飞书接口失败 code={code} msg={envelope.get('msg')}")
    return envelope


def parse_search_items(data: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, str | None]:
    """解析 records/search 的 data 段：记录列表、是否还有下一页、翻页 token。"""
    items = data.get("items") or []
    return list(items), bool(data.get("has_more")), data.get("page_token")


def parse_upload_token(data: dict[str, Any]) -> str:
    """解析 upload_all 的 data 段，取 file_token。"""
    token = str((data or {}).get("file_token") or "").strip()
    if not token:
        raise BitableError("上传响应缺少 file_token")
    return token


def parse_get_attachments(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    """解析 base v3 get_attachments：{record_id: {file_token: extra_info}}。

    extra_info 是下载该附件必须携带的鉴权参数。
    """
    result: dict[str, dict[str, str]] = {}
    for record_id, fields in (data or {}).get("attachments", {}).items():
        token_extra: dict[str, str] = {}
        for entries in (fields or {}).values():
            for entry in entries or []:
                token = str(entry.get("file_token") or "")
                extra = str(entry.get("extra_info") or "")
                if token and extra:
                    token_extra[token] = extra
        if token_extra:
            result[str(record_id)] = token_extra
    return result


def build_append_body(
    record_id: str,
    field_id: str,
    file_tokens: list[str],
) -> dict[str, Any]:
    """构造 base v3 append_attachments 请求体（原生追加语义，不动既有附件）。"""
    return {
        "attachments": {
            record_id: {
                field_id: [{"file_token": token} for token in file_tokens],
            }
        }
    }


@asynccontextmanager
async def _own_client(http: httpx.AsyncClient | None) -> AsyncIterator[httpx.AsyncClient]:
    """注入则复用，否则自建并负责关闭（IO 函数共享的生命周期样板）。"""
    if http is not None:
        yield http
        return
    client = httpx.AsyncClient(timeout=60)
    try:
        yield client
    finally:
        await client.aclose()


async def search_records(
    tenant_token: str,
    app_token: str,
    table_id: str,
    http: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """拉取全表记录（records/search 自动翻页），返回原始 items。"""
    async with _own_client(http) as client:
        records: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": _PAGE_SIZE}
            if page_token:
                body["page_token"] = page_token
            resp = await client.post(
                f"{_BASE_URL}/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                headers={"Authorization": f"Bearer {tenant_token}"},
                json=body,
            )
            envelope = ensure_ok(resp.json())
            items, has_more, next_token = parse_search_items(envelope.get("data") or {})
            records.extend(items)
            if not has_more or not next_token:
                return records
            page_token = next_token


async def get_attachment_extras(
    tenant_token: str,
    app_token: str,
    table_id: str,
    record_ids: list[str],
    http: httpx.AsyncClient | None = None,
) -> dict[str, dict[str, str]]:
    """批量取记录附件的 extra_info（Base 附件下载必带，见官方下载流程）。"""
    if not record_ids:
        return {}
    async with _own_client(http) as client:
        resp = await client.post(
            f"{_BASE_URL}/open-apis/base/v3/bases/{app_token}/tables/{table_id}/get_attachments",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json={"record_id_list": record_ids},
        )
        envelope = ensure_ok(resp.json())
        return parse_get_attachments(envelope.get("data") or {})


async def download_media(
    tenant_token: str,
    file_token: str,
    extra: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> bytes:
    """下载附件字节（照片/签字）。Base 附件必须带 extra_info。"""
    async with _own_client(http) as client:
        params = {"extra": extra} if extra else None
        resp = await client.get(
            f"{_BASE_URL}/open-apis/drive/v1/medias/{file_token}/download",
            headers={"Authorization": f"Bearer {tenant_token}"},
            params=params,
        )
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            ensure_ok(resp.json())
        resp.raise_for_status()
        return resp.content


async def upload_attachment(
    tenant_token: str,
    app_token: str,
    file_name: str,
    content: bytes,
    http: httpx.AsyncClient | None = None,
) -> str:
    """上传 PDF 字节为 Base 附件，返回 file_token。"""
    async with _own_client(http) as client:
        resp = await client.post(
            f"{_BASE_URL}/open-apis/drive/v1/medias/upload_all",
            headers={"Authorization": f"Bearer {tenant_token}"},
            data={
                "file_name": file_name,
                "parent_type": "bitable_file",
                "parent_node": app_token,
                "size": str(len(content)),
            },
            files={"file": (file_name, content, "application/pdf")},
        )
        envelope = ensure_ok(resp.json())
        return parse_upload_token(envelope.get("data") or {})


async def append_attachments(
    tenant_token: str,
    app_token: str,
    table_id: str,
    record_id: str,
    field_id: str,
    file_tokens: list[str],
    http: httpx.AsyncClient | None = None,
) -> None:
    """把 file_token 追加进记录附件字段（不改动既有附件项）。"""
    async with _own_client(http) as client:
        resp = await client.post(
            f"{_BASE_URL}/open-apis/base/v3/bases/{app_token}/tables/{table_id}/append_attachments",
            headers={"Authorization": f"Bearer {tenant_token}"},
            json=build_append_body(record_id, field_id, file_tokens),
        )
        ensure_ok(resp.json())


async def load_tenant_token() -> str:
    """对外统一的 token 入口（安全模块独立凭证）。"""
    return await get_safety_tenant_token()
