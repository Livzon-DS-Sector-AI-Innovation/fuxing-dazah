"""QA 主数据服务：创建/更新/状态切换、别名与外部来源快照、列表与序列化。"""

import logging
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AppException,
    DuplicateException,
    NotFoundException,
)
from app.modules.qa import (
    file_service as file_service,  # 显式再导出，供 api 层与测试补丁使用
)
from app.modules.qa.models import (
    MasterObject,
    MasterObjectAlias,
    MasterObjectSource,
    MasterObjectType,
    RecordStatus,
)
from app.modules.qa.repository import (
    get_aliases,
    get_aliases_for_masters,
    get_master,
    get_sources,
    get_sources_for_masters,
    list_masters,
)
from app.modules.qa.service._shared import (
    _actor_id,
    _audit,
    _require_text,
    _resolve_department_patch,
    _validate_department,
    normalize_code,
    normalize_text,
)
from app.platform.identity.models import User

logger = logging.getLogger(__name__)


_SOURCE_ENTITY_MAP: dict[str, tuple[str, str]] = {
    "PRODUCT": ("production", "product"),
    "MATERIAL": ("production", "intermediate_type"),
    "EQUIPMENT": ("equipment", "equipment"),
}

_SOURCE_ENTITY_ALIASES: dict[tuple[str, str], tuple[str, str]] = {
    ("production", "products"): ("production", "product"),
    ("production", "intermediate_types"): ("production", "intermediate_type"),
    ("production", "intermediatetype"): ("production", "intermediate_type"),
    ("equipment", "equipments"): ("equipment", "equipment"),
}


async def _get_external_source(
    db: AsyncSession,
    object_type: str,
    source_module: str,
    source_entity: str,
    source_id: uuid.UUID,
    user: User | None = None,
) -> tuple[str, str]:
    """校验来源并返回编码/名称快照。

    设备来源是一个带调用上下文的跨模块引用：HTTP/用户触发的写入必须
    通过 ``validate_equipment_references``，这样既不会因猜 UUID 越权，
    又能在首次关联用户自己数据范围内的设备时自动创建 QA 授权。只有
    ``user=None`` 的可信内部任务才使用无上下文摘要接口。
    """
    expected = _SOURCE_ENTITY_MAP.get(object_type)
    normalized_module = source_module.strip().lower()
    normalized_entity = source_entity.strip().lower()
    normalized_module, normalized_entity = _SOURCE_ENTITY_ALIASES.get(
        (normalized_module, normalized_entity), (normalized_module, normalized_entity)
    )
    if expected is None or (normalized_module, normalized_entity) != expected:
        raise AppException(
            status_code=422,
            message=f"{object_type} 仅允许关联 {expected[0]}/{expected[1]} 来源"
            if expected
            else "该主数据类型不支持外部来源",
        )

    brief: Any | None = None
    if normalized_module == "production" and normalized_entity == "product":
        from app.modules.production.public_api import get_product_brief

        brief = await get_product_brief(db, source_id)
    elif normalized_module == "production" and normalized_entity == "intermediate_type":
        from app.modules.production.public_api import get_intermediate_type_brief

        brief = await get_intermediate_type_brief(db, source_id)
    elif normalized_module == "equipment" and normalized_entity == "equipment":
        if user is not None:
            from app.modules.equipment.public_api import validate_equipment_references

            refs = await validate_equipment_references(
                db, user, "qa", [source_id], auto_publish_owned=True
            )
            brief = refs[0] if refs else None
        else:
            from app.modules.equipment.public_api import get_equipment_brief

            brief = await get_equipment_brief(db, source_id)

    if brief is None or not getattr(brief, "is_active", True):
        raise AppException(status_code=422, message="外部来源对象不存在或已停用")
    code = (
        getattr(brief, "code", None)
        or getattr(brief, "equipment_no", None)
        or str(source_id)
    )
    name = (
        getattr(brief, "name", None)
        or getattr(brief, "product_name", None)
        or str(source_id)
    )
    return str(code), str(name)


async def _validate_region_parent(
    db: AsyncSession,
    object_id: uuid.UUID | None,
    parent_id: uuid.UUID | None,
) -> None:
    if parent_id is None:
        return
    if object_id is not None and parent_id == object_id:
        raise AppException(status_code=422, message="区域不能将自身作为父级")
    parent = await get_master(db, parent_id)
    if parent is None or parent.object_type != MasterObjectType.REGION.value:
        raise AppException(status_code=422, message="区域父级不存在或不是区域类型")
    # 沿父链向上检查环路；上限保护异常脏数据。
    seen: set[uuid.UUID] = {object_id} if object_id else set()
    current = parent
    for _ in range(200):
        if current.id in seen:
            raise AppException(status_code=422, message="区域父级关系不能形成循环")
        seen.add(current.id)
        if current.region_parent_id is None:
            return
        next_parent = await get_master(db, current.region_parent_id)
        if next_parent is None:
            return
        current = next_parent
    raise AppException(status_code=422, message="区域层级过深或存在循环")


async def _ensure_master_code_available(
    db: AsyncSession,
    object_type: str,
    code: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(MasterObject).where(
        MasterObject.object_type == object_type,
        MasterObject.normalized_code == code,
    )
    if exclude_id:
        stmt = stmt.where(MasterObject.id != exclude_id)
    # 不过滤 is_deleted：历史停用记录仍占用编码。
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise DuplicateException("主数据编码", code)


async def _ensure_alias_available(
    db: AsyncSession,
    object_id: uuid.UUID,
    normalized_alias: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> None:
    stmt = select(MasterObjectAlias).where(
        MasterObjectAlias.master_object_id == object_id,
        MasterObjectAlias.normalized_alias == normalized_alias,
        MasterObjectAlias.is_deleted.is_(False),
    )
    if exclude_id:
        stmt = stmt.where(MasterObjectAlias.id != exclude_id)
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise DuplicateException("主数据别名", normalized_alias)


async def create_master(
    db: AsyncSession, payload: Any, user: User | None = None
) -> MasterObject:
    object_type = str(payload.object_type).upper()
    if object_type not in {item.value for item in MasterObjectType}:
        raise AppException(status_code=422, message="不支持的 QA 主数据类型")
    code = normalize_code(_require_text(payload.code, "业务编码"))
    name = _require_text(payload.name, "名称")
    await _ensure_master_code_available(db, object_type, code)
    if (
        object_type != MasterObjectType.REGION.value
        and payload.region_parent_id is not None
    ):
        raise AppException(status_code=422, message="只有区域类型可以设置区域父级")
    await _validate_region_parent(db, None, payload.region_parent_id)
    dept_id, dept_name = await _validate_department(
        db,
        payload.responsible_department_id,
        payload.responsible_department_name_snapshot,
    )
    obj = MasterObject(
        object_type=object_type,
        code=code,
        normalized_code=code,
        name=name,
        description=payload.description,
        status=RecordStatus.ACTIVE.value,
        responsible_department_id=dept_id,
        responsible_department_name_snapshot=dept_name,
        region_parent_id=payload.region_parent_id,
        contact_name=payload.contact_name,
        contact_phone=payload.contact_phone,
        contact_email=payload.contact_email,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(obj)
    await db.flush()
    for alias_in in payload.aliases:
        alias = _require_text(getattr(alias_in, "alias", alias_in), "别名")
        if not alias:
            raise AppException(status_code=422, message="别名不能为空")
        normalized = normalize_text(alias)
        await _ensure_alias_available(db, obj.id, normalized)
        db.add(
            MasterObjectAlias(
                master_object_id=obj.id,
                alias=alias,
                normalized_alias=normalized,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
        )
    source_seen: set[tuple[str, str, uuid.UUID]] = set()
    for source_in in payload.sources:
        module = source_in.source_module.strip().lower()
        entity = source_in.source_entity.strip().lower()
        module, entity = _SOURCE_ENTITY_ALIASES.get((module, entity), (module, entity))
        source_key = (module, entity, source_in.source_id)
        if source_key in source_seen:
            raise DuplicateException("来源关联", str(source_in.source_id))
        source_seen.add(source_key)
        if user is None:
            # 保持可信内部任务及旧测试适配器的五参数调用兼容。
            source_code, source_name = await _get_external_source(
                db, object_type, module, entity, source_in.source_id
            )
        else:
            source_code, source_name = await _get_external_source(
                db, object_type, module, entity, source_in.source_id, user
            )
        db.add(
            MasterObjectSource(
                master_object_id=obj.id,
                source_module=module,
                source_entity=entity,
                source_id=source_in.source_id,
                source_code_snapshot=source_code,
                source_name_snapshot=source_name,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
        )
    await db.flush()
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="master_object",
        resource_id=obj.id,
        new_value={"object_type": object_type, "code": code, "name": name},
    )
    return obj


async def update_master(
    db: AsyncSession, object_id: uuid.UUID, payload: Any, user: User | None = None
) -> MasterObject:
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    old = {
        "name": obj.name,
        "status": obj.status,
        "responsible_department_id": obj.responsible_department_id,
        "region_parent_id": str(obj.region_parent_id) if obj.region_parent_id else None,
    }
    aliases = payload.aliases if "aliases" in payload.model_fields_set else None
    sources = payload.sources if "sources" in payload.model_fields_set else None
    data = payload.model_dump(exclude_unset=True, exclude={"aliases", "sources"})
    if "region_parent_id" in data:
        if (
            obj.object_type != MasterObjectType.REGION.value
            and data["region_parent_id"] is not None
        ):
            raise AppException(status_code=422, message="只有区域类型可以设置区域父级")
        await _validate_region_parent(db, obj.id, data["region_parent_id"])
    if "name" in data:
        obj.name = _require_text(data["name"], "名称")
    for key in (
        "description",
        "contact_name",
        "contact_phone",
        "contact_email",
        "remark",
    ):
        if key in data:
            setattr(obj, key, data[key])
    if (
        "responsible_department_id" in data
        or "responsible_department_name_snapshot" in data
    ):
        dept_id, dept_name = await _resolve_department_patch(
            db,
            current_id=obj.responsible_department_id,
            current_name=obj.responsible_department_name_snapshot,
            data=data,
        )
        obj.responsible_department_id, obj.responsible_department_name_snapshot = (
            dept_id,
            dept_name,
        )
    if "region_parent_id" in data:
        obj.region_parent_id = data["region_parent_id"]
    obj.updated_by = _actor_id(user)
    await db.flush()
    if aliases is not None:
        await replace_master_aliases(
            db,
            object_id,
            [
                alias.alias if hasattr(alias, "alias") else str(alias)
                for alias in aliases
            ],
            user,
        )
    if sources is not None:
        await replace_master_sources(db, object_id, sources, user)
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="master_object",
        resource_id=obj.id,
        old_value=old,
        new_value={"name": obj.name, "status": obj.status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_master(db, object_id) or obj


async def set_master_status(
    db: AsyncSession, object_id: uuid.UUID, status: str, user: User | None = None
) -> MasterObject:
    if status not in (RecordStatus.ACTIVE.value, RecordStatus.INACTIVE.value):
        raise AppException(status_code=422, message="状态只能是 active 或 inactive")
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    old = obj.status
    obj.status = status
    obj.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="activate" if status == "active" else "deactivate",
        user=user,
        resource_type="master_object",
        resource_id=obj.id,
        old_value={"status": old},
        new_value={"status": status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_master(db, object_id) or obj


async def add_master_aliases(
    db: AsyncSession,
    object_id: uuid.UUID,
    aliases: Sequence[str],
    user: User | None = None,
) -> list[MasterObjectAlias]:
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    created: list[MasterObjectAlias] = []
    for raw in aliases:
        alias = _require_text(raw, "别名")
        normalized = normalize_text(alias)
        await _ensure_alias_available(db, object_id, normalized)
        row = MasterObjectAlias(
            master_object_id=object_id,
            alias=alias,
            normalized_alias=normalized,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(row)
        created.append(row)
    await db.flush()
    await _audit(
        db,
        action="alias_add",
        user=user,
        resource_type="master_object",
        resource_id=object_id,
        new_value={"aliases": list(aliases)},
    )
    return created


async def replace_master_aliases(
    db: AsyncSession,
    object_id: uuid.UUID,
    aliases: Sequence[str],
    user: User | None = None,
) -> list[MasterObjectAlias]:
    """以软删除方式替换别名集合，保留完整历史。"""
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    for old in await get_aliases(db, object_id):
        old.is_deleted = True
        old.updated_by = _actor_id(user)
    await db.flush()
    rows = await add_master_aliases(db, object_id, aliases, user)
    await _audit(
        db,
        action="aliases_replace",
        user=user,
        resource_type="master_object",
        resource_id=object_id,
        new_value={"aliases": list(aliases)},
    )
    return rows


async def add_master_sources(
    db: AsyncSession,
    object_id: uuid.UUID,
    source_inputs: Sequence[Any],
    user: User | None = None,
) -> list[MasterObjectSource]:
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    if obj.status != RecordStatus.ACTIVE.value:
        raise AppException(status_code=422, message="停用主数据不能新增来源关联")
    created: list[MasterObjectSource] = []
    for source_in in source_inputs:
        module = source_in.source_module.strip().lower()
        entity = source_in.source_entity.strip().lower()
        module, entity = _SOURCE_ENTITY_ALIASES.get((module, entity), (module, entity))
        if user is None:
            code, name = await _get_external_source(
                db, obj.object_type, module, entity, source_in.source_id
            )
        else:
            code, name = await _get_external_source(
                db, obj.object_type, module, entity, source_in.source_id, user
            )
        duplicate = await db.execute(
            select(MasterObjectSource).where(
                MasterObjectSource.master_object_id == object_id,
                MasterObjectSource.source_module == module,
                MasterObjectSource.source_entity == entity,
                MasterObjectSource.source_id == source_in.source_id,
                MasterObjectSource.is_deleted.is_(False),
            )
        )
        if duplicate.scalar_one_or_none() is not None:
            raise DuplicateException("来源关联", str(source_in.source_id))
        row = MasterObjectSource(
            master_object_id=object_id,
            source_module=module,
            source_entity=entity,
            source_id=source_in.source_id,
            source_code_snapshot=code,
            source_name_snapshot=name,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(row)
        created.append(row)
    await db.flush()
    await _audit(
        db,
        action="source_add",
        user=user,
        resource_type="master_object",
        resource_id=object_id,
    )
    return created


async def replace_master_sources(
    db: AsyncSession,
    object_id: uuid.UUID,
    source_inputs: Sequence[Any],
    user: User | None = None,
) -> list[MasterObjectSource]:
    """以软删除方式替换来源集合，来源快照不被覆盖。"""
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    for old in await get_sources(db, object_id):
        old.is_deleted = True
        old.updated_by = _actor_id(user)
    await db.flush()
    rows = await add_master_sources(db, object_id, source_inputs, user)
    await _audit(
        db,
        action="sources_replace",
        user=user,
        resource_type="master_object",
        resource_id=object_id,
        new_value={"source_count": len(rows)},
    )
    return rows


# ───────────────────────── 文件类型与台账 ─────────────────────────


async def _external_briefs(
    db: AsyncSession,
    module: str,
    entity: str,
    ids: Sequence[uuid.UUID],
    user: User | None = None,
) -> list[Any] | None:
    """按来源类型批量取外部摘要；不支持的类型返回 None。"""
    if (module, entity) == ("production", "product"):
        from app.modules.production.public_api import get_product_briefs

        return list(await get_product_briefs(db, ids))
    if (module, entity) == ("production", "intermediate_type"):
        from app.modules.production.public_api import get_intermediate_type_briefs

        return list(await get_intermediate_type_briefs(db, ids))
    if (module, entity) == ("equipment", "equipment"):
        if user is not None:
            from app.modules.equipment.public_api import get_equipment_references_by_ids

            return list(await get_equipment_references_by_ids(db, user, "qa", ids))
        from app.modules.equipment.public_api import get_equipment_briefs

        return list(await get_equipment_briefs(db, ids))
    return None


async def _availability_map(
    db: AsyncSession,
    sources: Sequence[MasterObjectSource],
    user: User | None = None,
) -> dict[uuid.UUID, bool]:
    """批量判断外部来源是否仍可用（对象存在且未停用）。

    逐条校验会让列表页每行打一次跨模块查询；这里按 (来源模块, 来源实体)
    分组，每组只查一次。
    """
    available: dict[uuid.UUID, bool] = {}
    groups: dict[tuple[str, str], list[MasterObjectSource]] = {}
    for source in sources:
        module = source.source_module.strip().lower()
        entity = source.source_entity.strip().lower()
        groups.setdefault(
            _SOURCE_ENTITY_ALIASES.get((module, entity), (module, entity)), []
        ).append(source)

    for (module, entity), rows in groups.items():
        try:
            briefs = await _external_briefs(
                db, module, entity, [row.source_id for row in rows], user
            )
        except Exception:
            logger.debug("来源可用性批量查询失败", exc_info=True)
            briefs = None
        active_ids = (
            {brief.id for brief in briefs if getattr(brief, "is_active", True)}
            if briefs
            else set()
        )
        for row in rows:
            available[row.id] = row.source_id in active_ids
    return available


async def master_to_dict(
    db: AsyncSession, obj: MasterObject, user: User | None = None
) -> dict[str, Any]:
    return (await master_to_dict_batch(db, [obj], user=user))[0]


async def master_to_dict_batch(
    db: AsyncSession,
    objects: Sequence[MasterObject],
    user: User | None = None,
) -> list[dict[str, Any]]:
    """组装主数据输出。

    别名、来源和来源可用性都按整批查询：列表页逐行查会变成 N+1（page_size
    上限 200 时一次列表能打出上千条 SQL）。
    """
    object_ids = [obj.id for obj in objects]
    aliases_by_master = await get_aliases_for_masters(db, object_ids)
    sources_by_master = await get_sources_for_masters(db, object_ids)
    availability = await _availability_map(
        db,
        [source for rows in sources_by_master.values() for source in rows],
        user,
    )

    result: list[dict[str, Any]] = []
    for obj in objects:
        source_items = [
            {
                "id": source.id,
                "source_module": source.source_module,
                "source_entity": source.source_entity,
                "source_id": source.source_id,
                "source_code_snapshot": source.source_code_snapshot,
                "source_name_snapshot": source.source_name_snapshot,
                "source_available": availability.get(source.id, False),
                "created_at": source.created_at,
            }
            for source in sources_by_master.get(obj.id, [])
        ]
        result.append(
            {
                "id": obj.id,
                "object_type": obj.object_type,
                "code": obj.code,
                "name": obj.name,
                "description": obj.description,
                "status": obj.status,
                "responsible_department_id": obj.responsible_department_id,
                "responsible_department_name_snapshot": (
                    obj.responsible_department_name_snapshot
                ),
                "region_parent_id": obj.region_parent_id,
                "contact_name": obj.contact_name,
                "contact_phone": obj.contact_phone,
                "contact_email": obj.contact_email,
                "remark": obj.remark,
                "created_at": obj.created_at,
                "updated_at": obj.updated_at,
                "aliases": [
                    {
                        "id": alias.id,
                        "alias": alias.alias,
                        "normalized_alias": alias.normalized_alias,
                        "created_at": alias.created_at,
                    }
                    for alias in aliases_by_master.get(obj.id, [])
                ],
                "sources": source_items,
                "responsible_department_name": obj.responsible_department_name_snapshot,
                "department_id": obj.responsible_department_id,
                "department_name": obj.responsible_department_name_snapshot,
                "parent_id": obj.region_parent_id,
                "is_active": obj.status == RecordStatus.ACTIVE.value,
                "source_count": len(source_items),
            }
        )
    return result


async def list_master_page(
    db: AsyncSession, **kwargs: Any
) -> tuple[list[MasterObject], int]:
    return await list_masters(db, **kwargs)
