"""产线字典与用户-产线绑定数据查询。"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models.line import Line, LineAssignment, LineProductLink

# ── 产线字典 ──


async def list_lines(db: AsyncSession) -> list[Line]:
    stmt = (
        select(Line)
        .where(Line.is_deleted == False)  # noqa: E712
        .order_by(Line.created_at)
    )
    return list((await db.execute(stmt)).scalars())


async def get_line(db: AsyncSession, line_id: uuid.UUID) -> Line | None:
    stmt = select(Line).where(
        Line.id == line_id,
        Line.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_line_by_name(db: AsyncSession, name: str) -> Line | None:
    stmt = select(Line).where(
        Line.name == name,
        Line.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_lines_by_ids(
    db: AsyncSession, line_ids: list[uuid.UUID], *, include_deleted: bool = True,
) -> list[Line]:
    """批量取产线。默认含已软删产线，保证历史流水仍能显示名称。"""
    if not line_ids:
        return []
    stmt = select(Line).where(Line.id.in_(line_ids))
    if not include_deleted:
        stmt = stmt.where(Line.is_deleted == False)  # noqa: E712
    return list((await db.execute(stmt)).scalars())


async def create_line(
    db: AsyncSession, *, name: str,
    remark: str | None, created_by: uuid.UUID | None,
) -> Line:
    line = Line(name=name, remark=remark, created_by=created_by)
    db.add(line)
    await db.flush()
    return line


async def delete_line(db: AsyncSession, line_id: uuid.UUID) -> bool:
    stmt = select(Line).where(
        Line.id == line_id,
        Line.is_deleted == False,  # noqa: E712
    )
    line = (await db.execute(stmt)).scalar_one_or_none()
    if not line:
        return False
    line.is_deleted = True
    await db.flush()
    return True


# ── 用户-产线绑定 ──


async def list_line_assignments(
    db: AsyncSession, *, line_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> list[LineAssignment]:
    stmt = select(LineAssignment).where(LineAssignment.is_deleted == False)  # noqa: E712
    if line_id:
        stmt = stmt.where(LineAssignment.line_id == line_id)
    if user_id:
        stmt = stmt.where(LineAssignment.user_id == user_id)
    return list((await db.execute(stmt)).scalars())


async def get_line_assignment(
    db: AsyncSession, user_id: uuid.UUID, line_id: uuid.UUID,
) -> LineAssignment | None:
    stmt = select(LineAssignment).where(
        LineAssignment.user_id == user_id,
        LineAssignment.line_id == line_id,
        LineAssignment.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_line_assignment(
    db: AsyncSession, *, user_id: uuid.UUID, line_id: uuid.UUID,
    created_by: uuid.UUID | None,
) -> LineAssignment:
    la = LineAssignment(user_id=user_id, line_id=line_id, created_by=created_by)
    db.add(la)
    await db.flush()
    return la


async def delete_line_assignment(db: AsyncSession, assignment_id: uuid.UUID) -> bool:
    stmt = select(LineAssignment).where(
        LineAssignment.id == assignment_id,
        LineAssignment.is_deleted == False,  # noqa: E712
    )
    la = (await db.execute(stmt)).scalar_one_or_none()
    if not la:
        return False
    la.is_deleted = True
    await db.flush()
    return True


async def delete_line_assignments_by_line(
    db: AsyncSession, line_id: uuid.UUID,
) -> None:
    """级联软删某产线名下的全部活跃绑定（产线软删时调用）。"""
    items = await list_line_assignments(db, line_id=line_id)
    for la in items:
        la.is_deleted = True
    await db.flush()


# ── 产线-产品关联 ──


async def list_line_product_links(
    db: AsyncSession, *, line_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
) -> list[LineProductLink]:
    stmt = select(LineProductLink).where(LineProductLink.is_deleted == False)  # noqa: E712
    if line_id:
        stmt = stmt.where(LineProductLink.line_id == line_id)
    if product_id:
        stmt = stmt.where(LineProductLink.product_id == product_id)
    return list((await db.execute(stmt)).scalars())


async def get_line_product_link(
    db: AsyncSession, line_id: uuid.UUID, product_id: uuid.UUID,
) -> LineProductLink | None:
    stmt = select(LineProductLink).where(
        LineProductLink.line_id == line_id,
        LineProductLink.product_id == product_id,
        LineProductLink.is_deleted == False,  # noqa: E712
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_line_product_link(
    db: AsyncSession, *, line_id: uuid.UUID, product_id: uuid.UUID,
    created_by: uuid.UUID | None,
) -> LineProductLink:
    link = LineProductLink(
        line_id=line_id, product_id=product_id, created_by=created_by,
    )
    db.add(link)
    await db.flush()
    return link


async def delete_line_product_link(db: AsyncSession, link_id: uuid.UUID) -> bool:
    stmt = select(LineProductLink).where(
        LineProductLink.id == link_id,
        LineProductLink.is_deleted == False,  # noqa: E712
    )
    link = (await db.execute(stmt)).scalar_one_or_none()
    if not link:
        return False
    link.is_deleted = True
    await db.flush()
    return True


async def delete_line_product_links_by_line(
    db: AsyncSession, line_id: uuid.UUID,
) -> None:
    """级联软删某产线名下的全部产品关联（产线软删时调用）。"""
    items = await list_line_product_links(db, line_id=line_id)
    for link in items:
        link.is_deleted = True
    await db.flush()
