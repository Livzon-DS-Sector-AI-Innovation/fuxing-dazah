"""飞书审批实例客户端（职称评审：审批先行模式）。

- 按审批定义编码分页拉取实例 Code 列表（单次时间范围 ≤10 小时，自动分段）
- 拉取实例详情（状态 + 表单控件值）
凭证与多维表格客户端一致：优先 HR_TITLE_REVIEW_FEISHU_* 独立应用，缺省回落全局应用。
"""

import json
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.modules.hr.title_review.bitable_client import TitleReviewBitableError

logger = logging.getLogger(__name__)

# tenant_access_token 内存缓存：{app_id}: {token, 过期时间戳}（飞书 token 有效期约 2 小时）
_token_cache: dict[str, tuple[str, float]] = {}

TOKEN_BASE = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"


async def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    attempts: int = 2,
    timeout: float = 30,
) -> dict[str, Any]:
    """带一次重试的请求（飞书网络偶发抖动时提高成功率）。"""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as http:
                resp = await http.request(
                    method, url, headers=headers, params=params, json=json_body
                )
                return resp.json()
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                logger.warning("飞书请求失败重试: %s %s %s", method, url, type(exc).__name__)
                await _sleep_async(1)
    raise TitleReviewBitableError(
        f"飞书请求网络异常: {method} {url} {type(last_exc).__name__}"
    ) from last_exc


async def _sleep_async(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def _get_tenant_token() -> str:
    """获取审批独立应用（HR_TITLE_REVIEW_FEISHU_*）的 tenant_access_token，缺省回落全局应用。

    审批权限（approval:approval:readonly / approval:definition）开通在独立应用上，
    与多维表格读写使用的全局应用分离。token 内存缓存约 100 分钟。
    """
    settings = get_settings()
    app_id = settings.HR_TITLE_REVIEW_FEISHU_APP_ID or settings.FEISHU_APP_ID
    app_secret = settings.HR_TITLE_REVIEW_FEISHU_APP_SECRET or settings.FEISHU_APP_SECRET
    cache_key = f"{app_id}:{app_secret}"
    cached = _token_cache.get(cache_key)
    if cached and time.time() < cached[1]:
        return cached[0]
    data = await _request_with_retry(
        "POST", TOKEN_BASE, json_body={"app_id": app_id, "app_secret": app_secret}, timeout=15
    )
    token = data.get("tenant_access_token", "")
    if not token:
        raise TitleReviewBitableError("获取飞书token失败: " + json.dumps(data))
    _token_cache[cache_key] = (str(token), time.time() + 100 * 60)
    return str(token)

__all__ = [
    "list_instance_codes",
    "get_instance",
    "form_widgets_to_fields",
    "TitleReviewBitableError",
]

APPROVAL_BASE = "https://open.feishu.cn/open-apis/approval/v4"

MAX_RANGE_HOURS = 10  # 单次查询时间范围上限（官方限制）


async def list_instance_codes(
    approval_code: str,
    start_ms: int,
    end_ms: int,
) -> list[str]:
    """按审批定义编码拉取实例 Code（自动分页 + 按 10 小时分段）。"""
    token = await _get_tenant_token()
    instance_codes: list[str] = []
    segment = MAX_RANGE_HOURS * 3600 * 1000
    seg_start = start_ms
    while seg_start < end_ms:
        seg_end = min(seg_start + segment, end_ms)
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "approval_code": approval_code,
                "start_time": str(seg_start),
                "end_time": str(seg_end),
                "page_size": 100,
            }
            if page_token:
                params["page_token"] = page_token
            data = await _request_with_retry(
                "GET",
                f"{APPROVAL_BASE}/instances",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if data.get("code") != 0:
                raise TitleReviewBitableError(
                    f"审批实例列表查询失败: code={data.get('code')} msg={data.get('msg')}"
                )
            result = data.get("data") or {}
            instance_codes.extend(result.get("instance_code_list") or [])
            if not result.get("has_more"):
                break
            page_token = result.get("page_token")
            if not page_token:
                break
        seg_start = seg_end
    return instance_codes


async def get_instance(instance_code: str) -> dict[str, Any]:
    """获取审批实例详情，返回 {status, form: [{id,name,type,value,...}]}。

    form 字段为 JSON 字符串（控件列表），在此解析为 list。
    """
    token = await _get_tenant_token()
    data = await _request_with_retry(
        "GET",
        f"{APPROVAL_BASE}/instances/{instance_code}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if data.get("code") != 0:
        raise TitleReviewBitableError(
            f"审批实例详情查询失败: code={data.get('code')} msg={data.get('msg')}"
        )
    result = data.get("data") or {}
    form_raw = result.get("form") or "[]"
    if isinstance(form_raw, str):
        try:
            form = json.loads(form_raw)
        except (TypeError, ValueError):
            form = []
    else:
        form = form_raw
    return {
        "status": result.get("status"),
        "start_time": result.get("start_time"),
        "form": form,
    }


def form_widgets_to_fields(form: list[dict[str, Any]]) -> dict[str, Any]:
    """审批表单控件列表 → {控件名: 值}（附件控件做元数据容错）。"""
    fields: dict[str, Any] = {}
    for widget in form:
        if not isinstance(widget, dict):
            continue
        name = widget.get("name") or widget.get("custom_id") or ""
        value = widget.get("value")
        if not name:
            continue
        if widget.get("type") in ("attachment", "attachmentV2"):
            fields[name] = _normalize_attachment_value(value)
        else:
            fields[name] = value
    return fields


def _normalize_attachment_value(value: Any) -> list[dict[str, Any]] | None:
    """审批附件值 → 元数据列表（容错提取 file_token/name/size/url）。"""
    if not isinstance(value, list):
        return None
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            entry: dict[str, Any] = {}
            for key in ("file_token", "name", "size", "title", "url", "file_size"):
                if item.get(key) is not None:
                    entry[key] = item.get(key)
            if entry:
                result.append(entry)
    return result or None
