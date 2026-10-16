"""Equipment personnel service."""

import logging
import uuid
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateException, NotFoundException
from app.modules.equipment import repository as repo
from app.modules.equipment.deps import EquipmentAccessContext
from app.modules.equipment.models.equipment import Equipment, EquipmentCategory
from app.modules.equipment.models.personnel import (
    EquipmentPersonnel,
    EquipmentRole,
)
from app.modules.equipment.schemas.personnel import (
    CandidateResponse,
    FeishuRefreshResult,
    PersonnelAddRequest,
    PersonnelAddResult,
    PersonnelCategoryAssign,
    PersonnelCategoryInfo,
    PersonnelListResponse,
    PersonnelResponse,
    PersonnelRoleAssign,
    PersonnelRoleInfo,
    PersonnelUpdate,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from app.modules.equipment.service.data_scope import verify_write_ownership
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

# ── 角色 Service ──

async def create_role(db: AsyncSession, data: RoleCreate) -> RoleResponse:
    existing = await repo.get_role_by_code(db, data.code)
    if existing:
        raise DuplicateException("角色编码", data.code)
    role = EquipmentRole(
        name=data.name,
        code=data.code,
        description=data.description,
        scope=data.scope,
        is_active=data.is_active,
    )
    role = await repo.create_role(db, role)
    # eager re-fetch per SQLAlchemy async 铁律
    refetched = await repo.get_role_by_id(db, role.id)
    assert refetched is not None
    return RoleResponse.model_validate(refetched)


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> RoleResponse:
    role = await repo.get_role_by_id(db, role_id)
    if not role:
        raise NotFoundException("角色", str(role_id))
    return RoleResponse.model_validate(role)


async def list_roles(
    db: AsyncSession,
    *,
    scope: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[RoleResponse], int]:
    offset = (page - 1) * page_size
    roles, total = await repo.list_roles(
        db, scope=scope, is_active=is_active, offset=offset, limit=page_size,
    )
    return [RoleResponse.model_validate(r) for r in roles], total


async def update_role(
    db: AsyncSession, role_id: uuid.UUID, data: RoleUpdate
) -> RoleResponse:
    role = await repo.get_role_by_id(db, role_id)
    if not role:
        raise NotFoundException("角色", str(role_id))
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.scope is not None:
        role.scope = data.scope
    if data.is_active is not None:
        role.is_active = data.is_active
    await db.flush()
    # eager re-fetch per SQLAlchemy async 铁律
    refetched = await repo.get_role_by_id(db, role_id)
    assert refetched is not None
    return RoleResponse.model_validate(refetched)


async def delete_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    role = await repo.get_role_by_id(db, role_id)
    if not role:
        raise NotFoundException("角色", str(role_id))
    await repo.soft_delete_role(db, role)


async def get_role_by_code(db: AsyncSession, code: str) -> RoleResponse | None:
    role = await repo.get_role_by_code(db, code)
    if not role:
        return None
    return RoleResponse.model_validate(role)


# ── 人员 Service ──

async def add_personnel(
    db: AsyncSession, data: PersonnelAddRequest
) -> PersonnelAddResult:
    """从 identity.users 中添加人员到设备人员池"""
    result = PersonnelAddResult(added=[], skipped=[], errors=[])

    for user_id in data.user_ids:
        try:
            # 查 identity.users
            user_result = await db.execute(
                select(User).where(
                    User.id == user_id,
                    User.is_deleted == False,  # noqa: E712
                )
            )
            user = user_result.scalar_one_or_none()
            if not user:
                result.errors.append(
                    {"user_id": str(user_id), "reason": "identity.users 中未找到"}
                )
                continue

            # 去重
            existing = await repo.get_personnel_by_user_id(db, user_id)
            if existing:
                result.skipped.append(user_id)
                continue

            # 冗余写入
            personnel = EquipmentPersonnel(
                user_id=user.id,
                name=user.name,
                employee_no=user.employee_no,
                department=user.department,
                feishu_user_id=user.feishu_user_id,
                feishu_open_id=user.feishu_open_id,
                mobile=user.mobile,
            )
            db.add(personnel)
            await db.flush()
            result.added.append(personnel.id)
        except Exception as e:
            logger.warning("批量添加人员失败: user_id=%s, reason=%s", user_id, e)
            result.errors.append({"user_id": str(user_id), "reason": str(e)})

    return result


async def get_personnel(
    db: AsyncSession, personnel_id: uuid.UUID
) -> PersonnelResponse:
    personnel = await repo.get_personnel_by_id(db, personnel_id)
    if not personnel:
        raise NotFoundException("设备人员", str(personnel_id))

    roles = await repo.get_personnel_roles(db, personnel_id)
    categories = await repo.get_personnel_categories(db, personnel_id)

    # 构建分类信息（含 category_name、role_name）
    cat_infos: list[PersonnelCategoryInfo] = []
    if categories:
        cat_ids = [c.category_id for c in categories]
        cat_result = await db.execute(
            select(EquipmentCategory).where(EquipmentCategory.id.in_(cat_ids))
        )
        cat_map = {c.id: c.name for c in cat_result.scalars().all()}

        role_ids_in_cat = {c.role_id for c in categories}
        role_result = await db.execute(
            select(EquipmentRole).where(EquipmentRole.id.in_(role_ids_in_cat))
        )
        role_map = {r.id: r.name for r in role_result.scalars().all()}

        for c in categories:
            cat_infos.append(
                PersonnelCategoryInfo(
                    role_id=c.role_id,
                    role_name=role_map.get(c.role_id, ""),
                    category_id=c.category_id,
                    category_name=cat_map.get(c.category_id, ""),
                )
            )

    # 查 identity.users 获取 avatar_url 和 position
    avatar_url = None
    position = None
    if personnel.user_id:
        user_result = await db.execute(
            select(User).where(User.id == personnel.user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            avatar_url = user.avatar_url
            position = user.position

    return PersonnelResponse(
        id=personnel.id,
        user_id=personnel.user_id,
        name=personnel.name,
        employee_no=personnel.employee_no,
        department=personnel.department,
        position=position,
        avatar_url=avatar_url,
        feishu_user_id=personnel.feishu_user_id,
        feishu_open_id=personnel.feishu_open_id,
        mobile=personnel.mobile,
        extended_attrs=personnel.extended_attrs,
        is_active=personnel.is_active,
        roles=[PersonnelRoleInfo.model_validate(r) for r in roles],
        categories=cat_infos,
        created_at=personnel.created_at,
        updated_at=personnel.updated_at,
    )


async def list_personnel(
    db: AsyncSession,
    ctx: EquipmentAccessContext,
    *,
    role_ids: list[uuid.UUID] | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PersonnelListResponse:
    offset = (page - 1) * page_size
    items, total = await repo.list_personnel(
        db,
        ctx,
        role_ids=role_ids,
        is_active=is_active,
        keyword=keyword,
        offset=offset,
        limit=page_size,
    )

    # 批量查所有人员角色
    all_personnel_ids = [p.id for p in items]
    roles_map: dict[uuid.UUID, list[PersonnelRoleInfo]] = {}
    if all_personnel_ids:
        for pid in all_personnel_ids:
            roles_map[pid] = [
                PersonnelRoleInfo.model_validate(r)
                for r in await repo.get_personnel_roles(db, pid)
            ]

    # 批量查所有人员分类约束
    cat_map: dict[uuid.UUID, list[PersonnelCategoryInfo]] = {
        pid: [] for pid in all_personnel_ids
    }
    if all_personnel_ids:
        cat_rows = await repo.get_personnel_categories_batch(db, all_personnel_ids)
        cat_ids = {c.category_id for c in cat_rows}
        role_ids_in_cat = {c.role_id for c in cat_rows}
        cat_name_map: dict[uuid.UUID, str] = {}
        role_name_map: dict[uuid.UUID, str] = {}
        if cat_ids:
            cat_result = await db.execute(
                select(EquipmentCategory).where(EquipmentCategory.id.in_(cat_ids))
            )
            cat_name_map = {c.id: c.name for c in cat_result.scalars().all()}
        if role_ids_in_cat:
            role_result = await db.execute(
                select(EquipmentRole).where(EquipmentRole.id.in_(role_ids_in_cat))
            )
            role_name_map = {r.id: r.name for r in role_result.scalars().all()}
        for c in cat_rows:
            cat_map.setdefault(c.personnel_id, []).append(
                PersonnelCategoryInfo(
                    role_id=c.role_id,
                    role_name=role_name_map.get(c.role_id, ""),
                    category_id=c.category_id,
                    category_name=cat_name_map.get(c.category_id, ""),
                )
            )

    # 批量查 identity.users 获取 avatar_url 和 position
    user_ids = [p.user_id for p in items if p.user_id]
    user_map: dict[uuid.UUID, User] = {}
    if user_ids:
        user_result = await db.execute(
            select(User).where(User.id.in_(user_ids))
        )
        user_map = {u.id: u for u in user_result.scalars().all()}

    personnel_list: list[PersonnelResponse] = []
    for p in items:
        user = user_map.get(p.user_id) if p.user_id else None
        personnel_list.append(
            PersonnelResponse(
                id=p.id,
                user_id=p.user_id,
                name=p.name,
                employee_no=p.employee_no,
                department=p.department,
                position=user.position if user else None,
                avatar_url=user.avatar_url if user else None,
                feishu_user_id=p.feishu_user_id,
                feishu_open_id=p.feishu_open_id,
                mobile=p.mobile,
                extended_attrs=p.extended_attrs,
                is_active=p.is_active,
                roles=roles_map.get(p.id, []),
                categories=cat_map.get(p.id, []),
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
        )

    return PersonnelListResponse(
        items=personnel_list, total=total, page=page, page_size=page_size,
    )


async def update_personnel(
    db: AsyncSession,
    personnel_id: uuid.UUID,
    data: PersonnelUpdate,
    ctx: EquipmentAccessContext | None = None,
) -> PersonnelResponse:
    personnel = await repo.get_personnel_by_id(db, personnel_id)
    if not personnel:
        raise NotFoundException("设备人员", str(personnel_id))
    if ctx:
        await verify_write_ownership(ctx, personnel, "created_by", "user_id")
    if data.is_active is not None:
        personnel.is_active = data.is_active
    if data.extended_attrs is not None:
        personnel.extended_attrs = data.extended_attrs
    await db.flush()
    return await get_personnel(db, personnel_id)


async def delete_personnel(
    db: AsyncSession,
    personnel_id: uuid.UUID,
    ctx: EquipmentAccessContext | None = None,
) -> None:
    personnel = await repo.get_personnel_by_id(db, personnel_id)
    if not personnel:
        raise NotFoundException("设备人员", str(personnel_id))
    if ctx:
        await verify_write_ownership(ctx, personnel, "created_by", "user_id")
    await repo.soft_delete_personnel_roles(db, personnel_id)
    await repo.soft_delete_personnel_categories(db, personnel_id)
    personnel.is_deleted = True
    await db.flush()


async def assign_roles(
    db: AsyncSession,
    personnel_id: uuid.UUID,
    data: PersonnelRoleAssign,
    ctx: EquipmentAccessContext | None = None,
) -> PersonnelResponse:
    personnel = await repo.get_personnel_by_id(db, personnel_id)
    if not personnel:
        raise NotFoundException("设备人员", str(personnel_id))
    if ctx:
        await verify_write_ownership(ctx, personnel, "created_by", "user_id")
    await repo.soft_delete_personnel_roles(db, personnel_id)
    if data.role_ids:
        await repo.add_personnel_roles(db, personnel_id, data.role_ids)
    return await get_personnel(db, personnel_id)


async def update_categories(
    db: AsyncSession,
    personnel_id: uuid.UUID,
    data: PersonnelCategoryAssign,
    ctx: EquipmentAccessContext | None = None,
) -> PersonnelResponse:
    personnel = await repo.get_personnel_by_id(db, personnel_id)
    if not personnel:
        raise NotFoundException("设备人员", str(personnel_id))
    if ctx:
        await verify_write_ownership(ctx, personnel, "created_by", "user_id")
    await repo.soft_delete_personnel_categories(db, personnel_id)
    if data.categories:
        items = [
            {"role_id": c.role_id, "category_id": c.category_id}
            for c in data.categories
        ]
        await repo.add_personnel_categories(db, personnel_id, items)
    return await get_personnel(db, personnel_id)


async def get_candidates(
    db: AsyncSession,
    role_codes: list[str],
    category_id: uuid.UUID | None = None,
    category_ids: list[uuid.UUID] | None = None,
) -> list[CandidateResponse]:
    """按角色编码查找可分配人员。

    category_id 为 API 兼容的单分类入参；category_ids 供自动指派等内部
    调用方传分类集合（设备多分类并集）。两者都传时以 category_ids 为准。
    """
    role_result = await db.execute(
        select(EquipmentRole).where(
            EquipmentRole.code.in_(role_codes),
            EquipmentRole.is_deleted == False,  # noqa: E712
        )
    )
    roles = list(role_result.scalars().all())
    role_ids = [r.id for r in roles]

    if not role_ids:
        return []

    if category_ids is None and category_id is not None:
        category_ids = [category_id]

    raw = await repo.get_candidates(db, role_ids, category_ids=category_ids)
    return [
        CandidateResponse(
            personnel_id=r["personnel_id"],
            user_id=r["user_id"],
            name=r["name"],
            department=r["department"],
            feishu_user_id=r["feishu_user_id"],
            feishu_open_id=r["feishu_open_id"],
            roles=[
                PersonnelRoleInfo(
                    id=rl["id"], name=rl["name"], code=rl["code"], scope=rl["scope"]
                )
                for rl in r["roles"]
            ],
        )
        for r in raw
    ]


REPAIR_ROLE_CODE = "repair"
"""维修工角色编码：工单自动指派维修人时按此角色筛人。

需在「设备人员管理」预先创建 code=repair 的角色并分配给维修工；
人员可再绑定设备分类做专长约束，未绑定任何分类表示全分类可派。
"""


async def derive_maintainer_for_equipment(
    db: AsyncSession, equipment: "Equipment"
) -> uuid.UUID | None:
    """按设备分类从人员池推导维修人（自动指派用）。

    候选 = 持 REPAIR_ROLE_CODE 角色、与设备同部门、无分类约束或约束与设备
    分类并集（含子孙分类）相交的在岗人员；设备无分类时仅无约束人员可选。
    取第一位绑定平台账号（user_id 非空）者。查不到返回 None——调用方
    不应因无候选而中断建单，由派单超时监控提醒主管人工指派。

    只在设备所属部门内选人：跨部门指派的工单，被指派人在网页端会因数据范围
    校验无法「开始维修」，工单会卡死。
    """
    from sqlalchemy import select as sa_select

    from app.modules.equipment.models.equipment import EquipmentCategoryLink

    # 人员表的 department 存部门名称（与 identity.departments.name 同口径），
    # 设备侧先把 department_id 换成名称；设备没有部门则无人可选。
    if not equipment.department_id:
        return None
    dept_info = await repo.get_department_info(db, equipment.department_id)
    dept_name = dept_info.get("name") if dept_info else None
    if not dept_name:
        return None

    # 显式查分类链接表，不依赖 equipment.category_links 的加载状态
    # （自动建单路径拿到的设备对象未必预加载了该 relationship）
    link_result = await db.execute(
        sa_select(EquipmentCategoryLink.category_id).where(
            EquipmentCategoryLink.equipment_id == equipment.id,
            EquipmentCategoryLink.is_deleted == False,  # noqa: E712
        )
    )
    category_ids: set[uuid.UUID] = set()
    for (category_id,) in link_result.all():
        category_ids.update(
            await repo.get_category_ids_inclusive(db, category_id)
        )

    candidates = await get_candidates(
        db, [REPAIR_ROLE_CODE], category_ids=sorted(category_ids),
    )
    for candidate in candidates:
        if candidate.user_id is not None and candidate.department == dept_name:
            return candidate.user_id
    return None


async def refresh_feishu(db: AsyncSession) -> FeishuRefreshResult:
    """手动刷新所有人员的飞书信息"""
    result = FeishuRefreshResult(total=0, updated=0, skipped=0, unmatched=0)

    stmt = select(EquipmentPersonnel).where(
        EquipmentPersonnel.user_id.isnot(None),
        EquipmentPersonnel.is_deleted == False,  # noqa: E712
    )
    rows = (await db.execute(stmt)).scalars().all()
    result.total = len(rows)

    if not rows:
        return result

    user_ids = [r.user_id for r in rows if r.user_id]
    users_result = await db.execute(
        select(User).where(User.id.in_(user_ids))
    )
    user_map = {u.id: u for u in users_result.scalars().all()}

    for p in rows:
        user = user_map.get(cast(uuid.UUID, p.user_id))
        if not user:
            result.unmatched += 1
            continue

        changed = False
        for field in [
            "name", "employee_no", "department", "mobile",
            "feishu_user_id", "feishu_open_id",
        ]:
            new_val = getattr(user, field, None)
            old_val = getattr(p, field, None)
            if new_val != old_val:
                setattr(p, field, new_val)
                changed = True

        if changed:
            result.updated += 1
        else:
            result.skipped += 1

    await db.flush()
    return result


async def get_personnel_by_id(
    db: AsyncSession, personnel_id: uuid.UUID
) -> PersonnelResponse | None:
    """供 public_api 调用的简洁接口"""
    try:
        return await get_personnel(db, personnel_id)
    except NotFoundException:
        return None
