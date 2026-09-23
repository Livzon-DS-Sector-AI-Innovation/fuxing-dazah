"""oh 本地镜像回填（dev 工具，oh-direct Ticket 04 双路径比对前置）。

oh 岗位/危害因素两表事件镜像在 dev 库严重分歧（oh_positions 非删除 910 行 vs
Bitable 440 行，survey_oh 探针 2026-09-23；幽灵行+NULL 键行堆积，cert/msds
「本地比对前须回填镜像」第三例）。本脚本把 Bitable 两表全量按「search 形态
归一 → handler 既有映射纯函数」UPSERT 写入**本地 dev 库** oh_positions /
oh_hazard_factors，并把 Bitable 已不存在的记录软删对齐（与事件镜像最终状态
一致）；(department,position) / factor_name 部分唯一索引冲突按 handler
`_create_guarded` 语义跳过（保留先建行）。只读 Bitable、只写本地库；
生产环境严禁执行。

用法（backend 目录下）：.venv/Scripts/python.exe scripts/tmp/backfill_oh_mirror.py
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

sys.path.insert(0, ".")

# 文本列（search 富文本段形态归一为 handler 预期纯字符串）；危害因素多选
# 保持原样（handler _clean_hazard_factors 原生兼容 list<str>/list<dict>）
_TEXT_COLUMNS = {
    "position": ("部门", "岗位", "职务"),
    "hazard_factor": ("危害因素名称", "呼吸防护用品"),
}


async def _backfill_kind(kind: str, model: Any, map_fn: Any) -> None:
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.core.database import async_session_factory
    from app.modules.safety.bitable_config.store import store
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.bitable_direct import fields as bd_fields

    conn = store.get_connection("oh", kind)
    if conn is None or conn.status == "disabled":
        print(f"[x] oh/{kind} 连接未配置或已停用")
        raise SystemExit(2)

    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
    records = await client.list_all_records(
        table_id=conn.table_id, page_size=500, strict=True,
    )
    collected: dict[str, dict[str, Any]] = {}
    for r in records:
        rid = str(r.get("record_id") or "")
        if not rid:
            continue
        fields = dict(r.get("fields") or {})
        for column in _TEXT_COLUMNS[kind]:
            if column in fields:
                fields[column] = bd_fields.rich_text(fields.get(column)) or None
        mapped = map_fn(fields)
        if mapped is None:
            continue  # 跳行规则（部门岗位均空 / 名称空），与镜像种群口径一致
        mapped["feishu_record_id"] = rid
        mapped["source"] = "bitable"
        collected[rid] = mapped

    updated = created = skipped = 0
    async with async_session_factory() as session:
        for rid, mapped in collected.items():
            existing = await session.scalar(
                select(model).where(
                    model.feishu_record_id == rid,
                    model.is_deleted == False,  # noqa: E712
                )
            )
            if existing is not None:
                for col, val in mapped.items():
                    setattr(existing, col, val)
                try:
                    await session.commit()
                    updated += 1
                except IntegrityError:
                    # UPDATE 撞 (dept,pos) 部分唯一索引：重复组的第二行在镜像
                    # 中本就更新不了（生产 handler 同样失败仅留日志），按同
                    # 语义跳过保留旧值
                    await session.rollback()
                    skipped += 1
                continue
            obj = model(**mapped)
            session.add(obj)
            try:
                await session.commit()
                created += 1
            except IntegrityError:
                # 部分唯一索引冲突（(dept,pos) / factor_name 重复行）：
                # 按 handler _create_guarded 语义跳过（保留先建行）
                await session.rollback()
                skipped += 1

        result = await session.execute(
            select(model.feishu_record_id).where(
                model.is_deleted == False,  # noqa: E712
            )
        )
        existing_ids = {rid for (rid,) in result.all() if rid}
        stale = sorted(existing_ids - set(collected))
        soft_deleted = 0
        for rid in stale:
            row = await session.scalar(
                select(model).where(
                    model.feishu_record_id == rid,
                    model.is_deleted == False,  # noqa: E712
                )
            )
            if row is not None:
                row.is_deleted = True
                await session.commit()
                soft_deleted += 1

    print(f"[{kind}] bitable_total={len(records)} collected={len(collected)}"
          f" updated={updated} created={created} unique_skipped={skipped}"
          f" soft_deleted_stale={soft_deleted}")


async def main() -> int:
    from app.modules.safety.feishu.oh_bitable_handler import (
        map_hazard_factor_fields,
        map_position_fields,
    )
    from app.modules.safety.models import OhHazardFactor, OhPosition

    await _backfill_kind("position", OhPosition, map_position_fields)
    await _backfill_kind("hazard_factor", OhHazardFactor, map_hazard_factor_fields)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
