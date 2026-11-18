"""seed_daily_report.py — AI+安全日报建 4 表 + 登记连接 + 播种名单（幂等）。

前置：先用 lark-cli（bot）建 Base，拿 app_token 传入：
    lark-cli drive …（或网页手动建）→ 复制 app_token（bascn…）
用法（backend 下）：
    .venv/bin/python -m scripts.seed_daily_report --app-token <bascn…> [--dry-run]
    # 可选：--roster-open-id/--roster-name/--roster-role 重复传入可播多行名单

幂等：表按名复用；名单按 open_id 查重后追加；连接按 daily_report 域 4 kind 覆写。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402

DOMAIN = "daily_report"

# 与 service/daily_report/store.py 字段名同源（改必同步）
TABLES: dict[str, dict[str, Any]] = {
    "reports": {
        "table": {
            "name": "员工日报表",
            "default_view_name": "全部",
            "fields": [
                {"field_name": "日报日期", "type": 5},
                {"field_name": "日期键", "type": 1},
                {"field_name": "员工姓名", "type": 1},
                {"field_name": "员工OpenID", "type": 1},
                {"field_name": "今日重点工作", "type": 1},
                {"field_name": "完成情况", "type": 1},
                {"field_name": "问题与协调", "type": 1},
                {"field_name": "明日计划", "type": 1},
                {"field_name": "AI评价与建议", "type": 1},
                {"field_name": "日报状态", "type": 3, "property": {"options": [
                    {"name": "待补充"}, {"name": "已完成"}, {"name": "评价异常"},
                ]}},
                {"field_name": "首次提交时间", "type": 5},
                {"field_name": "完成提交时间", "type": 5},
            ],
        }
    },
    "summary": {
        "table": {
            "name": "部门日报汇总表",
            "default_view_name": "全部",
            "fields": [
                {"field_name": "汇总日期", "type": 5},
                {"field_name": "日期键", "type": 1},
                {"field_name": "负责人日报", "type": 1},
                {"field_name": "发布时间", "type": 5},
            ],
        }
    },
    "roster": {
        "table": {
            "name": "应提交名单表",
            "default_view_name": "全部",
            # 人员字段(11)不能做首列主索引（1254012 Unsupported field type）
            # → 单选「角色」提为首列，成员(11)随后
            "fields": [
                {"field_name": "角色", "type": 3, "property": {"options": [
                    {"name": "员工"}, {"name": "负责人"},
                ]}},
                {"field_name": "成员", "type": 11},
            ],
        }
    },
    "history": {
        "table": {
            "name": "提交历史表",
            "default_view_name": "全部",
            "fields": [
                {"field_name": "日期键", "type": 1},
                {"field_name": "员工OpenID", "type": 1},
                {"field_name": "员工姓名", "type": 1},
                {"field_name": "阶段", "type": 3, "property": {"options": [
                    {"name": "首次提交"}, {"name": "最终提交"}, {"name": "AI评价"},
                ]}},
                {"field_name": "内容", "type": 1},
            ],
        }
    },
}


async def ensure_tables(client: SafetyBitableClient, *, dry_run: bool) -> dict[str, str]:
    existing = {t.get("name"): str(t.get("table_id")) for t in await client.list_tables()}
    result: dict[str, str] = {}
    for kind, spec in TABLES.items():
        name = spec["table"]["name"]
        if name in existing:
            print(f"  [{kind}] 表已存在复用: {name} → {existing[name]}")
            result[kind] = existing[name]
            continue
        if dry_run:
            print(f"  [{kind}] dry-run：将新建 {name}（{len(spec['table']['fields'])} 列）")
            continue
        created = await client.create_table(spec)
        # create_table 解析取 data.table 包装键，单表创建接口返回平铺 table_id
        # （2026-11-18 实测：解析落空但表已建）；失败时按名回查兜底，勿误报。
        table_id = str((created or {}).get("table_id") or "")
        if not table_id:
            recheck = {t.get("name"): str(t.get("table_id")) for t in await client.list_tables()}
            table_id = recheck.get(name, "")
        if not table_id:
            raise SystemExit(f"建表失败: {kind}/{name}")
        result[kind] = table_id
        print(f"  [{kind}] 建表成功: {name} → {result[kind]}")
    return result


async def seed_roster(
    client: SafetyBitableClient, table_id: str,
    roster: list[tuple[str, str, str]], *, dry_run: bool,
) -> None:
    if not roster:
        print("  [roster] 无播种名单参数，跳过")
        return
    client.table_id = table_id
    rows = await client.list_all_records(strict=True)
    seen_ids: set[str] = set()
    for row in rows:
        member = (row.get("fields") or {}).get("成员")
        if isinstance(member, list) and member and isinstance(member[0], dict):
            seen_ids.add(str(member[0].get("id") or ""))
    for open_id, name, role in roster:
        if open_id in seen_ids:
            print(f"  [roster] 已在名单，跳过: {name}")
            continue
        if dry_run:
            print(f"  [roster] dry-run：将追加 {name}({role})")
            continue
        ok = await client.create_record(fields={
            "成员": [{"id": open_id}],
            "角色": role,
        })
        print(f"  [roster] 追加 {name}({role}): {'成功' if ok else '失败'}")


async def register_connections(app_token: str, table_ids: dict[str, str], *, dry_run: bool) -> None:
    from app.core.database import async_session_factory

    if dry_run:
        for kind, tid in table_ids.items():
            print(f"  [conn] dry-run：{DOMAIN}/{kind} → {app_token}/{tid}")
        return
    async with async_session_factory() as db:
        for kind, tid in table_ids.items():
            await store.set_connection(
                db, DOMAIN, kind,
                {"app_token": app_token, "table_id": tid, "note": "AI+安全日报（seed_daily_report 建立与登记）"},
                operator_name="seed_daily_report",
            )
        await db.commit()
    store.invalidate(DOMAIN)
    print(f"  [conn] {DOMAIN} 域 {len(table_ids)} 条连接已登记")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-token", required=True, help="目标 Base app_token（bascn…）")
    parser.add_argument("--roster-open-id", action="append", default=[], help="名单 open_id（可多次）")
    parser.add_argument("--roster-name", action="append", default=[], help="名单姓名（与 open_id 顺序对应）")
    parser.add_argument("--roster-role", action="append", default=[], help="角色：员工/负责人（缺省员工）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = SafetyBitableClient(app_token=args.app_token, table_id=None)
    print(f"[1/3] 建/复用 4 表（base={args.app_token[:12]}…）")
    table_ids = await ensure_tables(client, dry_run=args.dry_run)

    roster = []
    for i, open_id in enumerate(args.roster_open_id):
        name = args.roster_name[i] if i < len(args.roster_name) else open_id[-8:]
        role = args.roster_role[i] if i < len(args.roster_role) else "员工"
        roster.append((open_id, name, role))
    print(f"[2/3] 播种名单（{len(roster)} 人）")
    if "roster" in table_ids:
        await seed_roster(client, table_ids["roster"], roster, dry_run=args.dry_run)

    print("[3/3] 登记连接（bitable_config daily_report 域）")
    if table_ids:
        await register_connections(args.app_token, table_ids, dry_run=args.dry_run)
    print("完成 ✅")


if __name__ == "__main__":
    asyncio.run(main())
