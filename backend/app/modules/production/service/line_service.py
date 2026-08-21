"""产线字典与用户-产线绑定服务。"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, DuplicateException, NotFoundException
from app.modules.production.repository import intermediate as im_repo
from app.modules.production.repository import line as repo
from app.modules.production.schemas.line import (
    LineAssignmentOut,
    LineCreate,
    LineOut,
    LineUpdate,
)
from app.platform.identity.models import User


async def list_lines(db: AsyncSession) -> list[LineOut]:
    items = await repo.list_lines(db)
    return [LineOut.model_validate(line) for line in items]


async def create_line(
    db: AsyncSession, payload: LineCreate, user: User | None,
) -> LineOut:
    """创建产线，检查名称唯一。"""
    if await repo.get_line_by_name(db, payload.name):
        raise DuplicateException("产线名称", payload.name)
    line = await repo.create_line(
        db, name=payload.name,
        remark=payload.remark, created_by=user.id if user else None,
    )
    return LineOut.model_validate(line)


async def update_line(
    db: AsyncSession, line_id: uuid.UUID, payload: LineUpdate, user: User | None,
) -> LineOut:
    """编辑产线，仅更新显式传入的字段（编码创建后不可改）。"""
    line = await repo.get_line(db, line_id)
    if not line:
        raise NotFoundException("产线", str(line_id))
    if payload.name is not None and payload.name != line.name:
        if await repo.get_line_by_name(db, payload.name):
            raise DuplicateException("产线名称", payload.name)
    non_nullable_fields = {"name"}
    for field_name, val in payload.model_dump(exclude_unset=True).items():
        if val is None and field_name in non_nullable_fields:
            continue
        setattr(line, field_name, val)
    if user:
        line.updated_by = user.id
    await db.flush()
    # UPDATE 后 re-fetch，确保 server default 同步
    refreshed = await repo.get_line(db, line_id)
    assert refreshed is not None
    return LineOut.model_validate(refreshed)


async def delete_line(db: AsyncSession, line_id: uuid.UUID, user: User | None) -> None:
    """软删除产线，级联软删其名下活跃绑定。

    历史产出行的 line_id 原样保留，展示端 include_deleted join 照常显示名称。
    """
    line = await repo.get_line(db, line_id)
    if not line:
        raise NotFoundException("产线", str(line_id))
    # 名下仍有混装容器时禁止删除（容器库存/流水归属不可孤儿化）
    if await im_repo.get_mixing_containers_by_line(db, line_id):
        raise AppException(
            status_code=400, message="该产线下存在混装容器，请先删除容器",
        )
    await repo.delete_line_assignments_by_line(db, line_id)
    line.is_deleted = True
    if user:
        line.updated_by = user.id
    await db.flush()


async def _build_assignment_out(
    db: AsyncSession, items: list,
) -> list[LineAssignmentOut]:
    if not items:
        return []
    line_ids = list({a.line_id for a in items})
    lines = await repo.get_lines_by_ids(db, line_ids, include_deleted=True)
    line_map = {ln.id: ln for ln in lines}
    return [
        LineAssignmentOut(
            id=a.id,
            user_id=a.user_id,
            line_id=a.line_id,
            line_name=line_map[a.line_id].name if a.line_id in line_map else None,
            created_at=a.created_at,
        )
        for a in items
    ]


async def list_line_assignments(
    db: AsyncSession, *, line_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
) -> list[LineAssignmentOut]:
    items = await repo.list_line_assignments(db, line_id=line_id, user_id=user_id)
    return await _build_assignment_out(db, items)


async def bind_user_line(
    db: AsyncSession, *, user_id: uuid.UUID, line_id: uuid.UUID,
    created_by: uuid.UUID | None,
) -> LineAssignmentOut:
    """绑定用户到产线。软删过的旧绑定留着，重新绑定直接插新行。"""
    line = await repo.get_line(db, line_id)
    if not line:
        raise NotFoundException("产线", str(line_id))
    if await repo.get_line_assignment(db, user_id, line_id):
        raise DuplicateException("产线绑定", "用户+产线")
    la = await repo.create_line_assignment(
        db, user_id=user_id, line_id=line_id, created_by=created_by,
    )
    outs = await _build_assignment_out(db, [la])
    return outs[0]


async def unbind_user_line(db: AsyncSession, assignment_id: uuid.UUID) -> None:
    ok = await repo.delete_line_assignment(db, assignment_id)
    if not ok:
        raise NotFoundException("产线绑定")


async def get_user_line_ids(db: AsyncSession, user_id: uuid.UUID) -> list[uuid.UUID]:
    """用户当前绑定的产线 ID 列表（供消耗可见性过滤）。"""
    items = await repo.list_line_assignments(db, user_id=user_id)
    return [a.line_id for a in items]


async def resolve_user_line_ids(
    db: AsyncSession,
    user_id: uuid.UUID,
    owner_user_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """产线可见性兜底链：操作人绑定 → 批次负责人绑定 → 皆无则空列表。

    空列表统一语义：未绑定产线的用户不可消耗/产出有产线的中间体，
    仅无产线（line_id=None）的过渡期存量在制品除外。
    """
    line_ids = await get_user_line_ids(db, user_id)
    if line_ids or not owner_user_id:
        return line_ids
    return await get_user_line_ids(db, owner_user_id)
