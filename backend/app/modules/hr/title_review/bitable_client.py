"""职称评审多维表格（Bitable）API 客户端（v2 绑定现有表模式）。

使用全局飞书应用凭证（FEISHU_APP_ID/SECRET），纯 httpx 调用。
活动绑定 HR 在飞书建好的申报表/投票表（app_token/table_id 按活动入参），
本客户端不负责建表（原型表格结构复杂，自动建表易漂移）。
"""

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"
DRIVE_BASE = "https://open.feishu.cn/open-apis/drive/v1"
TOKEN_BASE = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

# tenant_access_token 内存缓存（飞书 token 有效期约 2 小时，缓存 100 分钟）
_token_cache: tuple[str, float] | None = None


class TitleReviewBitableError(Exception):
    """多维表格 API 调用失败。"""


async def _get_tenant_token() -> str:
    """获取全局应用（公司应用）的 tenant_access_token（内存缓存）。

    多维表格读写使用全局应用：其 bitable 权限已开通且已加入 Base 协作者。
    审批同步走 approval_client（独立应用凭证，见该模块）。
    """
    global _token_cache
    if _token_cache and time.time() < _token_cache[1]:
        return _token_cache[0]
    settings = get_settings()
    data = await _request_raw(
        "POST",
        TOKEN_BASE,
        json_body={
            "app_id": settings.FEISHU_APP_ID,
            "app_secret": settings.FEISHU_APP_SECRET,
        },
        timeout=15,
    )
    token = data.get("tenant_access_token", "")
    if not token:
        raise TitleReviewBitableError("获取飞书token失败: " + json.dumps(data))
    _token_cache = (str(token), time.time() + 100 * 60)
    return str(token)


async def _request_raw(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempts: int = 2,
    timeout: float = 30,
) -> dict[str, Any]:
    """带一次重试的原始请求（飞书网络偶发抖动时提高成功率）。"""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.request(
                    method, url, json=json_body, params=params, headers=headers
                )
                if resp.status_code in (429,) or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                return resp.json()
        except Exception as exc:  # noqa: BLE001 — 传输/解析/限流统一重试
            last_exc = exc
            if attempt < attempts - 1:
                logger.warning("飞书请求失败重试: %s %s %s", method, url, type(exc).__name__)
                await asyncio.sleep(1)
    raise TitleReviewBitableError(
        f"多维表格 API 网络异常: {method} {url} {type(last_exc).__name__}"
    ) from last_exc


async def _request(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一请求入口：取 token → 调用 → 校验 code=0。

    网络层异常（超时/断连）统一包装为 TitleReviewBitableError，
    由上层对账按业务失败处理（记录 errors 而非 500）。
    """
    token = await _get_tenant_token()
    headers = {"Authorization": f"Bearer {token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    data = await _request_raw(
        method, url, json_body=json_body, params=params, headers=headers
    )
    if data.get("code") != 0:
        raise TitleReviewBitableError(
            f"多维表格 API 失败: {method} {url} code={data.get('code')} msg={data.get('msg')}"
        )
    return dict(data.get("data") or {})


async def subscribe_bitable(app_token: str) -> None:
    """订阅多维表格变更事件（必须订阅才能收到 record_changed 事件）。"""
    await _request(
        "POST",
        f"{DRIVE_BASE}/files/{app_token}/subscribe",
        params={"file_type": "bitable"},
    )


async def batch_create_records(
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
) -> list[str]:
    """批量写入记录（≤500/批），返回记录 id 列表（按顺序）。"""
    if not records:
        return []
    created: list[str] = []
    for i in range(0, len(records), 500):
        chunk = records[i : i + 500]
        data = await _request(
            "POST",
            f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records/batch_create",
            json_body={"records": [{"fields": r} for r in chunk]},
        )
        created.extend(
            str(item.get("record_id", "")) for item in data.get("records", [])
        )
    return created


async def update_record(
    app_token: str,
    table_id: str,
    record_id: str,
    fields: dict[str, Any],
) -> None:
    """更新单条记录。"""
    await _request(
        "PUT",
        f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records/{record_id}",
        json_body={"fields": fields},
    )


async def list_all_records(
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    filter_expr: str | None = None,
) -> list[dict[str, Any]]:
    """分页拉取全部记录，返回 [{"record_id": str, "fields": {中文列名: 值}}]。

    filter_expr 为飞书筛选表达式，如 `CurrentValue.[姓名]="张三"`。
    """
    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "page_size": page_size,
            "field_name_type": "name",  # 用中文列名做 key，直接与原型字段名匹配
        }
        if page_token:
            params["page_token"] = page_token
        if filter_expr:
            params["filter"] = filter_expr
        data = await _request(
            "GET",
            f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records",
            params=params,
        )
        items = data.get("items") or []  # 空表时飞书返回 items: null
        all_items.extend(items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return all_items


async def list_tables(app_token: str, *, page_size: int = 100) -> list[dict[str, Any]]:
    """列出 Base 内全部数据表，返回 [{table_id, name, ...}]。"""
    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        data = await _request(
            "GET",
            f"{BITABLE_BASE}/apps/{app_token}/tables",
            params=params,
        )
        items = data.get("items") or []  # 空 Base 时飞书返回 items: null
        all_items.extend(items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return all_items


async def list_fields(
    app_token: str, table_id: str, *, page_size: int = 100
) -> list[dict[str, Any]]:
    """列出表格全部字段，返回 [{field_id, field_name, type, ...}]。"""
    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        data = await _request(
            "GET",
            f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/fields",
            params=params,
        )
        items = data.get("items") or []  # 空表时飞书返回 items: null
        all_items.extend(items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return all_items


async def create_grid_view(
    app_token: str,
    table_id: str,
    view_name: str,
    filter_info: dict[str, Any] | None = None,
) -> str:
    """创建表格视图（评委个人视图：按评审人编号筛选），返回 view_id。"""
    payload: dict[str, Any] = {"view_name": view_name, "view_type": "grid"}
    if filter_info:
        payload["filter_info"] = filter_info
    data = await _request(
        "POST",
        f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/views",
        json_body=payload,
    )
    return str(data.get("view", {}).get("view_id", ""))
