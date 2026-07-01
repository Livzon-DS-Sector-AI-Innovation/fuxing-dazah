"""手动同步丽珠医药集团成员到数据库（并发 + 进度）。

用法: uv run python -X utf8 scripts/tmp/sync_lizhu_members.py
"""

import asyncio
import json
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
os.environ["SECRET_KEY"] = "scripts-manual-run"

import lark_oapi as lark  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.database import async_session_factory  # noqa: E402
from app.platform.identity.models import Department, User  # noqa: E402

# 从 .env 读取同步目标（缺省福州福兴）
_TARGET_ID = os.environ.get("FEISHU_SYNC_MEMBER_DEPT_ID", "od-071212463565ebca263941d217cb6e52")
CONCURRENCY = 10


async def _get_client_and_token(settings: Settings):
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
        raise RuntimeError(f"获取 tenant token 失败: code={resp.code}")
    token = json.loads(resp.raw.content.decode("utf-8")).get("tenant_access_token", "")
    return client, token


async def _fetch_dept_users(
    client, token: str, dept_id: str, dept_name: str,
) -> tuple[list[dict], str, int]:
    """获取某部门直属成员，返回 (用户列表, 部门名, 用户数)"""
    from lark_oapi.api.contact.v3 import FindByDepartmentUserRequest

    users: list[dict] = []
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
        raw_data = resp.raw.content if resp.raw else None
        if not raw_data:
            break
        data = json.loads(raw_data.decode("utf-8")).get("data", {})
        for u in data.get("items", []):
            avatar = u.get("avatar", {}) or {}
            users.append({
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
    return users, dept_name, len(users)


async def main():
    settings = Settings()
    if not settings.FEISHU_APP_ID:
        print("❌ 未配置 FEISHU_APP_ID", file=sys.stderr)
        sys.exit(1)

    print("=" * 50)
    print("丽珠医药集团 — 成员同步（并发）")
    print("=" * 50)

    # 1. 读取部门，筛选目标部门及其子部门
    async with async_session_factory() as db:
        all_db_depts = list(await db.scalars(
            select(Department)
            .where(
                Department.is_deleted == False,  # noqa: E712
                Department.status_is_deleted == False,  # noqa: E712
            )
            .order_by(Department.order, Department.name),
        ))
    if not all_db_depts:
        print("❌ 无部门数据，请先运行 sync_lizhu_departments.py", file=sys.stderr)
        sys.exit(1)

    # 构建 parent 索引
    id_to_dept = {d.feishu_department_id: d for d in all_db_depts}
    children_of: dict[str, list] = {}
    for d in all_db_depts:
        pid = d.parent_feishu_department_id or ""
        children_of.setdefault(pid, []).append(d)

    # 定位目标部门
    target = id_to_dept.get(_TARGET_ID)
    if not target:
        print(f"❌ 未找到目标部门: id={_TARGET_ID}", file=sys.stderr)
        sys.exit(1)
    print(f"目标: {target.name} ({target.member_count} 人)")

    # BFS 收集目标部门及其全部子部门
    depts: list = [target]
    queue = [target.feishu_department_id]
    while queue:
        pid = queue.pop(0)
        for child in children_of.get(pid, []):
            depts.append(child)
            queue.append(child.feishu_department_id)

    dept_map = {d.feishu_department_id: d.name for d in depts}
    print(f"含子部门: {len(depts)} 个")

    # 2. 连接飞书
    client, token = await _get_client_and_token(settings)

    # 3. 并发拉取（带进度）
    print(f"并发拉取中（{CONCURRENCY} 路）...")
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    total = len(depts)
    start = time.time()
    lock = asyncio.Lock()

    async def _fetch_one(dept):
        nonlocal done
        async with sem:
            result = await _fetch_dept_users(
                client, token, dept.feishu_department_id, dept.name,
            )
        async with lock:
            nonlocal done
            done += 1
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            pct = done * 100 // total
            bar = "█" * (pct // 2) + "░" * (50 - pct // 2)
            print(
                f"\r  [{bar}] {done}/{total} ({pct}%) "
                f"| {rate:.1f} dept/s | {result[2]} 人 [{result[1]}]"
                f"\033[K",
                end="", flush=True,
            )
        return result

    tasks = [_fetch_one(d) for d in depts]
    results = await asyncio.gather(*tasks)
    print()  # 换行

    # 4. 去重
    seen_uids: set[str] = set()
    all_users: list[dict] = []
    fetch_total = 0
    for users, dept_name, count in results:
        fetch_total += count
        for u in users:
            uid = u["user_id"]
            if not uid or uid in seen_uids:
                continue
            seen_uids.add(uid)
            dids = u.get("department_ids", [])
            primary_dept = dept_map.get(dids[0], "") if dids else dept_name
            all_users.append({**u, "dept_name": primary_dept})

    print(f"拉取: {fetch_total} 人次 → 去重后 {len(all_users)} 个唯一用户")

    # 5. 入库（带进度）
    print("正在写入数据库 ...")
    async with async_session_factory() as db:
        for i, u in enumerate(all_users):
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
            if (i + 1) % 50 == 0:
                print(f"  写入 {i + 1}/{len(all_users)} ...")
        await db.commit()

    elapsed = time.time() - start
    print(f"✅ 完成: {len(all_users)} 个用户 | 耗时 {elapsed:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
