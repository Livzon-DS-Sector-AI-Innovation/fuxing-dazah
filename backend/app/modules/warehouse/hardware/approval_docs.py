"""五金库出库单据合并查询（领料单 + 报废单，2026-11-25）。

报废出库并入申领的出库全路径后，「申请单据」列表与顶部统计卡需要把两类
单据放进同一个分页里。两表状态同名同义（draft/pending/approved/issued/
rejected/cancelled），按状态直接归入页签。本模块只负责"哪些单据、第几页"
（返回 doc_kind + id），行数据（明细等）由 API 层用各自现有的 response
构造器补全，保证与 /requisitions、/scraps 两个端点的行结构一致。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import String, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.warehouse.hardware.models import HardwareRequisition, HardwareScrap

KIND_REQUISITION = "requisition"
KIND_SCRAP = "scrap"


async def list_outbound_docs(
    db: AsyncSession,
    *,
    kinds: Sequence[str],
    statuses: Sequence[str] | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[tuple[str, UUID]], int]:
    """领料单 + 报废单合并分页：返回 [(doc_kind, id)]（创建时间倒序）与总数。

    kinds 为空直接返回空页；statuses 为空表示不限状态（含草稿/已撤回）。
    """
    selects: list[Any] = []
    for kind, model in ((KIND_REQUISITION, HardwareRequisition), (KIND_SCRAP, HardwareScrap)):
        if kind not in kinds:
            continue
        stmt = select(
            literal(kind, String).label("doc_kind"),
            model.id.label("id"),
            model.created_at.label("created_at"),
        ).where(model.is_deleted.is_(False))
        if statuses:
            stmt = stmt.where(model.status.in_(tuple(statuses)))
        selects.append(stmt)
    if not selects:
        return [], 0

    merged = union_all(*selects).subquery()
    total = await db.scalar(select(func.count()).select_from(merged))
    rows = (
        await db.execute(
            select(merged.c.doc_kind, merged.c.id)
            .order_by(merged.c.created_at.desc(), merged.c.doc_kind, merged.c.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [(str(r[0]), r[1]) for r in rows], int(total or 0)
