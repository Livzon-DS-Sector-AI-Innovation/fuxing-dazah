"""hazard_id 本地镜像回填（verify 前置，cert/msds/oh 三域先例：本地比对前须回填镜像）。

全量拉 Bitable 危险源辨识表 → handler `_upsert_mirror` 同语义 UPSERT：
search 形态归一化 → map_bitable_to_model → identity 派生部门 +
hazard_id_no 派生 → 按 feishu_record_id 匹配活行（全字段含 None 覆写，
feishu_record_id/hazard_id_no 除外）或 INSERT。

与 handler 的唯一差异：撞幽灵行重复组（同 fid 多活行，探针 recvrX7gkf2SS1）
时 handler 的 scalar_one_or_none 会抛 MultipleResultsFound（生产病灶），本
脚本按「跳过并告警」处理（oh backfill 先例：重复组生产同样更新不了，跳过）。

用法（backend 目录下，本地 dev）：

    .venv/Scripts/python.exe scripts/tmp/backfill_hazard_id_mirror.py [--apply]

默认 dry-run 打印将插入/更新/跳过的计数与样本；--apply 才写库。
退出码：0 成功；2 连接未配置；3 拉取失败。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

sys.path.insert(0, ".")

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.service.bitable_direct.reader import (  # noqa: E402
    fetch_all_records,
    resolve_client,
)
from app.modules.safety.service.hazard_id_direct.views import (  # noqa: E402
    search_to_handler_form,
)
from app.modules.safety.service.hazard_identification_bitable import (  # noqa: E402
    map_bitable_to_model,
)

_TABLE_ID_NOTE = "registry hazard_id/identification"


async def _resolve_departments(session: Any, names: set[str]) -> dict[str, str | None]:
    if not names:
        return {}
    from sqlalchemy import select

    from app.platform.identity.models import User as IdentityUser

    stmt = select(IdentityUser.name, IdentityUser.department).where(
        IdentityUser.name.in_(sorted(names)),
        IdentityUser.is_deleted == False,  # noqa: E712
    )
    rows = (await session.execute(stmt)).all()
    out: dict[str, str | None] = {}
    for name, dept in rows:
        out.setdefault(name, dept)
    return out


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    args = parser.parse_args()

    conn = store.get_connection("hazard_id", "identification")
    if conn is None or not conn.enabled:
        print(f"[x] 连接未配置或停用（{_TABLE_ID_NOTE}）")
        return 2

    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardIdentification
    from app.modules.safety.service.hazard_identification_bitable import _person_name

    client = resolve_client("hazard_id", "identification")
    records = await fetch_all_records(client, page_size=500, automatic_fields=True)
    print(f"Bitable 全量 {len(records)} 行")

    n_insert = n_update = n_skip_dup = 0
    samples: list[str] = []
    async with async_session_factory() as session:
        # 预载活行按 fid 分组（找重复组）
        rows = list((await session.scalars(
            select(HazardIdentification).where(
                HazardIdentification.is_deleted == False,  # noqa: E712
                HazardIdentification.feishu_record_id.isnot(None),
            )
        )).all())
        by_fid: dict[str, list[Any]] = {}
        for r in rows:
            by_fid.setdefault(r.feishu_record_id or "", []).append(r)

        # 提交人姓名集合 → 部门批量派生（handler 同语义）
        submitter_names: set[str] = set()
        for rec in records:
            fields = rec.get("fields") or {}
            nm = _person_name(search_to_handler_form(fields).get("提交人员（人工）"))
            if nm:
                submitter_names.add(nm)
        dept_map = await _resolve_departments(session, submitter_names)

        for rec in records:
            rid = str(rec.get("record_id") or "")
            if not rid:
                continue
            fields = rec.get("fields") or {}
            mapped = map_bitable_to_model(
                search_to_handler_form(fields),
                feishu_record_id=rid,
                feishu_table_id=conn.table_id,
                department=dept_map.get(_person_name(fields.get("提交人员（人工）"))),
            )
            mapped["hazard_id_no"] = f"HI-{rid[-12:]}"
            existing = by_fid.get(rid) or []
            if len(existing) > 1:
                n_skip_dup += 1
                if len(samples) < 3:
                    samples.append(f"跳过重复组 {rid} x{len(existing)}")
                continue
            if existing:
                obj = existing[0]
                for k, v in mapped.items():
                    if k not in ("feishu_record_id", "hazard_id_no"):
                        setattr(obj, k, v)
                n_update += 1
            else:
                session.add(HazardIdentification(**mapped))
                n_insert += 1

        print(f"{'[APPLY]' if args.apply else '[DRY-RUN]'} "
              f"insert={n_insert} update={n_update} skip_dup={n_skip_dup}")
        for s in samples:
            print(f"  {s}")
        if args.apply:
            await session.commit()
            print("已提交")
        else:
            print("dry-run 未写库；加 --apply 执行")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
