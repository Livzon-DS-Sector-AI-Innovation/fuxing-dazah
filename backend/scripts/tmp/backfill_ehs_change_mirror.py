"""ehs_change 本地镜像回填（verify 前置，cert/msds/oh/hazard_id 四域先例：
本地比对前须回填镜像）。

全量拉 Bitable 审批/验收两表 → handler `_upsert` 同语义 UPSERT：
mapper（map_approval_fields / map_acceptance_fields，search 形态直接
兼容——本域无公式列）→ EhsChangeService.upsert_from_bitable（含
ai_review_result 合并 regulations 语义）→ 按 feishu_record_id 匹配活行
或 INSERT。

跳行规则与 handler 一致：mapper 返 None（申请状态「已删除」）跳过。
「已删除」态的既有 PG 活行（Bitable 已无对应态值）不动——verify 归因。

**写库语义（与 hazard_id 先例不同）**：EhsChangeService.upsert_from_bitable
内部逐行 commit——本脚本**恒写库**（幂等 UPSERT，重复执行结果不变；
--apply 参数保留仅为调用习惯兼容，无 dry-run 模式）。2026-09-24 首跑
实测 insert=10 update=482，回填后 PG 活行 492=Bitable 全量。

用法（backend 目录下，本地 dev）：

    .venv/Scripts/python.exe scripts/tmp/backfill_ehs_change_mirror.py

退出码：0 成功；2 连接未配置；3 拉取失败。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

sys.path.insert(0, ".")

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.ehs_change_bitable import get_mapper  # noqa: E402
from app.modules.safety.service.bitable_direct.reader import (  # noqa: E402
    fetch_all_records,
    resolve_client,
)

_TABLE_NOTE = "registry ehs_change/approval+acceptance"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply", action="store_true",
        help="兼容保留（脚本恒写库，见模块 docstring）",
    )
    parser.parse_args()

    conns = {v.kind: v for v in store.get_connections("ehs_change")}
    if not conns:
        print(f"[x] 连接未配置（{_TABLE_NOTE}）")
        return 2

    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import EhsChange
    from app.modules.safety.service.ehs_change import EhsChangeService

    n_insert = n_update = n_skip_deleted = n_skip_dup = 0
    samples: list[str] = []
    async with async_session_factory() as session:
        # 预载活行按 fid 分组（找重复组；本域探针 0 重复，防御保留）
        rows = list((await session.scalars(
            select(EhsChange).where(
                EhsChange.is_deleted == False,  # noqa: E712
                EhsChange.feishu_record_id.isnot(None),
            )
        )).all())
        by_fid: dict[str, list[Any]] = {}
        for r in rows:
            by_fid.setdefault(r.feishu_record_id or "", []).append(r)

        service = EhsChangeService(session)
        for kind in ("approval", "acceptance"):
            conn = conns.get(kind)
            if conn is None or not conn.table_id:
                print(f"[x] {kind} 未配置 table_id")
                return 2
            client = resolve_client("ehs_change", kind)
            records = await fetch_all_records(
                client, page_size=500, automatic_fields=True,
            )
            mapper = get_mapper(kind)
            print(f"[{kind}] Bitable 全量 {len(records)} 行")

            for rec in records:
                rid = str(rec.get("record_id") or "")
                if not rid:
                    continue
                mapped = mapper(rec.get("fields") or {})
                if mapped is None:
                    n_skip_deleted += 1
                    continue
                existing = by_fid.get(rid) or []
                if len(existing) > 1:
                    n_skip_dup += 1
                    if len(samples) < 3:
                        samples.append(f"跳过重复组 {rid} x{len(existing)}")
                    continue
                if existing:
                    # upsert_from_bitable 的更新分支（None 不覆盖 + regulations
                    # 合并）依赖既有行对象——直接走 service 保持语义一致
                    await service.upsert_from_bitable(mapped, rid, kind)
                    n_update += 1
                else:
                    await service.upsert_from_bitable(mapped, rid, kind)
                    n_insert += 1

        print(f"[APPLIED] "
              f"insert={n_insert} update={n_update} "
              f"skip_deleted={n_skip_deleted} skip_dup={n_skip_dup}")
        for s in samples:
            print(f"  {s}")
        # upsert_from_bitable 已逐行 commit（恒写库，幂等；见模块 docstring）
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
