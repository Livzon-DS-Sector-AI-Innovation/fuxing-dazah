"""Feishu contact: departments, users with Redis caching."""

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
    import json as _json

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
    resp = await client.auth.v3.tenant_access_token.ainternal(req)
    if not resp.success():
        raise RuntimeError(
            f"Failed to get tenant token: code={resp.code}, msg={resp.msg}",
        )
    if resp.raw and resp.raw.content:
        data = _json.loads(resp.raw.content.decode("utf-8"))
        return data.get("tenant_access_token", "")
    raise RuntimeError("Empty tenant token response")


# ── Department helpers ──────────────────────────────────────────────


async def get_all_departments() -> list[dict]:
    """BFS 递归获取全公司所有部门（含名称），包括叶子节点。

    返回扁平列表。
    """
    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

    from lark_oapi.api.contact.v3 import ListDepartmentRequest

    all_depts: list[dict] = []
    # BFS: 从根出发，逐层获取子部门
    queue: list[tuple[str, str]] = [("0", "")]
    visited: set[str] = {"0"}

    while queue:
        parent_id, parent_oid = queue.pop(0)

        page_token = ""
        while True:
            req = (
                ListDepartmentRequest.builder()
                .department_id_type("open_department_id")
                .parent_department_id(parent_id)
                .fetch_child(False)
                .page_size(50)
                .page_token(page_token)
                .build()
            )
            req.headers["Authorization"] = f"Bearer {token}"
            resp = await client.contact.v3.department.alist(req)
            raw = resp.raw.content if resp.raw else None
            if not raw:
                break
            data = json.loads(raw.decode("utf-8")).get("data", {})
            for it in data.get("items", []):
                oid = it.get("open_department_id", "")
                if not oid or oid in visited:
                    continue
                visited.add(oid)
                name = it.get("name", "") or oid
                order_str = it.get("order", "0") or "0"
                try:
                    order_val = int(order_str)
                except (ValueError, TypeError):
                    order_val = 0
                all_depts.append({
                    "department_id": oid,
                    "name": name,
                    "parent_department_id": parent_oid if parent_id != "0" else "",
                    "leader_user_id": it.get("leader_user_id", "") or "",
                    "member_count": it.get("member_count", 0) or 0,
                    "status_is_deleted": False,
                    "order": order_val,
                })
                # 继续递归子部门
                queue.append((oid, oid))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")

    logger.info("Fetched %d departments from Feishu (BFS)", len(all_depts))
    return all_depts


async def get_department_members(dept_id: str) -> list[dict]:
    """获取部门成员列表，优先读 Redis"""
    cache_key = f"feishu:dept:{dept_id}:members"
    cached = await cache_get(cache_key)
    if cached:
        return json.loads(cached)

    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

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

        raw = resp.raw.content if resp.raw else None
        if raw:
            data = json.loads(raw.decode("utf-8")).get("data", {})
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

    raw = resp.raw.content if resp.raw else None
    if raw:
        dept = json.loads(raw.decode("utf-8")).get("data", {}).get("department", {})
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


# ── User helpers ────────────────────────────────────────────────────


async def get_all_users() -> list[dict]:
    """获取所有可见用户（全公司范围，分页）。

    每个元素包含 user_id, open_id, name, employee_no, email, mobile,
    department_ids, job_title, positions, department_path 等。
    """
    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

    from lark_oapi.api.contact.v3 import ListUserRequest

    all_users: list[dict] = []
    page_token = ""
    while True:
        req = (
            ListUserRequest.builder()
            .user_id_type("user_id")
            .page_size(100)
            .page_token(page_token)
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.contact.v3.user.alist(req)
        raw = resp.raw.content if resp.raw else None
        if raw:
            data = json.loads(raw.decode("utf-8")).get("data", {})
            for u in data.get("items", []):
                all_users.append({
                    "user_id": u.get("user_id", ""),
                    "open_id": u.get("open_id", ""),
                    "name": u.get("name", ""),
                    "employee_no": u.get("employee_no", ""),
                    "email": u.get("email", ""),
                    "mobile": u.get("mobile", ""),
                    "job_title": u.get("job_title", ""),
                    "department_ids": u.get("department_ids", []),
                })
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        else:
            break

    logger.info("Fetched %d users from Feishu", len(all_users))
    return all_users


async def find_users_by_department(department_id: str) -> list[dict]:
    """按部门获取所有用户详情（含 department_ids、position、job_title 等）。

    每个元素包含：
    - user_id, open_id, name, employee_no, email, mobile,
    - department_ids (list[str]), job_title, positions, department_path
    """
    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

    from lark_oapi.api.contact.v3 import FindByDepartmentUserRequest

    all_users: list[dict] = []
    page_token = ""
    while True:
        req = (
            FindByDepartmentUserRequest.builder()
            .user_id_type("user_id")
            .department_id_type("open_department_id")
            .department_id(department_id)
            .page_size(100)
            .page_token(page_token)
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.contact.v3.user.afind_by_department(req)
        if not resp.success():
            logger.error(
                "Failed to find users by department %s: code=%s, msg=%s",
                department_id, resp.code, resp.msg,
            )
            break

        if resp.data and resp.data.items:
            for u in resp.data.items:
                positions: list[dict] = []
                if u.positions:
                    for p in u.positions:
                        positions.append({
                            "position_code": p.position_code,
                            "position_name": p.position_name,
                            "department_id": p.department_id,
                            "is_major": p.is_major,
                        })

                department_path: list[dict] = []
                if u.department_path:
                    for dp in u.department_path:
                        dept_name = ""
                        if dp.department_name:
                            dept_name = dp.department_name.name or ""
                        dept_id_val = (
                            str(dp.department_id)
                            if dp.department_id else ""
                        )
                        department_path.append({
                            "department_id": dept_id_val,
                            "department_name": dept_name,
                        })

                all_users.append({
                    "user_id": u.user_id or "",
                    "open_id": u.open_id or "",
                    "name": u.name or "",
                    "en_name": u.en_name or "",
                    "email": u.email or "",
                    "mobile": u.mobile or "",
                    "employee_no": u.employee_no or "",
                    "job_title": u.job_title or "",
                    "department_ids": u.department_ids or [],
                    "positions": positions,
                    "department_path": department_path,
                    "avatar_key": u.avatar_key or "",
                    "join_time": u.join_time or 0,
                    "is_frozen": u.is_frozen if u.is_frozen is not None else False,
                })

            if not resp.data.has_more:
                break
            page_token = resp.data.page_token or ""
        else:
            break

    logger.info(
        "Fetched %d users from department %s", len(all_users), department_id,
    )
    return all_users


async def get_user_detail(user_id: str, user_id_type: str = "user_id") -> dict | None:
    """获取单个用户详细信息。

    返回包含 department_ids, positions, department_path 等完整字段。
    """
    client = await _get_feishu_client()
    token = await _get_tenant_token(client)

    from lark_oapi.api.contact.v3 import GetUserRequest

    req = (
        GetUserRequest.builder()
        .user_id_type(user_id_type)
        .user_id(user_id)
        .build()
    )
    req.headers["Authorization"] = f"Bearer {token}"
    resp = await client.contact.v3.user.aget(req)
    if not resp.success():
        logger.error(
            "Failed to get user %s: code=%s, msg=%s",
            user_id, resp.code, resp.msg,
        )
        return None

    if resp.data and resp.data.user:
        u = resp.data.user
        positions: list[dict] = []
        if u.positions:
            for p in u.positions:
                positions.append({
                    "position_code": p.position_code,
                    "position_name": p.position_name,
                    "department_id": p.department_id,
                    "is_major": p.is_major,
                })

        department_path: list[dict] = []
        if u.department_path:
            for dp in u.department_path:
                dept_name = ""
                if dp.department_name:
                    dept_name = dp.department_name.name or ""
                department_path.append({
                    "department_id": str(dp.department_id) if dp.department_id else "",
                    "department_name": dept_name,
                })

        return {
            "user_id": u.user_id or "",
            "open_id": u.open_id or "",
            "name": u.name or "",
            "en_name": u.en_name or "",
            "email": u.email or "",
            "mobile": u.mobile or "",
            "employee_no": u.employee_no or "",
            "job_title": u.job_title or "",
            "department_ids": u.department_ids or [],
            "positions": positions,
            "department_path": department_path,
            "avatar_key": u.avatar_key or "",
            "join_time": u.join_time or 0,
            "is_frozen": u.is_frozen if u.is_frozen is not None else False,
        }

    return None
