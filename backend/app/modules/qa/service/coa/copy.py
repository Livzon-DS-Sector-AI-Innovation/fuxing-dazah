"""COA 复制到其它模板：把一条出具记录的若干格登记到同产品另一模板的同批号记录。

口径：
- 目标模板下没有这个批号 → 新建：流水号选填；没被复制覆盖、配了默认值的检测
  项目自动填默认值（与手工登记同口径）。
- 已有 → 只覆盖载荷里的格，其余结果（含备注）、批次字段、流水号原样保留。
- 写入的值由调用方给（原样复制的，或就地改过的），这里只认格的归属；每格的
  来源记进 coa_copy_links（同一目标格只留最新一条）。
- 操作日志就是普通的新建 / 编辑记录，没有专门的复制动作。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import CoaCopyKind
from app.modules.qa.repository import coa as repo
from app.modules.qa.schemas.coa import (
    CoaCopyReportIn,
    CoaReportCreate,
    CoaReportUpdate,
    CoaValueIn,
)
from app.modules.qa.service.coa.common import (
    _actor_id,
    compose_batch_info,
    get_report_or_404,
    get_standard_or_404,
    resolve_standard_fields,
)
from app.modules.qa.service.coa.issuance import create_report, update_report
from app.platform.identity.models import User


def _cell_uuid(raw: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise AppException(
            status_code=400, message=f"{label} {raw} 不是有效的项目"
        ) from exc


async def copy_report(
    db: AsyncSession,
    source_report_id: uuid.UUID,
    payload: CoaCopyReportIn,
    user: User | None,
) -> dict[str, Any]:
    source = await get_report_or_404(db, source_report_id)
    target_standard = await get_standard_or_404(db, uuid.UUID(payload.standard_id))
    if target_standard.product_id != source.product_id:
        raise AppException(status_code=400, message="只能复制到同一产品下的其它模板")
    if target_standard.id == source.standard_id:
        raise AppException(status_code=400, message="来源和目标是同一个模板")

    source_fields, _ = await resolve_standard_fields(db, source.standard_id)
    target_fields, _ = await resolve_standard_fields(db, target_standard.id)
    # 品名/批号/流水号是内置字段，不能当格复制（批号沿用来源、流水号各记各的）
    builtin_keys = {f["key"] for f in source_fields if f.get("builtin")}
    source_keys = {f["key"] for f in source_fields if not f.get("builtin")}
    target_keys = {f["key"] for f in target_fields if not f.get("builtin")}
    source_item_ids = {i.id for i in await repo.list_items(db, source.standard_id)}
    target_items = await repo.list_items(db, target_standard.id)
    target_item_ids = {i.id for i in target_items}

    values: dict[uuid.UUID, CoaValueIn] = {}
    batch_data: dict[str, str] = {}
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for cell in payload.cells:
        slot = (cell.kind, cell.target)
        if slot in seen:
            raise AppException(status_code=400, message="复制的内容里目标格重复")
        seen.add(slot)
        if cell.kind == CoaCopyKind.ITEM:
            source_id = _cell_uuid(cell.source, "来源项目")
            target_id = _cell_uuid(cell.target, "目标项目")
            if source_id not in source_item_ids:
                raise AppException(status_code=400, message="来源项目不在来源模板中")
            if target_id not in target_item_ids:
                raise AppException(status_code=400, message="目标项目不在目标模板中")
            if cell.value_num is None and not (cell.value_text or "").strip():
                raise AppException(status_code=400, message="结果值不能为空（数值或文字）")
            values[target_id] = CoaValueIn(
                item_id=str(target_id),
                value_num=cell.value_num,
                value_text=cell.value_text,
                remark=cell.remark,
            )
            links.append(
                {"kind": cell.kind, "source_key": str(source_id), "target_key": str(target_id)}
            )
        else:
            for role, key, keys in (
                ("来源", cell.source, source_keys),
                ("目标", cell.target, target_keys),
            ):
                if key in builtin_keys:
                    raise AppException(
                        status_code=400,
                        message=f"{role}批次字段 {key} 是内置字段，不能当格复制",
                    )
                if key not in keys:
                    raise AppException(
                        status_code=400, message=f"{role}批次字段 {key} 不在模板字段集中"
                    )
            value = (cell.value or "").strip()
            if not value:
                raise AppException(
                    status_code=400, message=f"批次字段 {cell.target} 的值不能为空"
                )
            batch_data[cell.target] = value
            links.append(
                {"kind": cell.kind, "source_key": cell.source, "target_key": cell.target}
            )

    existing = await repo.find_report_by_batch(
        db, source.product_id, target_standard.id, source.batch_no
    )
    if existing is None:
        for item in target_items:
            if item.default_value and item.id not in values:
                values[item.id] = CoaValueIn(item_id=str(item.id), value_text=item.default_value)
        report = await create_report(
            db,
            CoaReportCreate(
                product_id=str(source.product_id),
                standard_id=str(target_standard.id),
                batch_no=source.batch_no,
                serial_no=payload.serial_no,
                batch_data=batch_data or None,
                values=list(values.values()),
            ),
            user,
        )
        created = True
    else:
        # 没碰的格原样带回（update 的 values/batch_data 是全量替换语义）；
        # 模板里已移除的项目带不回去（校验只认现有项目），与手工编辑同口径
        old_fields, _ = await resolve_standard_fields(db, existing.standard_id)
        old_batch = compose_batch_info(existing, old_fields)
        merged_batch = {k: v for k, v in old_batch.items() if k in target_keys} | batch_data
        old_values = await repo.list_values_by_report(db, existing.id)
        kept = [
            CoaValueIn(
                item_id=str(v.item_id),
                value_num=v.value_num,
                value_text=v.value_text,
                remark=v.remark,
            )
            for v in old_values
            if v.item_id in target_item_ids and v.item_id not in values
        ]
        report = await update_report(
            db,
            existing.id,
            CoaReportUpdate(batch_data=merged_batch or None, values=kept + list(values.values())),
            user,
        )
        created = False

    actor = _actor_id(user)
    await repo.replace_copy_links(
        db,
        uuid.UUID(report["id"]),
        [
            {**link, "source_report_id": source.id, "created_by": actor, "updated_by": actor}
            for link in links
        ],
    )
    return report | {"created": created}
