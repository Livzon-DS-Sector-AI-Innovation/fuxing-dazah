"""通讯录同步：按指定根部门同步部门+成员到 identity 库（默认福兴口径）。

用法（backend 下）：
    .venv/bin/python -m scripts.sync_feishu_directory [open_department_id]

建议间隔重跑（部门/入离职变化）；每日 00:00 的 member_sync_loop 也走
FEISHU_SYNC_MEMBER_DEPT_ID（.env 已配同一部门）。
"""

import asyncio
import json
import sys

from sqlalchemy import text

# 默认同步「丽珠集团福州福兴医药有限公司」（福兴口径，与五金库同组织）
DEFAULT_DEPT_ID = "od-071212463565ebca263941d217cb6e52"
CHECK_NAMES = ["林建水", "林礼枫", "杨剑"]


async def main() -> None:
    from app.platform.integrations.feishu.sync import (
        sync_departments,
        sync_members,
    )

    root_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DEPT_ID
    print("using root:", root_id)

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
