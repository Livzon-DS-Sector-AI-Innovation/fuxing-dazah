"""seed_training_behavior.py — 主安全库建 S6 两表 + 登记连接 + 可选三违回填。

用法（backend 下）：
    .venv/bin/python -m scripts.seed_training_behavior                     # 建表+登记连接
    .venv/bin/python -m scripts.seed_training_behavior --backfill-violations  # 建表+登记+历史三违回填
    .venv/bin/python -m scripts.seed_training_behavior --dry-run           # 只打印计划不动飞书/DB

幂等：
- 表按名查找，已存在复用（不重复建）；
- 连接按 training_behavior/{training,violation} 覆写（app_token=主安全库）；
- 回填按「关联隐患编号」去重（存量+批内），重跑不重复建行。

结构事实源：app/modules/safety/service/training_behavior/seed_data.py（四期蓝本+微增列）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.service.bitable_direct import fields as bd_fields  # noqa: E402
from app.modules.safety.service.bitable_direct import reader as bd_reader  # noqa: E402
from app.modules.safety.service.training_behavior import seed_data  # noqa: E402

# 主安全库（OH 6 表/体系标准核查表所在 base；goals 接入同一先例口径）
MAIN_APP_TOKEN = "Ea0abVsMzacU5VsF4K5cBH0kngb"

_HAZARD_READ_FIELDS = (
    seed_data.HAZARD_NO, seed_data.HAZARD_CATEGORY_AI,
    seed_data.HAZARD_DESC_AI, seed_data.HAZARD_DESC, seed_data.HAZARD_DATE,
)


async def ensure_table(
    client: SafetyBitableClient, schema: dict, *, dry_run: bool
) -> str | None:
    tables = await client.list_tables()
    existing = next(
        (t for t in tables if t.get("name") == schema["table"]["name"]), None
    )
    if existing:
        print(f"  表已存在，复用: {existing['table_id']}")
        return str(existing["table_id"])
    if dry_run:
        print(f"  dry-run：将新建表「{schema['table']['name']}」"
              f"（{len(schema['table']['fields'])} 列）")
        return None
    created = await client.create_table(schema)
    if not created or not created.get("table_id"):
        raise SystemExit(f"建表失败: {schema['table']['name']}（见上方日志）")
    print(f"  建表成功: {created['table_id']}")
    return str(created["table_id"])


async def fetch_hazard_records() -> list[dict]:
    client = bd_reader.resolve_client("hazard", "hazard")
    return await client.list_all_records(
        field_names=list(_HAZARD_READ_FIELDS), page_size=500, strict=True
    )


async def backfill_violations(violation_table_id: str, *, dry_run: bool) -> None:
    """历史三违回填：dry-run 只读计数；真跑复用 backflow.run_backflow_round
    （同一套幂等口径，避免脚本与服务两份逻辑漂移）。"""
    try:
        hazard_records = await fetch_hazard_records()
    except Exception as exc:  # noqa: BLE001 —— 回填是可选步，读不到隐患即跳过
        print(f"  [回填跳过] hazard 域读取失败: {exc}")
        return
    client = SafetyBitableClient(
        app_token=MAIN_APP_TOKEN, table_id=violation_table_id
    )
    existing = await client.list_all_records(
        field_names=["关联隐患编号"], strict=True
    )
    existing_nos = {
        no
        for r in existing
        if (no := bd_fields.text(r.get("fields") or {}, "关联隐患编号"))
    }
    plan = seed_data.plan_backfill(hazard_records, existing_nos)
    print(f"  隐患表三违作业行命中回填计划: {len(plan)} 条"
          f"（违章表存量 {len(existing_nos)} 条编号去重后）")
    if dry_run:
        return
    from app.modules.safety.service.training_behavior import backflow

    outcome = await backflow.run_backflow_round()
    print(f"  回填执行完成: {outcome}")


async def register_connection(
    kind: str, table_id: str, *, dry_run: bool
) -> None:
    if dry_run:
        print(f"  dry-run：将登记连接 training_behavior/{kind} → {MAIN_APP_TOKEN}/{table_id}")
        return
    from app.core.database import async_session_factory

    async with async_session_factory() as db:
        await store.set_connection(
            db,
            seed_data.DOMAIN,
            kind,
            {
                "app_token": MAIN_APP_TOKEN,
                "table_id": table_id,
                "note": f"S6 教育培训与行为管控（播种脚本 {datetime.now(UTC).date()} 建立与登记）",
            },
            operator_name="seed_training_behavior",
        )
        await db.commit()
    store.invalidate(seed_data.DOMAIN)
    print(f"  连接已登记: training_behavior/{kind} → {MAIN_APP_TOKEN}/{table_id}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backfill-violations", action="store_true",
        help="建表登记后，把隐患表历史三违作业行回填进违章档案（幂等）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不动飞书/DB")
    args = parser.parse_args()

    main_client = SafetyBitableClient(app_token=MAIN_APP_TOKEN, table_id=None)
    print("[1/3] 培训计划与实施表")
    training_id = await ensure_table(main_client, seed_data.table_schema_training(), dry_run=args.dry_run)
    print("[2/3] 违章行为档案表")
    violation_id = await ensure_table(main_client, seed_data.table_schema_violation(), dry_run=args.dry_run)

    if args.dry_run:
        if args.backfill_violations and violation_id:
            print("[3/3] 三违回填（dry-run 读真源计数）")
            await backfill_violations(violation_id, dry_run=True)
        else:
            print("[3/3] dry-run：跳过连接登记与回填")
        print("完成：dry-run 结束（未做任何变更）")
        return

    if training_id:
        await register_connection(seed_data.KIND_TRAINING, training_id, dry_run=False)
    if violation_id:
        await register_connection(seed_data.KIND_VIOLATION, violation_id, dry_run=False)
    if args.backfill_violations and violation_id:
        print("[回填] 历史三违作业行")
        await backfill_violations(violation_id, dry_run=False)
    print("完成：training-behavior 页将自动转 live（刷新即出数）")


if __name__ == "__main__":
    asyncio.run(main())
