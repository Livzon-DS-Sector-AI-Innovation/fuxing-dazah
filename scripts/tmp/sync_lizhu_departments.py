"""手动同步丽珠医药集团组织架构（并发 BFS + 进度条）。

用法: uv run python -X utf8 scripts/tmp/sync_lizhu_departments.py
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
from tqdm.asyncio import tqdm  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.core.database import async_session_factory  # noqa: E402
from app.platform.identity.models import Department  # noqa: E402

# 从 .env 读取同步目标（缺省福州福兴）
_DEPT_ID = os.environ.get("FEISHU_SYNC_ROOT_DEPT_ID", "od-071212463565ebca263941d217cb6e52")
CONCURRENCY = 15


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


async def _fetch_children(
    client, token: str, parent_id: str,
) -> list[dict]:
    """获取某部门所有直接子部门"""
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
        raw_data = resp.raw.content if resp.raw else None
        if not raw_data:
            break
        data = json.loads(raw_data.decode("utf-8")).get("data", {})
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


async def main():
    settings = Settings()
    if not settings.FEISHU_APP_ID:
        print("❌ 未配置 FEISHU_APP_ID")
        sys.exit(1)

    t0 = time.time()
    print("=" * 50)
    print("丽珠医药集团 — 组织架构同步")
    print("=" * 50)

    client, token = await _get_client_and_token(settings)

    # 获取丽珠自身
    from lark_oapi.api.contact.v3 import GetDepartmentRequest
    req = (
        GetDepartmentRequest.builder()
        .department_id_type("open_department_id")
        .department_id(_DEPT_ID)
        .build()
    )
    req.headers["Authorization"] = f"Bearer {token}"
    resp = await client.contact.v3.department.aget(req)
    raw = resp.raw.content.decode("utf-8")
    root_info = json.loads(raw).get("data", {}).get("department", {})
    root_name = root_info.get("name", "") or "丽珠医药集团"
    print(f"根: {root_name} ({root_info.get('member_count', 0)} 人)")

    # 并发 BFS
    sem = asyncio.Semaphore(CONCURRENCY)
    all_depts: list[dict] = [{
        "department_id": _DEPT_ID, "name": root_name,
        "parent_department_id": "",
        "leader_user_id": root_info.get("leader_user_id", "") or "",
        "member_count": root_info.get("member_count", 0) or 0,
        "status_is_deleted": False, "order": 0,
    }]
    visited: set[str] = {_DEPT_ID}
    queue: list[tuple[str, str]] = [(_DEPT_ID, root_name)]

    pbar = tqdm(desc="拉取部门", unit="dept", position=0)

    while queue:
        # 并发拉取当前层所有父部门的子部门
        async def _fetch_one(pid):
            async with sem:
                return await _fetch_children(client, token, pid)

        tasks = [_fetch_one(pid) for pid, _ in queue]
        queue = []
        results = await asyncio.gather(*tasks)

        for children in results:
            next_parents = []
            for d in children:
                oid = d["department_id"]
                if oid in visited:
                    continue
                visited.add(oid)
                all_depts.append(d)
                next_parents.append((oid, d["name"]))
            queue.extend(next_parents)
            pbar.update(len(next_parents))
        pbar.set_postfix({"累计": len(all_depts), "队列": len(queue)})

    pbar.close()
    print(f"\n拉取: {len(all_depts)} 个部门, 耗时 {time.time() - t0:.1f}s")

    # 入库
    print("写入数据库 ...")
    async with async_session_factory() as db:
        for d in tqdm(all_depts, desc="写入部门", unit="dept"):
            existing = await db.scalar(
                select(Department).where(
                    Department.feishu_department_id == d["department_id"],
                ),
            )
            if existing:
                existing.name = d["name"]
                existing.parent_feishu_department_id = d["parent_department_id"] or None
                existing.leader_user_id = d["leader_user_id"] or None
                existing.member_count = d["member_count"]
                existing.status_is_deleted = d["status_is_deleted"]
                existing.order = d["order"]
            else:
                db.add(Department(
                    feishu_department_id=d["department_id"], name=d["name"],
                    parent_feishu_department_id=d["parent_department_id"] or None,
                    leader_user_id=d["leader_user_id"] or None,
                    member_count=d["member_count"],
                    status_is_deleted=d["status_is_deleted"], order=d["order"],
                ))
        await db.commit()

    print(f"✅ 完成: {len(all_depts)} 个部门 | 总耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
