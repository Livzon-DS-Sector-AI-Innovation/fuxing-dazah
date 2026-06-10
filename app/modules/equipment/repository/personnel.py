"""Equipment personnel repository."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models.personnel import (
    EquipmentPersonnel,
    EquipmentPersonnelCategory,
    EquipmentPersonnelRole,
    EquipmentRole,
)

# ── 角色 Repository ──

async def create_role(db: AsyncSession, role: EquipmentRole) -> EquipmentRole:
    db.add(role)
    await db.flush()
    return role


async def get_role_by_id(db: AsyncSession, role_id: uuid.UUID) -> EquipmentRole | None:
    result = await db.execute(
        select(EquipmentRole).where(
            EquipmentRole.id == role_id,
            EquipmentRole.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_role_by_code(db: AsyncSession, code: str) -> EquipmentRole | None:
    result = await db.execute(
        select(EquipmentRole).where(
            EquipmentRole.code == code,
            EquipmentRole.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_roles(
    db: AsyncSession,
    *,
    scope: str | None = None,
    is_active: bool | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[EquipmentRole], int]:
    stmt = select(EquipmentRole).where(
        EquipmentRole.is_deleted == False,  # noqa: E712
    )
    count_stmt = select(func.count()).select_from(EquipmentRole).where(
        EquipmentRole.is_deleted == False,  # noqa: E712
    )

    if scope is not None:
        stmt = stmt.where(EquipmentRole.scope == scope)
        count_stmt = count_stmt.where(EquipmentRole.scope == scope)
    if is_active is not None:
        stmt = stmt.where(EquipmentRole.is_active == is_active)
        count_stmt = count_stmt.where(EquipmentRole.is_active == is_active)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(EquipmentRole.created_at).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def soft_delete_role(db: AsyncSession, role: EquipmentRole) -> None:
    role.is_deleted = True
    await db.flush()


# ── 人员 Repository ──

async def get_personnel_by_user_id(
    db: AsyncSession, user_id: uuid.UUID
) -> EquipmentPersonnel | None:
    result = await db.execute(
        select(EquipmentPersonnel).where(
            EquipmentPersonnel.user_id == user_id,
            EquipmentPersonnel.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def get_personnel_by_id(
    db: AsyncSession, personnel_id: uuid.UUID
) -> EquipmentPersonnel | None:
    result = await db.execute(
        select(EquipmentPersonnel).where(
            EquipmentPersonnel.id == personnel_id,
            EquipmentPersonnel.is_deleted == False,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def list_personnel(
    db: AsyncSession,
    *,
    role_ids: list[uuid.UUID] | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> tuple[list[EquipmentPersonnel], int]:
    stmt = select(EquipmentPersonnel).where(
        EquipmentPersonnel.is_deleted == False,  # noqa: E712
    )
    count_stmt = select(func.count()).select_from(EquipmentPersonnel).where(
        EquipmentPersonnel.is_deleted == False,  # noqa: E712
    )

    if is_active is not None:
        stmt = stmt.where(EquipmentPersonnel.is_active == is_active)
        count_stmt = count_stmt.where(EquipmentPersonnel.is_active == is_active)
    if keyword:
        stmt = stmt.where(EquipmentPersonnel.name.ilike(f"%{keyword}%"))
        count_stmt = count_stmt.where(EquipmentPersonnel.name.ilike(f"%{keyword}%"))
    if role_ids:
        stmt = stmt.join(
            EquipmentPersonnelRole,
            EquipmentPersonnelRole.personnel_id == EquipmentPersonnel.id,
        ).where(
            EquipmentPersonnelRole.role_id.in_(role_ids),
            EquipmentPersonnelRole.is_deleted == False,  # noqa: E712
        )
        count_stmt = count_stmt.join(
            EquipmentPersonnelRole,
            EquipmentPersonnelRole.personnel_id == EquipmentPersonnel.id,
        ).where(
            EquipmentPersonnelRole.role_id.in_(role_ids),
            EquipmentPersonnelRole.is_deleted == False,  # noqa: E712
        )

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(EquipmentPersonnel.name).offset(offset).limit(limit).distinct()
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def list_all_personnel_by_user_ids(
    db: AsyncSession, user_ids: list[uuid.UUID]
) -> list[EquipmentPersonnel]:
    """按 user_id 列表查询，用于飞书批量刷新"""
    result = await db.execute(
        select(EquipmentPersonnel).where(
            EquipmentPersonnel.user_id.in_(user_ids),
            EquipmentPersonnel.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


# ── 人员角色关联 Repository ──

async def add_personnel_roles(
    db: AsyncSession, personnel_id: uuid.UUID, role_ids: list[uuid.UUID]
) -> list[EquipmentPersonnelRole]:
    """批量新增人员角色关联（upsert）"""
    records: list[EquipmentPersonnelRole] = []
    for rid in role_ids:
        result = await db.execute(
            select(EquipmentPersonnelRole).where(
                EquipmentPersonnelRole.personnel_id == personnel_id,
                EquipmentPersonnelRole.role_id == rid,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_deleted = False
            records.append(existing)
        else:
            record = EquipmentPersonnelRole(personnel_id=personnel_id, role_id=rid)
            db.add(record)
            records.append(record)
    await db.flush()
    return records


async def get_personnel_roles(
    db: AsyncSession, personnel_id: uuid.UUID
) -> list[EquipmentRole]:
    """获取人员的角色列表"""
    result = await db.execute(
        select(EquipmentRole)
        .join(
            EquipmentPersonnelRole,
            EquipmentPersonnelRole.role_id == EquipmentRole.id,
        )
        .where(
            EquipmentPersonnelRole.personnel_id == personnel_id,
            EquipmentPersonnelRole.is_deleted == False,  # noqa: E712
            EquipmentRole.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def soft_delete_personnel_roles(
    db: AsyncSession, personnel_id: uuid.UUID
) -> None:
    """软删除某人员的所有角色关联"""
    result = await db.execute(
        select(EquipmentPersonnelRole).where(
            EquipmentPersonnelRole.personnel_id == personnel_id,
            EquipmentPersonnelRole.is_deleted == False,  # noqa: E712
        )
    )
    records = result.scalars().all()
    for r in records:
        r.is_deleted = True
    await db.flush()


# ── 人员分类约束 Repository ──

async def add_personnel_categories(
    db: AsyncSession,
    personnel_id: uuid.UUID,
    items: list[dict],  # [{"role_id": ..., "category_id": ...}]
) -> list[EquipmentPersonnelCategory]:
    records: list[EquipmentPersonnelCategory] = []
    for item in items:
        # upsert: 如果已存在（含软删除），恢复它；否则新增
        result = await db.execute(
            select(EquipmentPersonnelCategory).where(
                EquipmentPersonnelCategory.personnel_id == personnel_id,
                EquipmentPersonnelCategory.role_id == item["role_id"],
                EquipmentPersonnelCategory.category_id == item["category_id"],
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.is_deleted = False
            records.append(existing)
        else:
            record = EquipmentPersonnelCategory(
                personnel_id=personnel_id,
                role_id=item["role_id"],
                category_id=item["category_id"],
            )
            db.add(record)
            records.append(record)
    await db.flush()
    return records


async def get_personnel_categories_batch(
    db: AsyncSession, personnel_ids: list[uuid.UUID]
) -> list[EquipmentPersonnelCategory]:
    """批量获取多个人员的分类约束"""
    result = await db.execute(
        select(EquipmentPersonnelCategory).where(
            EquipmentPersonnelCategory.personnel_id.in_(personnel_ids),
            EquipmentPersonnelCategory.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def get_personnel_categories(
    db: AsyncSession, personnel_id: uuid.UUID
) -> list[EquipmentPersonnelCategory]:
    result = await db.execute(
        select(EquipmentPersonnelCategory).where(
            EquipmentPersonnelCategory.personnel_id == personnel_id,
            EquipmentPersonnelCategory.is_deleted == False,  # noqa: E712
        )
    )
    return list(result.scalars().all())


async def soft_delete_personnel_categories(
    db: AsyncSession, personnel_id: uuid.UUID
) -> None:
    result = await db.execute(
        select(EquipmentPersonnelCategory).where(
            EquipmentPersonnelCategory.personnel_id == personnel_id,
            EquipmentPersonnelCategory.is_deleted == False,  # noqa: E712
        )
    )
    records = result.scalars().all()
    for r in records:
        r.is_deleted = True
    await db.flush()


# ── 候选人查询 ──

async def get_candidates(
    db: AsyncSession,
    role_ids: list[uuid.UUID],
    category_id: uuid.UUID | None = None,
) -> list[dict]:
    """按角色查找可分配人员，支持设备分类过滤"""
    base = (
        select(
            EquipmentPersonnel,
            EquipmentRole,
        )
        .join(
            EquipmentPersonnelRole,
            EquipmentPersonnelRole.personnel_id == EquipmentPersonnel.id,
        )
        .join(
            EquipmentRole,
            EquipmentRole.id == EquipmentPersonnelRole.role_id,
        )
        .where(
            EquipmentPersonnel.is_deleted == False,  # noqa: E712
            EquipmentPersonnel.is_active == True,  # noqa: E712
            EquipmentPersonnelRole.is_deleted == False,  # noqa: E712
            EquipmentPersonnelRole.role_id.in_(role_ids),
            EquipmentRole.is_deleted == False,  # noqa: E712
            EquipmentRole.is_active == True,  # noqa: E712
        )
    )

    result = await db.execute(base)
    rows = result.all()

    candidates: dict[uuid.UUID, dict] = {}
    for personnel, role in rows:
        pid = personnel.id
        if pid not in candidates:
            candidates[pid] = {
                "personnel_id": pid,
                "name": personnel.name,
                "department": personnel.department,
                "feishu_user_id": personnel.feishu_user_id,
                "feishu_open_id": personnel.feishu_open_id,
                "roles": [],
            }
        candidates[pid]["roles"].append(
            {"id": role.id, "name": role.name, "code": role.code, "scope": role.scope}
        )

    if category_id is not None:
        # 查所有有分类约束的人员
        constrained_result = await db.execute(
            select(EquipmentPersonnelCategory.personnel_id).where(
                EquipmentPersonnelCategory.is_deleted == False,  # noqa: E712
            )
        )
        constrained_ids = {row[0] for row in constrained_result.all()}

        # 查匹配当前分类的约束
        matched_result = await db.execute(
            select(EquipmentPersonnelCategory).where(
                EquipmentPersonnelCategory.category_id == category_id,
                EquipmentPersonnelCategory.is_deleted == False,  # noqa: E712
            )
        )
        matched = {(r.personnel_id, r.role_id) for r in matched_result.scalars().all()}

        filtered: dict[uuid.UUID, dict] = {}
        for pid, info in candidates.items():
            if pid not in constrained_ids:
                # 无约束 → 入选
                filtered[pid] = info
            else:
                # 有约束 → 只保留匹配的角色
                filtered_roles = [
                    r for r in info["roles"]
                    if (pid, r["id"]) in matched
                ]
                if filtered_roles:
                    info["roles"] = filtered_roles
                    filtered[pid] = info

        return list(filtered.values())

    return list(candidates.values())
