"""Background tasks: Feishu contact sync and timeout scanning."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import async_session_factory
from app.modules.equipment.models.work_order import WorkOrder
from app.platform.integrations.feishu.contact import get_department_leader
from app.platform.integrations.feishu.message import send_timeout_notification

logger = logging.getLogger(__name__)
settings = get_settings()

stop_member_sync_flag = asyncio.Event()
stop_timeout_flag = asyncio.Event()


async def _get_feishu_client_and_token():
    """获取 lark client 和 tenant token"""
    import lark_oapi as lark

    client = (
        lark.Client.builder()
        .app_id(settings.FEISHU_APP_ID)
        .app_secret(settings.FEISHU_APP_SECRET)
        .domain(lark.FEISHU_DOMAIN)
        .app_type(lark.AppType.SELF)
        .build()
    )
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
        raise RuntimeError(f"Failed to get tenant token: code={resp.code}")
    raw = resp.raw.content.decode("utf-8") if resp.raw and resp.raw.content else ""
    token = json.loads(raw).get("tenant_access_token", "")
    return client, token


async def _bfs_departments_under(client, token: str, root_id: str) -> list[dict]:
    """BFS 并发获取指定部门下所有子部门（含自身）"""
    from lark_oapi.api.contact.v3 import GetDepartmentRequest

    # 获取根部门自身信息
    req = (
        GetDepartmentRequest.builder()
        .department_id_type("open_department_id")
        .department_id(root_id)
        .build()
    )
    req.headers["Authorization"] = f"Bearer {token}"
    resp = await client.contact.v3.department.aget(req)
    raw = resp.raw.content.decode("utf-8") if resp.raw and resp.raw.content else ""
    root_info = json.loads(raw).get("data", {}).get("department", {})
    root_name = root_info.get("name", "") or root_id

    all_depts: list[dict] = [{
        "department_id": root_id,
        "name": root_name,
        "parent_department_id": "",
        "leader_user_id": root_info.get("leader_user_id", "") or "",
        "member_count": root_info.get("member_count", 0) or 0,
        "status_is_deleted": False,
        "order": 0,
    }]
    visited: set[str] = {root_id}
    sem = asyncio.Semaphore(15)

    logger.info("BFS starting from [%s]", root_name)

    # Level 1: root's direct children
    children = await _fetch_children(client, token, root_id)
    queue: list[str] = []
    for d in children:
        if d["department_id"] not in visited:
            visited.add(d["department_id"])
            all_depts.append(d)
            queue.append(d["department_id"])

    # BFS: concurrent per level
    while queue:
        async def _fetch_one(pid):
            async with sem:
                return await _fetch_children(client, token, pid)

        tasks = [_fetch_one(pid) for pid in queue]
        queue = []
        results = await asyncio.gather(*tasks)
        for children_batch in results:
            for d in children_batch:
                if d["department_id"] not in visited:
                    visited.add(d["department_id"])
                    all_depts.append(d)
                    queue.append(d["department_id"])
        logger.info("BFS progress: %d depts (queue=%d)", len(all_depts), len(queue))

    return all_depts


async def _fetch_children(client, token: str, parent_id: str) -> list[dict]:
    """获取某部门的所有直接子部门"""
    from lark_oapi.api.contact.v3 import ListDepartmentRequest

    items: list[dict] = []
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
            if not oid:
                continue
            name = it.get("name", "") or oid
            try:
                order_val = int(it.get("order", "0") or "0")
            except (ValueError, TypeError):
                order_val = 0
            items.append({
                "department_id": oid,
                "name": name,
                "parent_department_id": parent_id,
                "leader_user_id": it.get("leader_user_id", "") or "",
                "member_count": it.get("member_count", 0) or 0,
                "status_is_deleted": False,
                "order": order_val,
            })
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return items


async def _fetch_dept_users(
    client, token: str, dept_id: str,
) -> list[dict]:
    """获取某部门的直属成员"""
    from lark_oapi.api.contact.v3 import FindByDepartmentUserRequest

    all_users: list[dict] = []
    page_token = ""
    while True:
        req = (
            FindByDepartmentUserRequest.builder()
            .department_id(dept_id)
            .department_id_type("open_department_id")
            .page_size(50)
            .page_token(page_token)
            .user_id_type("user_id")
            .build()
        )
        req.headers["Authorization"] = f"Bearer {token}"
        resp = await client.contact.v3.user.afind_by_department(req)
        raw = resp.raw.content if resp.raw else None
        if not raw:
            break
        data = json.loads(raw.decode("utf-8")).get("data", {})
        for u in data.get("items", []):
            avatar = u.get("avatar", {}) or {}
            all_users.append({
                "user_id": u.get("user_id", ""),
                "open_id": u.get("open_id", ""),
                "name": u.get("name", ""),
                "employee_no": u.get("employee_no", ""),
                "email": u.get("email", ""),
                "mobile": u.get("mobile", ""),
                "job_title": u.get("job_title", ""),
                "department_ids": u.get("department_ids", []),
                "avatar_url": (
                    avatar.get("avatar_240") or avatar.get("avatar_640")
                    or avatar.get("avatar_72") or ""
                ),
            })
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
    return all_users


# ── Public sync entry points ────────────────────────────────────────


async def sync_departments(root_dept_id: str) -> dict:
    """同步指定根部门下的全部组织架构到数据库。返回 {dept_count, elapsed}。"""
    import time as _time

    t0 = _time.time()
    logger.info("sync_departments start: root=%s", root_dept_id)

    client, token = await _get_feishu_client_and_token()
    depts = await _bfs_departments_under(client, token, root_dept_id)
    logger.info("BFS complete: %d departments", len(depts))

    async with async_session_factory() as db:
        from app.platform.identity.models import Department

        for d in depts:
            existing = await db.scalar(
                select(Department).where(
                    Department.feishu_department_id == d["department_id"],
                ),
            )
            if existing:
                existing.name = d["name"]
                existing.parent_feishu_department_id = (
                    d["parent_department_id"] or None
                )
                existing.leader_user_id = d["leader_user_id"] or None
                existing.member_count = d["member_count"]
                existing.status_is_deleted = d["status_is_deleted"]
                existing.order = d["order"]
            else:
                db.add(Department(
                    feishu_department_id=d["department_id"],
                    name=d["name"],
                    parent_feishu_department_id=(
                        d["parent_department_id"] or None
                    ),
                    leader_user_id=d["leader_user_id"] or None,
                    member_count=d["member_count"],
                    status_is_deleted=d["status_is_deleted"],
                    order=d["order"],
                ))
        await db.commit()

    elapsed = _time.time() - t0
    logger.info(
        "sync_departments done: %d depts in %.1fs",
        len(depts), elapsed,
    )
    return {"dept_count": len(depts), "elapsed": round(elapsed, 1)}


async def sync_members(target_dept_id: str) -> dict:
    """同步指定部门及其子部门的全部成员到数据库（并发）。"""
    import time as _time

    t0 = _time.time()
    logger.info("sync_members start: target=%s", target_dept_id)

    client, token = await _get_feishu_client_and_token()

    # 获取目标部门及其子部门
    depts = await _bfs_departments_under(client, token, target_dept_id)
    dept_map = {d["department_id"]: d["name"] for d in depts}
    logger.info("Found %d departments for member sync", len(depts))

    # 并发拉取每个部门的成员
    sem = asyncio.Semaphore(10)

    async def _fetch_one(dept):
        async with sem:
            return await _fetch_dept_users(client, token, dept["department_id"]), dept

    tasks = [_fetch_one(d) for d in depts]
    results = await asyncio.gather(*tasks)

    # 去重
    seen_uids: set[str] = set()
    all_users: list[dict] = []
    for users, dept in results:
        for u in users:
            uid = u["user_id"]
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)
            dids = u.get("department_ids", [])
            primary_dept = dept_map.get(dids[0], "") if dids else dept["name"]
            all_users.append({**u, "dept_name": primary_dept})

    logger.info("Fetched %d unique users from %d depts", len(all_users), len(depts))

    # 入库
    async with async_session_factory() as db:
        from app.platform.identity.models import User

        for u in all_users:
            existing = await db.scalar(
                select(User).where(User.feishu_user_id == u["user_id"]),
            )
            oid = u.get("open_id", "")
            if not existing and oid:
                existing = await db.scalar(
                    select(User).where(User.feishu_open_id == oid),
                )
            dept_ids_json = json.dumps(
                u.get("department_ids", []), ensure_ascii=False,
            )
            if existing:
                existing.name = u["name"] or existing.name
                existing.employee_no = (
                    u.get("employee_no") or None or existing.employee_no
                )
                existing.email = u.get("email") or existing.email
                existing.mobile = u.get("mobile") or existing.mobile
                existing.position = u.get("job_title") or existing.position
                existing.avatar_url = u.get("avatar_url") or existing.avatar_url
                if not existing.department:
                    existing.department = u["dept_name"]
                existing.feishu_department_ids = dept_ids_json
                if not existing.feishu_open_id:
                    existing.feishu_open_id = oid
                if not existing.feishu_user_id:
                    existing.feishu_user_id = u["user_id"]
            else:
                db.add(User(
                    name=u["name"],
                    feishu_user_id=u["user_id"],
                    feishu_open_id=oid,
                    employee_no=u.get("employee_no") or None,
                    email=u.get("email") or None,
                    mobile=u.get("mobile") or None,
                    department=u["dept_name"],
                    position=u.get("job_title"),
                    avatar_url=u.get("avatar_url") or None,
                    feishu_department_ids=dept_ids_json,
                ))
        await db.commit()

    elapsed = _time.time() - t0
    logger.info("sync_members done: %d users in %.1fs", len(all_users), elapsed)
    return {
        "user_count": len(all_users), "dept_count": len(depts),
        "elapsed": round(elapsed, 1),
    }


# ── Scheduled loops ─────────────────────────────────────────────────


async def member_sync_loop() -> None:
    """每天 00:00 同步 FEISHU_SYNC_MEMBER_DEPT_ID 下的成员"""
    while not stop_member_sync_flag.is_set():
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        wait_seconds = (next_midnight - now).total_seconds()
        target = settings.FEISHU_SYNC_MEMBER_DEPT_ID
        logger.info(
            "Next member sync in %.0f min (target=%s)",
            wait_seconds / 60, target,
        )
        try:
            await asyncio.wait_for(
                stop_member_sync_flag.wait(), timeout=wait_seconds,
            )
            break
        except TimeoutError:
            pass

        if not stop_member_sync_flag.is_set() and target:
            try:
                await sync_members(target)
            except Exception:
                logger.exception("Member sync failed")


async def scan_timeout_work_orders() -> None:
    """扫描超时未接单的工单"""
    dept_id = settings.FEISHU_EQUIPMENT_DEPT_ID
    if not dept_id:
        return

    async with async_session_factory() as db:
        try:
            from app.modules.equipment.service.maintenance_config import (
                get_claim_timeout_config,
            )

            config = await get_claim_timeout_config(db)
            result = await db.execute(
                select(WorkOrder).where(
                    WorkOrder.status == "待处理",
                    WorkOrder.is_deleted == False,  # noqa: E712
                )
            )
            pending_orders = result.scalars().all()

            now = datetime.now(UTC)
            priority_map = {
                "紧急": "emergency", "高": "high",
                "中": "medium", "低": "low",
            }
            for order in pending_orders:
                attr = priority_map.get(order.priority, "medium")
                timeout_minutes = getattr(config, attr, 60)
                elapsed = (now - order.reported_at).total_seconds() / 60
                if elapsed > timeout_minutes:
                    leader = await get_department_leader(dept_id)
                    leader_name = (
                        leader.get("name", "主管") if leader else "主管"
                    )
                    await send_timeout_notification(
                        order.work_order_no, "设备", leader_name,
                    )
                    logger.info(
                        "Timeout WO %s (%.0f min > %d min)",
                        order.work_order_no, elapsed, timeout_minutes,
                    )
        except Exception:
            logger.exception("Timeout scan error")
        finally:
            await db.rollback()


async def timeout_scan_loop() -> None:
    """每60秒扫描超时工单"""
    while not stop_timeout_flag.is_set():
        try:
            await scan_timeout_work_orders()
        except Exception:
            logger.exception("Timeout scan error")
        try:
            await asyncio.wait_for(
                stop_timeout_flag.wait(), timeout=60,
            )
        except TimeoutError:
            pass
