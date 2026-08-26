"""飞书多维表格（Bitable）OpenAPI 适配器（平台集成能力）。

供业务模块调用：读写绑定现有表格的记录/字段/视图、订阅变更事件。
token 缓存与重试统一走 http.py；业务模块不再自行拼装飞书 HTTP 请求。
"""

from typing import Any

from app.platform.integrations.feishu.http import (
    FeishuAPIError,
    feishu_request,
    get_tenant_token,
)

BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"
DRIVE_BASE = "https://open.feishu.cn/open-apis/drive/v1"


class BitableAPIError(FeishuAPIError):
    """多维表格 API 调用失败。"""


async def _request(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> dict[str, Any]:
    """统一请求入口：取 token → 调用 → 校验 code=0 → 返回 data 段。

    应用凭证缺省回落全局 FEISHU_*；业务模块可传入独立应用凭证。
    网络层异常统一包装为 BitableAPIError，由上层对账按业务失败处理
    （记录 errors 而非 500）。
    """
    try:
        token = await get_tenant_token(app_id, app_secret)
        headers = {"Authorization": f"Bearer {token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        data = await feishu_request(
            method, url, json_body=json_body, params=params, headers=headers
        )
    except FeishuAPIError as exc:
        raise BitableAPIError(str(exc)) from exc
    return dict(data.get("data") or {})


async def subscribe_bitable(
    app_token: str, *, app_id: str | None = None, app_secret: str | None = None
) -> None:
    """订阅多维表格变更事件（必须订阅才能收到 record_changed 事件）。"""
    await _request(
        "POST",
        f"{DRIVE_BASE}/files/{app_token}/subscribe",
        params={"file_type": "bitable"},
        app_id=app_id,
        app_secret=app_secret,
    )


async def batch_create_records(
    app_token: str,
    table_id: str,
    records: list[dict[str, Any]],
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
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
            app_id=app_id,
            app_secret=app_secret,
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
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> None:
    """更新单条记录。"""
    await _request(
        "PUT",
        f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records/{record_id}",
        json_body={"fields": fields},
        app_id=app_id,
        app_secret=app_secret,
    )


async def list_all_records(
    app_token: str,
    table_id: str,
    *,
    page_size: int = 500,
    filter_expr: str | None = None,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> list[dict[str, Any]]:
    """分页拉取全部记录，返回 [{"record_id": str, "fields": {中文列名: 值}}]。

    filter_expr 为飞书筛选表达式，如 `CurrentValue.[姓名]="张三"`。
    """
    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        if filter_expr:
            params["filter"] = filter_expr
        data = await _request(
            "GET",
            f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/records",
            params=params,
            app_id=app_id,
            app_secret=app_secret,
        )
        items = data.get("items") or []  # 空表时飞书返回 items: null
        all_items.extend(items)
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")
        if not page_token:
            break
    return all_items


async def list_tables(
    app_token: str,
    *,
    page_size: int = 100,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> list[dict[str, Any]]:
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
            app_id=app_id,
            app_secret=app_secret,
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
    app_token: str,
    table_id: str,
    *,
    page_size: int = 100,
    app_id: str | None = None,
    app_secret: str | None = None,
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
            app_id=app_id,
            app_secret=app_secret,
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
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> str:
    """创建表格视图（评委个人视图：按评审人编号筛选），返回 view_id。"""
    payload: dict[str, Any] = {"view_name": view_name, "view_type": "grid"}
    if filter_info:
        payload["filter_info"] = filter_info
    data = await _request(
        "POST",
        f"{BITABLE_BASE}/apps/{app_token}/tables/{table_id}/views",
        json_body=payload,
        app_id=app_id,
        app_secret=app_secret,
    )
    return str(data.get("view", {}).get("view_id", ""))
