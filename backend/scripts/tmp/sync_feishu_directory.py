"""一次性通讯录同步：发现租户根部门 → 同步部门+成员到 identity 库。"""

import asyncio
import json

from sqlalchemy import text

CHECK_NAMES = ["林建水", "林礼枫", "杨剑"]


async def main() -> None:
    from app.platform.integrations.feishu.sync import (
        _fetch_children,
        _get_feishu_client_and_token,
        sync_departments,
        sync_members,
    )

    client, token = await _get_feishu_client_and_token()
    children = await _fetch_children(client, token, "0")
    print("root candidates:", json.dumps(
        [{"id": c["department_id"], "name": c["name"],
          "members": c["member_count"]} for c in children],
        ensure_ascii=False,
    ))
    if not children:
        print("!! 根部门发现失败（检查平台应用通讯录权限）")
        return
    root_id = children[0]["department_id"]
    print("using root:", root_id, children[0]["name"])

    dept_stats = await sync_departments(root_id)
    print("sync_departments:", json.dumps(dept_stats, ensure_ascii=False))
    member_stats = await sync_members(root_id)
    print("sync_members:", json.dumps(member_stats, ensure_ascii=False))

    from app.core.database import async_session_factory

    async with async_session_factory() as s:
        rows = await s.execute(
            text("SELECT name, email, department FROM identity.users "
                 "WHERE name = ANY(:names) AND is_deleted = false"),
            {"names": CHECK_NAMES},
        )
        found = rows.fetchall()
    print("check:", json.dumps(
        [list(r) for r in found], ensure_ascii=False))
    missing = set(CHECK_NAMES) - {r[0] for r in found}
    if missing:
        print("!! 仍未找到:", missing)


asyncio.run(main())
