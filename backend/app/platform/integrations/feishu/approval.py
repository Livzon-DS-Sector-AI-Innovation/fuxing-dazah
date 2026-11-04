"""飞书审批（Approval）OpenAPI 适配器（平台集成能力）。

- 按审批定义编码分页拉取实例 Code 列表（单次时间范围 ≤10 小时，自动分段）
- 拉取实例详情（状态 + 表单控件值）
凭证可传入独立应用（如职称评审审批应用），缺省回落全局 FEISHU_* 应用。
"""

import json
import logging
from typing import Any

from app.platform.integrations.feishu.http import (
    FeishuAPIError,
    feishu_request,
    get_tenant_token,
)

logger = logging.getLogger(__name__)

APPROVAL_BASE = "https://open.feishu.cn/open-apis/approval/v4"
MAX_RANGE_HOURS = 10  # 单次查询时间范围上限（官方限制）


class ApprovalAPIError(FeishuAPIError):
    """飞书审批 API 调用失败。"""


async def list_instance_codes(
    approval_code: str,
    start_ms: int,
    end_ms: int,
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> list[str]:
    """按审批定义编码拉取实例 Code（自动分页 + 按 10 小时分段）。"""
    try:
        token = await get_tenant_token(app_id=app_id, app_secret=app_secret)
    except FeishuAPIError as exc:
        raise ApprovalAPIError(str(exc)) from exc
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
            try:
                data = await feishu_request(
                    "GET",
                    f"{APPROVAL_BASE}/instances",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
            except FeishuAPIError as exc:
                raise ApprovalAPIError(str(exc)) from exc
            result = data.get("data") or {}
            instance_codes.extend(result.get("instance_code_list") or [])
            if not result.get("has_more"):
                break
            page_token = result.get("page_token")
            if not page_token:
                break
        seg_start = seg_end
    return instance_codes


async def get_instance(
    instance_code: str,
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
) -> dict[str, Any]:
    """获取审批实例详情，返回 {status, start_time, form: [...]}。

    form 字段为 JSON 字符串（控件列表），在此解析为 list。
    """
    try:
        token = await get_tenant_token(app_id=app_id, app_secret=app_secret)
        data = await feishu_request(
            "GET",
            f"{APPROVAL_BASE}/instances/{instance_code}",
            headers={"Authorization": f"Bearer {token}"},
        )
    except FeishuAPIError as exc:
        raise ApprovalAPIError(str(exc)) from exc
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


# ── 创建审批实例（五金库领料审批 M3 首次落地；原辅料领料审批可直接复用）──


async def create_instance(
    approval_code: str,
    user_id: str,
    form: list[dict[str, Any]] | str,
    *,
    app_id: str | None = None,
    app_secret: str | None = None,
    uuid_idempotency: str | None = None,
    node_approver_user_id_list: dict[str, list[str]] | None = None,
    node_approver_open_id_list: dict[str, list[str]] | None = None,
) -> str:
    """创建审批实例，返回 instance_code。

    - 幂等：``uuid_idempotency`` 传入同一 uuid 重复提交返回同一实例
      （官方 x-lark-uuid 头）；业务侧持久化 uuid 实现重试不重单。
    - form：控件 JSON（list[dict]）或已序列化的 JSON 字符串（官方要求
      form 为 JSON 字符串，list 输入内部 json.dumps 兜底）。
    - 凭证：缺省回落全局 FEISHU_*；五金库走 safety 应用（2026-10-28
      已拍板口径，approval:instance 权限已具备）。
    - 审批人：node_approver_user_id_list / node_approver_open_id_list
      按节点 key 指定（定义流程为「发起人自选」时必传）。
    """
    import uuid as _uuid

    try:
        token = await get_tenant_token(app_id=app_id, app_secret=app_secret)
        body: dict[str, Any] = {
            "approval_code": approval_code,
            "user_id": user_id,
            "form": form if isinstance(form, str) else json.dumps(form, ensure_ascii=False),
        }
        if node_approver_user_id_list:
            body["node_approver_user_id_list"] = node_approver_user_id_list
        if node_approver_open_id_list:
            body["node_approver_open_id_list"] = node_approver_open_id_list
        data = await feishu_request(
            "POST",
            f"{APPROVAL_BASE}/instances",
            headers={
                "Authorization": f"Bearer {token}",
                "x-lark-uuid": uuid_idempotency or str(_uuid.uuid4()),
            },
            json_body=body,
        )
    except FeishuAPIError as exc:
        raise ApprovalAPIError(str(exc)) from exc
    instance_code = (data.get("data") or {}).get("instance_code", "")
    if not instance_code:
        raise ApprovalAPIError(f"创建审批实例成功但未返回 instance_code: {data}")
    logger.info(
        "飞书审批实例已创建: approval_code=%s instance_code=%s user=%s",
        approval_code, instance_code, user_id,
    )
    return instance_code
