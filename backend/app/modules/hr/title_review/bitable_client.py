"""职称评审多维表格（Bitable）API 客户端（v2 绑定现有表模式）。

使用全局飞书应用凭证（FEISHU_APP_ID/SECRET），纯 httpx 调用。
活动绑定 HR 在飞书建好的申报表/投票表（app_token/table_id 按活动入参），
本客户端不负责建表（原型表格结构复杂，自动建表易漂移）。
"""

import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"
DRIVE_BASE = "https://open.feishu.cn/open-apis/drive/v1"


class TitleReviewBitableError(Exception):
    """多维表格 API 调用失败。"""


async def _get_tenant_token() -> str:
    """获取全局应用（公司应用）的 tenant_access_token。

    多维表格读写使用全局应用：其 bitable 权限已开通且已加入 Base 协作者。
    审批同步走 approval_client（独立应用凭证，见该模块）。
    """
    settings = get_settings()
    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": settings.FEISHU_APP_ID,
                "app_secret": settings.FEISHU_APP_SECRET,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("tenant_access_token", "")
        if not token:
            raise TitleReviewBitableError("获取飞书token失败: " + json.dumps(data))
        return str(token)


async def _request(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一请求入口：取 token → 调用 → 校验 code=0。"""
    token = await _get_tenant_token()
    headers = {"Authorization": f"Bearer {token}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.request(
            method, url, headers=headers, json=json_body, params=params
        )
        data = resp.json()
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
) -> list[dict[str, Any]]:
    """分页拉取全部记录，返回 [{"record_id": str, "fields": {中文列名: 值}}]。"""
    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {
            "page_size": page_size,
            "field_name_type": "name",  # 用中文列名做 key，直接与原型字段名匹配
        }
        if page_token:
            params["page_token"] = page_token
        data = await _request(
            "GET",
            f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records",
            params=params,
        )
        items = data.get("items", [])
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
        items = data.get("items", [])
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
