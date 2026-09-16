"""设备跨模块引用授权业务服务。"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, ForbiddenException
from app.modules.equipment import repository as repo
from app.modules.equipment.deps import EquipmentAccessContext, build_access_context
from app.modules.equipment.models import Equipment, EquipmentReferenceGrant
from app.platform.identity.models import User
from app.shared import module_registry

ReferenceSource = Literal["own_scope", "shared"]
REFERENCE_MODULE_EXCLUSIONS = frozenset({"equipment", "toolbox"})


@dataclass(frozen=True)
class EquipmentReference:
    """跨模块可见的最小设备摘要。

    该 DTO 明确不包含供应商、型号、技术参数、资产价值等设备台账字段。
    """

    id: uuid.UUID
    equipment_no: str
    name: str
    status: str | None = None
    is_active: bool = True
    source: ReferenceSource = "shared"

    @property
    def code(self) -> str:
        return self.equipment_no

    @property
    def equipment_code(self) -> str:
        return self.equipment_no

    @property
    def equipment_name(self) -> str:
        return self.name


def validate_target_module(target_module: str) -> str:
    """校验目标模块编码，并拒绝设备/工具箱自身作为引用目标。"""
    # 每次从注册表读取编码集合，而不是依赖模块导入时生成的快照字典；这样
    # 新增业务模块（或运行时注册扩展模块）无需修改设备授权逻辑。
    code = (target_module or "").strip().lower()
    registered_codes = {module.code for module in module_registry.BUSINESS_MODULES}
    if not code or code not in registered_codes:
        raise AppException(
            status_code=422,
            message=f"无效的设备引用目标模块: {target_module}",
        )
    if code in REFERENCE_MODULE_EXCLUSIONS:
        raise AppException(status_code=422, message=f"模块 {code} 不支持设备跨模块引用")
    return code


async def _build_context(
    db: AsyncSession,
    user: User | EquipmentAccessContext | None,
) -> EquipmentAccessContext | None:
    if user is None:
        # None 仅供受信任的内部任务使用；HTTP 层必须注入真实用户。
        return None
    if isinstance(user, EquipmentAccessContext):
        # 允许模块内部已经完成权限解析的调用方复用同一公共契约；不再
        # 重新按 reference 资源查询一次范围，避免上下文被意外替换。
        return user
    return await build_access_context(db, user, resource="asset")


async def _coerce_context(
    db: AsyncSession,
    actor: EquipmentAccessContext | User,
) -> EquipmentAccessContext:
    """兼容服务层直接传 User 或已解析的访问上下文。"""
    if isinstance(actor, EquipmentAccessContext):
        return actor
    context = await _build_context(db, actor)
    assert context is not None
    return context


def _to_reference(equipment: Equipment, source: str) -> EquipmentReference:
    normalized_source: ReferenceSource = (
        "own_scope" if source == "own_scope" else "shared"
    )
    status = getattr(equipment, "status", None)
    return EquipmentReference(
        id=equipment.id,
        equipment_no=equipment.equipment_no,
        name=equipment.name,
        status=status,
        is_active=not bool(getattr(equipment, "is_deleted", False))
        and status != "报废",
        source=normalized_source,
    )


def _normalize_ids(
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
) -> list[uuid.UUID]:
    if ids is None:
        return []
    values: Sequence[uuid.UUID | str]
    if isinstance(ids, (uuid.UUID, str)):
        values = [ids]
    else:
        values = ids
    normalized: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for value in values:
        try:
            equipment_id = value if isinstance(value, uuid.UUID) else uuid.UUID(value)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ForbiddenException("设备不可用或无权关联") from exc
        if equipment_id not in seen:
            normalized.append(equipment_id)
            seen.add(equipment_id)
    return normalized


async def list_equipment_references(
    db: AsyncSession,
    user: User | EquipmentAccessContext | None,
    target_module: str,
    *,
    keyword: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EquipmentReference], int]:
    """查询目标模块可引用设备（自有范围与共享授权的并集）。"""
    target = validate_target_module(target_module)
    if page < 1 or page_size < 1:
        raise AppException(message="分页参数无效")
    ctx = await _build_context(db, user)
    rows, total = await repo.list_reference_equipments(
        db,
        ctx,
        target,
        keyword=keyword,
        status=status,
        page=page,
        page_size=page_size,
    )
    return [_to_reference(equipment, source) for equipment, source in rows], total


async def get_equipment_references_by_ids(
    db: AsyncSession,
    user: User | EquipmentAccessContext | None,
    target_module: str,
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
) -> list[EquipmentReference]:
    """按 ID 返回当前用户可见的设备摘要；未授权 ID 从结果中省略。"""
    target = validate_target_module(target_module)
    normalized_ids = _normalize_ids(ids)
    if not normalized_ids:
        return []
    ctx = await _build_context(db, user)
    rows = await repo.get_reference_equipments_by_ids(
        db,
        ctx,
        target,
        normalized_ids,
    )
    return [_to_reference(equipment, source) for equipment, source in rows]


async def validate_equipment_references(
    db: AsyncSession,
    user: User | EquipmentAccessContext | None,
    target_module: str,
    ids: Sequence[uuid.UUID | str] | uuid.UUID | str | None,
    *,
    auto_publish_owned: bool = True,
) -> list[EquipmentReference]:
    """校验设备关联并在首次关联自有设备时自动发布授权。

    用户请求只要包含一个缺失、报废、撤销或越权 ID，就整体失败，避免调用方
    意外保存部分关联。``user=None`` 代表受信任内部任务，跳过用户数据范围和
    授权表校验，但仍排除软删除/报废设备。
    """
    target = validate_target_module(target_module)
    normalized_ids = _normalize_ids(ids)
    if not normalized_ids:
        return []
    ctx = await _build_context(db, user)
    rows = await repo.get_reference_equipments_by_ids(
        db,
        ctx,
        target,
        normalized_ids,
    )
    if len(rows) != len(normalized_ids):
        raise ForbiddenException("设备不可用或无权关联")

    actor = ctx.user if ctx is not None else None
    if actor is not None and auto_publish_owned:
        owned_ids = await repo.get_owned_equipment_ids(db, ctx, normalized_ids)
        # 单条 INSERT ... ON CONFLICT DO NOTHING 取代逐台「查授权 + upsert」：
        # 既省掉 N 台 3N 次往返与逐条 flush，又天然满足「已存在的行一律不碰」——
        # 已撤销授权必须由设备负责人显式重新授权，不能被自动关联恢复。
        await repo.create_reference_grants_if_absent(
            db,
            sorted(owned_ids),
            target,
            source="auto_association",
            operator_id=actor.id,
        )
    return [_to_reference(equipment, source) for equipment, source in rows]


async def ensure_equipment_reference(
    db: AsyncSession,
    equipment_id: uuid.UUID | str,
    target_module: str,
    *,
    user: User | EquipmentAccessContext | None = None,
) -> EquipmentReference:
    """供其他模块在建立关联前调用的单设备校验/自动发布接口。"""
    rows = await validate_equipment_references(
        db,
        user,
        target_module,
        [equipment_id],
        auto_publish_owned=True,
    )
    return rows[0]


async def grant_equipment_references(
    db: AsyncSession,
    ctx: EquipmentAccessContext | User,
    target_module: str,
    equipment_ids: Sequence[uuid.UUID | str],
    *,
    remark: str | None = None,
) -> list[EquipmentReferenceGrant]:
    """手工授权设备到目标模块。调用方负责检查 manage 权限。"""
    target = validate_target_module(target_module)
    ctx = await _coerce_context(db, ctx)
    normalized_ids = _normalize_ids(equipment_ids)
    if not normalized_ids:
        return []
    owned_ids = await repo.get_owned_equipment_ids(db, ctx, normalized_ids)
    if len(owned_ids) != len(normalized_ids):
        raise ForbiddenException("只能管理自己设备数据范围内的授权")
    grants: list[EquipmentReferenceGrant] = []
    for equipment_id in normalized_ids:
        grants.append(
            await repo.upsert_reference_grant(
                db,
                equipment_id,
                target,
                source="manual",
                operator_id=ctx.user.id,
                remark=remark,
            )
        )
    return grants


async def revoke_equipment_references(
    db: AsyncSession,
    ctx: EquipmentAccessContext | User,
    target_module: str,
    equipment_ids: Sequence[uuid.UUID | str],
) -> list[EquipmentReferenceGrant]:
    """手工撤销设备授权；撤销记录保留并覆盖自有范围。"""
    target = validate_target_module(target_module)
    ctx = await _coerce_context(db, ctx)
    normalized_ids = _normalize_ids(equipment_ids)
    if not normalized_ids:
        return []
    # only_active=False：归属判断只看数据范围。设备报废/软删除后负责人仍必须
    # 能撤销它此前发出的共享授权，否则设备一旦恢复，旧授权会静默复活。
    owned_ids = await repo.get_owned_equipment_ids(
        db, ctx, normalized_ids, only_active=False
    )
    if len(owned_ids) != len(normalized_ids):
        raise ForbiddenException("只能管理自己设备数据范围内的授权")
    return await repo.revoke_reference_grants(
        db,
        normalized_ids,
        target,
        operator_id=ctx.user.id,
    )


async def get_reference_grants(
    db: AsyncSession,
    ctx: EquipmentAccessContext | User,
    target_module: str,
    equipment_ids: Sequence[uuid.UUID | str] | None = None,
) -> list[EquipmentReferenceGrant]:
    """查询当前数据范围内的授权记录。"""
    target = validate_target_module(target_module)
    ctx = await _coerce_context(db, ctx)
    normalized_ids = _normalize_ids(equipment_ids)
    grants = await repo.list_reference_grants(db, target, normalized_ids or None)
    if ctx.is_unrestricted:
        return grants
    allowed = await repo.get_owned_equipment_ids(
        db,
        ctx,
        [grant.equipment_id for grant in grants],
    )
    return [grant for grant in grants if grant.equipment_id in allowed]


def list_reference_target_modules() -> list[dict[str, str]]:
    """返回可被设备授权的动态业务模块列表。"""
    return [
        module.as_dict()
        for module in module_registry.BUSINESS_MODULES
        if module.code not in REFERENCE_MODULE_EXCLUSIONS
    ]


__all__ = [
    "EquipmentReference",
    "REFERENCE_MODULE_EXCLUSIONS",
    "ensure_equipment_reference",
    "get_equipment_references_by_ids",
    "get_reference_grants",
    "grant_equipment_references",
    "list_equipment_references",
    "list_reference_target_modules",
    "revoke_equipment_references",
    "validate_equipment_references",
    "validate_target_module",
]
