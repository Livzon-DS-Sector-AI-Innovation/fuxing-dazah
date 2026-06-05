"""Feishu contact (department members, leaders) with Redis caching."""

import json
import logging

from app.core.config import get_settings
from app.core.redis import cache_get, cache_set

logger = logging.getLogger(__name__)

settings = get_settings()


async def _get_feishu_client():
    import lark_oapi as lark

    return (
        lark.Client.builder()
        .app_id(settings.FEISHU_APP_ID)
        .app_secret(settings.FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )


async def _get_tenant_token(client) -> str:
    import lark_oapi as lark
    from lark_oapi.api.auth.v3 import (
        InternalTenantAccessTokenRequest,
        InternalTenantAccessTokenRequestBody,
    )

    req = (
        InternalTenantAccessTokenRequest.builder()
        .request_body(
            InternalTenantAccessTokenRequestBody.builder()
            .app_id(settings.FEISHU_APP_ID)
            .app_secret(settings.FEISHU_APP_SECRET)
            .build()
        )
        .build()
    )
    resp = await client.auth.v3.internal_tenant_access_token.acreate(req)
    if not resp.success():
        raise RuntimeError(f"Failed to get tenant token: {resp.msg}")
    return resp.data.tenant_access_token


async def get_department_members(dept_id: str) -> list[dict]:
    """获取部门成员列表，优先读 Redis"""
    cache_key = f"feishu:dept:{dept_id}:members"
    cached = await cache_get(cache_key)
    if cached:
        return json.loads(cached)

    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

    import lark_oapi as lark
    from lark_oapi.api.contact.v3 import ListUserRequest

    all_members = []
    page_token = ""
    while True:
        req = (
            ListUserRequest.builder()
            .department_id(dept_id)
            .page_size(100)
            .page_token(page_token)
            .user_id_type("user_id")
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.contact.v3.user.alist(req)
        if not resp.success():
            logger.error("Failed to list users for dept %s: %s", dept_id, resp.msg)
            break

        raw = resp.raw_content
        if raw:
            data = json.loads(raw).get("data", {})
            items = data.get("items", [])
            for item in items:
                all_members.append({
                    "user_id": item.get("user_id", ""),
                    "name": item.get("name", ""),
                    "employee_no": item.get("employee_no", ""),
                    "department_id": dept_id,
                })
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        else:
            break

    await cache_set(cache_key, json.dumps(all_members, ensure_ascii=False), ex=86400)
    return all_members


async def get_department_leader(dept_id: str) -> dict | None:
    """获取部门主管"""
    cache_key = f"feishu:dept:{dept_id}:leader"
    cached = await cache_get(cache_key)
    if cached:
        return json.loads(cached)

    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

    import lark_oapi as lark
    from lark_oapi.api.contact.v3 import GetDepartmentRequest

    req = (
        GetDepartmentRequest.builder()
        .department_id(dept_id)
        .user_id_type("user_id")
        .build()
    )
    req.headers["Authorization"] = f"Bearer {token}"
    resp = await client.contact.v3.department.aget(req)
    if not resp.success():
        logger.error("Failed to get department %s: %s", dept_id, resp.msg)
        return None

    raw = resp.raw_content
    if raw:
        dept = json.loads(raw).get("data", {}).get("department", {})
        leader_id = dept.get("leader_user_id")
        if leader_id:
            result = {"user_id": leader_id}
            await cache_set(cache_key, json.dumps(result, ensure_ascii=False), ex=86400)
            return result

    return None


async def is_department_member(user_id: str, dept_id: str) -> bool:
    """检查用户是否为部门成员"""
    members = await get_department_members(dept_id)
    return any(m.get("user_id") == user_id for m in members)
