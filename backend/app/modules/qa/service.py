"""QA 模块业务服务。

这里集中编排 QA 自有数据、外部来源快照、不可变文件版本、关系锁定、正文
提取和审计。跨模块查询只通过对方的 ``public_api`` 完成。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
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
    AIAuthorityPolicy,
    Document,
    DocumentChunkBlock,
    DocumentChunkRun,
    DocumentExtractionRun,
    DocumentFile,
    DocumentMasterLink,
    DocumentTextChunk,
    DocumentTextSegment,
    DocumentType,
    DocumentVersion,
    ExtractionRunStatus,
    ExtractionStatus,
    MasterObject,
    MasterObjectAlias,
    MasterObjectSource,
    MasterObjectType,
    RecordStatus,
    RelationType,
    VersionStatus,
)
from app.modules.qa.repository import (
    current_text_segment_condition,
    get_aliases,
    get_aliases_for_masters,
    get_chunk_run,
    get_document,
    get_document_type,
    get_extraction_run,
    get_file,
    get_file_for_version,
    get_latest_chunk_run_any_status,
    get_latest_extraction_run_any_status,
    get_links,
    get_master,
    get_sources,
    get_sources_for_masters,
    get_version,
    get_versions,
    list_chunk_block_locations,
    list_current_chunk_previews,
    list_current_raw_block_previews,
    list_documents,
    list_masters,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User

logger = logging.getLogger(__name__)

# 解析在独立线程中读取对象并执行 XML/PDF 版面处理；租约要覆盖大文件的
# 正常处理时间，同时仍由调度器在明确过期后回收。
EXTRACTION_LEASE_MINUTES = 30

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


def normalize_code(value: str) -> str:
    return " ".join(value.strip().upper().split())


def normalize_text(value: str) -> str:
    return " ".join(value.strip().upper().split())


def _require_text(value: Any, label: str) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        raise AppException(status_code=422, message=f"{label}不能为空")
    return text_value


def _actor_id(user: User | None) -> uuid.UUID | None:
    return user.id if user is not None else None


async def _audit(
    db: AsyncSession,
    *,
    action: str,
    user: User | None,
    resource_type: str,
    resource_id: uuid.UUID | None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    await record_audit_log(
        db,
        action=action,
        user=user,
        user_id=_actor_id(user),
        resource_type=f"qa.{resource_type}",
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        extra=extra,
    )


async def _validate_department(
    db: AsyncSession,
    department_id: str | None,
    department_name: str | None,
) -> tuple[str | None, str | None]:
    if not department_id:
        if department_name and department_name.strip():
            raise AppException(
                status_code=422, message="责任部门必须使用有效的飞书部门 ID"
            )
        return None, None
    from app.platform.identity.public_api import get_department_brief

    department = await get_department_brief(db, department_id)
    if department is None or not department.is_active:
        raise AppException(status_code=422, message="责任部门不存在或已停用")
    return department.feishu_department_id, department.name


async def _resolve_department_patch(
    db: AsyncSession,
    *,
    current_id: str | None,
    current_name: str | None,
    data: dict[str, Any],
) -> tuple[str | None, str | None]:
    """解析主数据/文件台账的部门部分更新并重新取得名称快照。"""
    id_present = "responsible_department_id" in data
    name_present = "responsible_department_name_snapshot" in data
    if id_present:
        return await _validate_department(
            db,
            data.get("responsible_department_id"),
            data.get("responsible_department_name_snapshot"),
        )
    if name_present:
        if current_id:
            return await _validate_department(db, current_id, None)
        if data.get("responsible_department_name_snapshot"):
            raise AppException(
                status_code=422, message="责任部门必须使用有效的飞书部门 ID"
            )
        return None, None
    return current_id, current_name


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


async def create_document_type(
    db: AsyncSession, payload: Any, user: User | None = None
) -> DocumentType:
    code = normalize_code(_require_text(payload.code, "文件类型编码"))
    duplicate = await db.execute(
        select(DocumentType).where(func.upper(DocumentType.code) == code)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise DuplicateException("文件类型编码", code)
    row = DocumentType(
        code=code,
        name=_require_text(payload.name, "文件类型名称"),
        description=(
            payload.description.strip()
            if getattr(payload, "description", None)
            else None
        ),
        ai_source_policy=getattr(
            payload, "ai_source_policy", AIAuthorityPolicy.AUTHORITATIVE.value
        ),
        status=RecordStatus.ACTIVE.value,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(row)
    await db.flush()
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="document_type",
        resource_id=row.id,
        new_value={
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "ai_source_policy": row.ai_source_policy,
        },
    )
    return row


async def update_document_type(
    db: AsyncSession,
    type_id: uuid.UUID,
    payload: Any,
    user: User | None = None,
) -> DocumentType:
    row = await get_document_type(db, type_id)
    if row is None:
        raise NotFoundException("文件类型", str(type_id))
    old = {
        "name": row.name,
        "status": row.status,
        "description": row.description,
        "ai_source_policy": row.ai_source_policy,
    }
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        row.name = _require_text(data["name"], "文件类型名称")
    if "description" in data:
        row.description = data["description"].strip() if data["description"] else None
    if "ai_source_policy" in data and data["ai_source_policy"] is not None:
        row.ai_source_policy = data["ai_source_policy"]
    for key in ("status",):
        if key in data:
            setattr(row, key, data[key])
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="document_type",
        resource_id=row.id,
        old_value=old,
        new_value={
            "name": row.name,
            "status": row.status,
            "description": row.description,
            "ai_source_policy": row.ai_source_policy,
        },
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_document_type(db, type_id) or row


async def create_document(
    db: AsyncSession, payload: Any, user: User | None = None
) -> Document:
    document_no = normalize_code(_require_text(payload.document_no, "文件编号"))
    duplicate = await db.execute(
        select(Document).where(func.upper(Document.document_no) == document_no)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise DuplicateException("文件编号", document_no)
    doc_type = await get_document_type(db, payload.document_type_id)
    if doc_type is None or doc_type.status != RecordStatus.ACTIVE.value:
        raise AppException(status_code=422, message="文件类型不存在或已停用")
    dept_id, dept_name = await _validate_department(
        db,
        payload.responsible_department_id,
        payload.responsible_department_name_snapshot,
    )
    row = Document(
        document_no=document_no,
        title=_require_text(payload.title, "文件标题"),
        document_type_id=payload.document_type_id,
        responsible_department_id=dept_id,
        responsible_department_name_snapshot=dept_name,
        status=RecordStatus.ACTIVE.value,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    db.add(row)
    await db.flush()
    await _audit(
        db,
        action="create",
        user=user,
        resource_type="document",
        resource_id=row.id,
        new_value={"document_no": row.document_no, "title": row.title},
    )
    return row


async def update_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    payload: Any,
    user: User | None = None,
) -> Document:
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    old = {
        "title": row.title,
        "document_type_id": str(row.document_type_id),
        "status": row.status,
        "responsible_department_id": row.responsible_department_id,
    }
    data = payload.model_dump(exclude_unset=True)
    if "title" in data:
        row.title = _require_text(data["title"], "文件标题")
    if "document_type_id" in data and data["document_type_id"] is not None:
        doc_type = await get_document_type(db, data["document_type_id"])
        if doc_type is None or doc_type.status != RecordStatus.ACTIVE.value:
            raise AppException(status_code=422, message="文件类型不存在或已停用")
        row.document_type_id = data["document_type_id"]
    if (
        "responsible_department_id" in data
        or "responsible_department_name_snapshot" in data
    ):
        dept_id, dept_name = await _resolve_department_patch(
            db,
            current_id=row.responsible_department_id,
            current_name=row.responsible_department_name_snapshot,
            data=data,
        )
        row.responsible_department_id, row.responsible_department_name_snapshot = (
            dept_id,
            dept_name,
        )
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="update",
        user=user,
        resource_type="document",
        resource_id=row.id,
        old_value=old,
        new_value={"title": row.title, "status": row.status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_document(db, document_id) or row


async def set_document_status(
    db: AsyncSession, document_id: uuid.UUID, status: str, user: User | None = None
) -> Document:
    if status not in (RecordStatus.ACTIVE.value, RecordStatus.INACTIVE.value):
        raise AppException(status_code=422, message="状态只能是 active 或 inactive")
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    old = row.status
    row.status = status
    row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="activate" if status == "active" else "deactivate",
        user=user,
        resource_type="document",
        resource_id=row.id,
        old_value={"status": old},
        new_value={"status": status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_document(db, document_id) or row


# ───────────────────────── 版本、文件和关系 ─────────────────────────


async def _next_version_sequence(db: AsyncSession, document_id: uuid.UUID) -> int:
    value = await db.scalar(
        select(func.coalesce(func.max(DocumentVersion.version_sequence), 0)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return int(value or 0) + 1


async def create_version(
    db: AsyncSession,
    document_id: uuid.UUID,
    *,
    version_label: str,
    approved_declared: bool,
    filename: str | None,
    content_type: str | None,
    data: bytes,
    user: User | None = None,
) -> DocumentVersion:
    # 同一文件的版本序号由事务内的文档行锁保护，避免并发上传得到相同序号。
    document_result = await db.execute(
        select(Document)
        .where(Document.id == document_id, Document.is_deleted.is_(False))
        .with_for_update()
    )
    document = document_result.scalar_one_or_none()
    if document is None:
        raise NotFoundException("质量文件", str(document_id))
    if document.status != RecordStatus.ACTIVE.value:
        raise AppException(status_code=422, message="停用文件不能登记新版本")
    label = version_label.strip()
    if not label:
        raise AppException(status_code=422, message="版本标签不能为空")
    if len(label) > 64:
        raise AppException(status_code=422, message="版本标签不能超过 64 个字符")
    duplicate = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            func.lower(DocumentVersion.version_label) == label.lower(),
            DocumentVersion.is_deleted.is_(False),
        )
    )
    if duplicate.scalar_one_or_none() is not None:
        raise DuplicateException("版本标签", label)
    if not approved_declared:
        raise AppException(
            status_code=422,
            message="必须确认该文件已在现行正式流程中批准",
        )

    # 先校验并写入私有存储；任意数据库失败由调用方/这里负责清理孤儿对象。
    # store_file 内部含 50MB 级 SHA-256 与阻塞的 MinIO PUT，放进线程池避免卡事件循环。
    stored = await asyncio.to_thread(
        file_service.store_file,
        filename,
        content_type,
        data,
    )
    try:
        version = DocumentVersion(
            document_id=document_id,
            version_label=label,
            version_sequence=await _next_version_sequence(db, document_id),
            approved_declared=True,
            status=VersionStatus.REGISTERED.value,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(version)
        await db.flush()
        file_row = DocumentFile(
            version_id=version.id,
            storage_key=stored.key,
            original_filename=stored.original_filename,
            extension=stored.extension,
            mime_type=stored.mime_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            extraction_status=ExtractionStatus.QUEUED.value,
            retry_count=0,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(file_row)
        await db.flush()
        await _audit(
            db,
            action="version_create",
            user=user,
            resource_type="document_version",
            resource_id=version.id,
            new_value={
                "document_id": str(document_id),
                "version_label": label,
                "approved_declared": True,
                "sha256": stored.sha256,
                "size_bytes": stored.size_bytes,
            },
        )
        return version
    except Exception:
        # session 会在外层 rollback；对象存储不参加 DB 事务，必须显式清理。
        file_service.cleanup_stored_file(stored)
        raise


async def _get_version_with_document_lock(
    db: AsyncSession, version_id: uuid.UUID
) -> DocumentVersion | None:
    """按统一顺序锁定版本所属文档，并在获得锁后重新读取版本状态。"""
    candidate = await get_version(db, version_id)
    if candidate is None:
        return None
    document_result = await db.execute(
        select(Document)
        .where(
            Document.id == candidate.document_id,
            Document.is_deleted.is_(False),
        )
        .with_for_update()
    )
    if document_result.scalar_one_or_none() is None:
        return None
    version = await get_version(db, version_id)
    if version is None or version.document_id != candidate.document_id:
        return None
    return version


async def set_relations(
    db: AsyncSession,
    version_id: uuid.UUID,
    relation_inputs: Sequence[Any],
    user: User | None = None,
) -> list[DocumentMasterLink]:
    version = await _get_version_with_document_lock(db, version_id)
    if version is None:
        raise NotFoundException("文件版本", str(version_id))
    # 关联属于文件台账元数据：登记版本和现行版本都可以人工维护（现行
    # 版本上的每次变更仍走 relations_update 审计），只有历史/停用版本
    # 作为过审快照冻结。
    if version.status not in {
        VersionStatus.REGISTERED.value,
        VersionStatus.CURRENT.value,
    }:
        raise AppException(status_code=409, message="历史或停用版本不能修改关联")
    seen: set[tuple[uuid.UUID, str]] = set()
    valid: list[tuple[MasterObject, str]] = []
    for relation in relation_inputs:
        relation_type = str(relation.relation_type).upper()
        if relation_type != RelationType.APPLIES_TO.value:
            raise AppException(status_code=422, message="V1 仅支持 APPLIES_TO 关联")
        obj = await get_master(db, relation.master_object_id)
        if obj is None:
            raise NotFoundException("关联主数据", str(relation.master_object_id))
        if obj.status != RecordStatus.ACTIVE.value:
            raise AppException(status_code=422, message="停用主数据不能建立新关联")
        key = (obj.id, relation_type)
        if key not in seen:
            seen.add(key)
            valid.append((obj, relation_type))

    # 用软删除替换集合，不物理删除历史关系。
    existing = await db.execute(
        select(DocumentMasterLink).where(
            DocumentMasterLink.version_id == version_id,
            DocumentMasterLink.is_deleted.is_(False),
        )
    )
    old_rows = list(existing.scalars())
    for row in old_rows:
        row.is_deleted = True
        row.updated_by = _actor_id(user)
    result: list[DocumentMasterLink] = []
    for obj, relation_type in valid:
        row = DocumentMasterLink(
            version_id=version_id,
            master_object_id=obj.id,
            relation_type=relation_type,
            code_snapshot=obj.code,
            name_snapshot=obj.name,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(row)
        result.append(row)
    await db.flush()
    await _audit(
        db,
        action="relations_update",
        user=user,
        resource_type="document_version",
        resource_id=version_id,
        old_value={"count": len(old_rows)},
        new_value={
            "count": len(result),
            "master_object_ids": [str(o.id) for o, _ in valid],
        },
    )
    return result


async def set_relations_append(
    db: AsyncSession,
    version_id: uuid.UUID,
    master_object_ids: Sequence[uuid.UUID],
    user: User | None = None,
    *,
    audit: bool = True,
    prune_missing: bool = False,
) -> list[DocumentMasterLink]:
    """以追加语义写入关联：只新增传入对象，默认保留全部既有关系。

    ``set_relations`` 保留 PUT 的全量人工替换语义；AI 确认入口先计算
    current + additions - explicit removals，再以 ``prune_missing=True``
    显式表达删除，因而不会因候选列表不完整而隐式删除既有关系。提案
    审批通过的自动关联是同一人工决定的附属动作，只传新增对象、默认
    不清理既有关系；经 ``audit=False`` 跳过独立审计，只在提案审批的
    审计记录里体现。
    """

    version = await _get_version_with_document_lock(db, version_id)
    if version is None:
        raise NotFoundException("文件版本", str(version_id))
    # 与 set_relations 的全量替换同一道闸门：登记/现行可写，历史/停用冻结。
    if version.status not in {
        VersionStatus.REGISTERED.value,
        VersionStatus.CURRENT.value,
    }:
        raise AppException(status_code=409, message="历史或停用版本不能修改关联")

    requested_ids = list(dict.fromkeys(master_object_ids))
    existing_result = await db.execute(
        select(DocumentMasterLink)
        .where(
            DocumentMasterLink.version_id == version_id,
            DocumentMasterLink.is_deleted.is_(False),
        )
        .with_for_update()
    )
    existing_rows = list(existing_result.scalars())
    existing_by_id = {row.master_object_id: row for row in existing_rows}
    existing_ids = set(existing_by_id)
    new_ids = [
        object_id for object_id in requested_ids if object_id not in existing_ids
    ]

    # 追加确认只对新增/人工选择的对象要求 active；历史正式关系即使其
    # 主数据后来停用也必须保留，除非用户显式把它放进 remove 集合（调用方
    # 已经通过最终集合表达了这层语义）。新对象按 ID 排序加锁，避免在状态
    # 校验和插入之间被并发停用。
    locked_new: dict[uuid.UUID, MasterObject] = {}
    if new_ids:
        master_result = await db.execute(
            select(MasterObject)
            .where(
                MasterObject.id.in_(new_ids),
                MasterObject.is_deleted.is_(False),
            )
            .order_by(MasterObject.id)
            .with_for_update()
        )
        locked_new = {row.id: row for row in master_result.scalars()}
    valid_new: list[MasterObject] = []
    for object_id in new_ids:
        obj = locked_new.get(object_id)
        if obj is None:
            raise NotFoundException("关联主数据", str(object_id))
        if obj.status != RecordStatus.ACTIVE.value:
            raise AppException(status_code=422, message="停用主数据不能建立新关联")
        valid_new.append(obj)

    requested_set = set(requested_ids)
    result: list[DocumentMasterLink] = []
    for row in existing_rows:
        if prune_missing and row.master_object_id not in requested_set:
            row.is_deleted = True
            row.updated_by = _actor_id(user)
        else:
            result.append(row)
    for obj in valid_new:
        row = DocumentMasterLink(
            version_id=version_id,
            master_object_id=obj.id,
            relation_type=RelationType.APPLIES_TO.value,
            code_snapshot=obj.code,
            name_snapshot=obj.name,
            created_by=_actor_id(user),
            updated_by=_actor_id(user),
        )
        db.add(row)
        result.append(row)
    # 追加语义下返回集合包含未出现在本次请求里的既有关系，排序键需容忍缺省。
    order = {object_id: index for index, object_id in enumerate(requested_ids)}
    result.sort(key=lambda row: order.get(row.master_object_id, len(order)))
    await db.flush()
    if audit:
        await _audit(
            db,
            action="relations_update",
            user=user,
            resource_type="document_version",
            resource_id=version_id,
            old_value={"count": len(existing_rows)},
            new_value={
                "count": len(result),
                "master_object_ids": [str(item) for item in requested_ids],
                "append_semantics": True,
            },
        )
    return result


async def copy_current_relations(
    db: AsyncSession,
    document_id: uuid.UUID,
    target_version_id: uuid.UUID,
    user: User | None = None,
) -> list[DocumentMasterLink]:
    document = await get_document(db, document_id)
    target = await get_version(db, target_version_id)
    if document is None or target is None or target.document_id != document_id:
        raise NotFoundException("文件版本", str(target_version_id))
    if document.current_version_id is None:
        return []
    current_links = await get_links(db, document.current_version_id)

    # Relations are copied explicitly by this endpoint; no silent inheritance.
    class _Relation:
        def __init__(self, object_id: uuid.UUID, relation_type: str):
            self.master_object_id = object_id
            self.relation_type = relation_type

    return await set_relations(
        db,
        target_version_id,
        [_Relation(r.master_object_id, r.relation_type) for r in current_links],
        user,
    )


async def make_current(
    db: AsyncSession,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User | None = None,
) -> DocumentVersion:
    # 文档行锁保证并发请求最多产生一个 current 指针。
    result = await db.execute(
        select(Document)
        .where(
            Document.id == document_id,
            Document.is_deleted.is_(False),
        )
        .with_for_update()
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise NotFoundException("质量文件", str(document_id))
    if document.status != RecordStatus.ACTIVE.value:
        raise AppException(status_code=422, message="停用文件不能设置当前版本")
    version = await get_version(db, version_id)
    if version is None or version.document_id != document_id:
        raise NotFoundException("文件版本", str(version_id))
    if not version.approved_declared:
        raise AppException(status_code=422, message="未声明外部批准的版本不能设为当前")
    if version.status == VersionStatus.INACTIVE.value:
        raise AppException(status_code=422, message="停用版本不能设为当前")
    file_row = await get_file_for_version(db, version.id)
    if file_row is None:
        raise AppException(status_code=422, message="版本缺少主文件")
    now = datetime.now(UTC)
    previous_id = document.current_version_id
    if previous_id == version.id and version.status == VersionStatus.CURRENT.value:
        return version
    if previous_id:
        previous = await get_version(db, previous_id)
        if previous is not None and previous.id != version.id:
            previous.status = VersionStatus.HISTORY.value
            previous.locked_at = previous.locked_at or now
            previous.first_locked_at = previous.first_locked_at or previous.locked_at
            previous.updated_by = _actor_id(user)
            # 必须先落库再提新：同一 flush 内 SQLAlchemy 按主键升序发 UPDATE，若新版本
            # id 较小会先被置为 current，此刻旧版本仍是 current，直接撞
            # uq_qa_document_versions_current（部分唯一索引，非延迟约束）→ 500。
            await db.flush()
    version.status = VersionStatus.CURRENT.value
    version.locked_at = version.locked_at or now
    version.first_locked_at = version.first_locked_at or version.locked_at
    version.updated_by = _actor_id(user)
    document.current_version_id = version.id
    document.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="make_current",
        user=user,
        resource_type="document_version",
        resource_id=version.id,
        old_value={"current_version_id": str(previous_id) if previous_id else None},
        new_value={"current_version_id": str(version.id), "sha256": file_row.sha256},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_version(db, version_id) or version


async def disable_version(
    db: AsyncSession, version_id: uuid.UUID, user: User | None = None
) -> DocumentVersion:
    version = await _get_version_with_document_lock(db, version_id)
    if version is None:
        raise NotFoundException("文件版本", str(version_id))
    if version.status == VersionStatus.CURRENT.value:
        raise AppException(
            status_code=409, message="当前版本不能直接停用，请先切换当前版本"
        )
    version.status = VersionStatus.INACTIVE.value
    version.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="disable",
        user=user,
        resource_type="document_version",
        resource_id=version.id,
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_version(db, version_id) or version


async def activate_version(
    db: AsyncSession, version_id: uuid.UUID, user: User | None = None
) -> DocumentVersion:
    """重新启用一个已停用版本，同时保持系统计算的锁定状态。"""
    version = await _get_version_with_document_lock(db, version_id)
    if version is None:
        raise NotFoundException("文件版本", str(version_id))
    if version.status != VersionStatus.INACTIVE.value:
        return version
    # 已经锁定的版本不能回到可编辑的 registered；重新启用后仍是历史版本。
    version.status = (
        VersionStatus.HISTORY.value
        if version.locked_at is not None or version.first_locked_at is not None
        else VersionStatus.REGISTERED.value
    )
    version.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="activate",
        user=user,
        resource_type="document_version",
        resource_id=version.id,
        new_value={"status": version.status},
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_version(db, version_id) or version


async def process_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    *,
    worker_token: str | None = None,
) -> DocumentFile:
    """处理正文并生成 raw block/chunk。

    解析运行和分块运行都是追加记录，旧数据不被覆盖；``current_*`` 指针
    只在新运行成功（包括明确的 text_not_available/unsupported）后更新。
    文件读取和 CPU 解析在事务锁之外执行，数据库只在写入阶段短暂 flush。
    """
    # 直接调用（例如人工重试/本地脚本）也必须先取得短暂的文件行锁，
    # 否则两个入口都可能在看到 NULL token 后各自创建解析运行。调度器
    # 已领取的 token 不允许被无 token 的调用“加入”，避免并行 worker 共用
    # 一个运行身份。
    claim_result = await db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.id == file_id,
            DocumentFile.is_deleted.is_(False),
        )
        .with_for_update()
    )
    file_row = claim_result.scalar_one_or_none()
    if file_row is None:
        raise NotFoundException("文件", str(file_id))
    if worker_token is None and file_row.extraction_worker_token:
        return file_row
    lease_token = worker_token or uuid.uuid4().hex
    if (
        file_row.extraction_worker_token
        and file_row.extraction_worker_token != lease_token
    ):
        # 旧 worker 的租约已被回收，禁止覆盖新运行结果。
        return file_row
    from app.modules.qa.document_processing import (
        CHUNK_VERSION,
        PARSER_VERSION,
    )

    # 调度器在网络/进程边界可能发生至少一次投递；同一个 lease token
    # 已经有 processing run 时直接复用，避免重复追加 raw block/chunk。
    existing_run_result = await db.execute(
        select(DocumentExtractionRun)
        .where(
            DocumentExtractionRun.file_id == file_id,
            DocumentExtractionRun.worker_token == lease_token,
            DocumentExtractionRun.status == ExtractionRunStatus.PROCESSING.value,
            DocumentExtractionRun.is_deleted.is_(False),
        )
        .with_for_update()
    )
    existing_run = existing_run_result.scalar_one_or_none()
    if existing_run is not None:
        return file_row

    parser_mode = (file_row.parser_mode or "native_text").strip() or "native_text"
    input_hash = hashlib.sha256(
        # 解析输入哈希只描述原文件和解析器；分块版本单独进入 chunk
        # 运行哈希，便于未来只升级分块算法时复用 raw block。
        f"{file_row.sha256}:{parser_mode}:{PARSER_VERSION}".encode()
    ).hexdigest()
    extraction_run = DocumentExtractionRun(
        file_id=file_id,
        sha256=file_row.sha256,
        input_hash=input_hash,
        parser_mode=parser_mode,
        parser_version=PARSER_VERSION,
        status=ExtractionRunStatus.PROCESSING.value,
        started_at=datetime.now(UTC),
        worker_token=lease_token,
        lease_until=datetime.now(UTC) + timedelta(minutes=EXTRACTION_LEASE_MINUTES),
        created_by=file_row.updated_by,
        updated_by=file_row.updated_by,
    )
    # lease_until 仅用于追踪/回收；解析函数本身不持有行锁。
    db.add(extraction_run)
    file_row.extraction_status = ExtractionStatus.PROCESSING.value
    file_row.extraction_error = None
    file_row.extraction_worker_token = lease_token
    file_row.extraction_lease_until = extraction_run.lease_until
    await db.flush()
    # flush 后 ID 已确定；提前保存，异常 rollback 后不依赖已过期 ORM 属性。
    extraction_run_id = extraction_run.id
    # claim/run 元数据先提交；对象读取和解析期间不持有 document_files 行锁。
    await db.commit()
    try:
        stored = await asyncio.to_thread(
            file_service.read_file,
            file_row.storage_key,
        )
        if stored is None:
            raise FileNotFoundError("私有存储对象不存在")
        data, _ = stored
        parsed = await asyncio.to_thread(
            file_service.extract_document,
            file_row.extension.lower(),
            data,
            mode=parser_mode,
        )
        # 这里不做 refresh 预检租约：紧随其后的 select ... with_for_update 已经
        # 用同一个 worker_token 原子确认归属，重复预检既违反 async 禁 refresh
        # 规则，也会在文件行被并发软删时抛 InvalidRequestError 覆盖掉下面的
        # STALE 分支。
        # 解析完成后再取得文件行锁。这样在开始替换 raw/chunk 前可以原子确认
        # lease token，锁会一直持有到本次结果提交，旧 worker 不会在提交窗口覆盖新结果。
        claim_result = await db.execute(
            select(DocumentFile)
            .where(
                DocumentFile.id == file_id,
                DocumentFile.is_deleted.is_(False),
                DocumentFile.extraction_worker_token == lease_token,
            )
            .with_for_update()
        )
        claimed_file = claim_result.scalar_one_or_none()
        if claimed_file is None:
            await db.rollback()
            stale_run = await db.get(DocumentExtractionRun, extraction_run_id)
            if stale_run is not None:
                stale_run.status = ExtractionRunStatus.STALE.value
                stale_run.error = "解析租约已被回收，旧 worker 结果已丢弃"
                stale_run.finished_at = datetime.now(UTC)
                stale_run.worker_token = None
                stale_run.lease_until = None
                await db.commit()
            return await get_file(db, file_id) or file_row
        file_row = claimed_file
        extraction_run.status = parsed.status
        extraction_run.block_count = len(parsed.blocks)
        extraction_run.char_count = sum(len(block.content) for block in parsed.blocks)
        extraction_run.statistics = parsed.statistics
        extraction_run.error = parsed.error
        extraction_run.finished_at = datetime.now(UTC)
        extraction_run.lease_until = None
        extraction_run.worker_token = None

        if parsed.status != ExtractionRunStatus.FAILED.value:
            # raw block 是事实/证据层：按 extraction run 追加保存，不因重解析
            # 覆盖或软删除。当前正文由 DocumentFile.current_extraction_run_id
            # 指针选择，历史分析运行仍可稳定引用原始 segment ID。
            block_rows: dict[int, DocumentTextSegment] = {}
            for block in parsed.blocks:
                row = DocumentTextSegment(
                    file_id=file_id,
                    extraction_run_id=extraction_run.id,
                    source_order=block.source_order,
                    block_type=block.block_type,
                    locator=block.locator,
                    page_number=block.page_number,
                    paragraph_index=block.paragraph_index,
                    table_index=block.table_index,
                    cell_index=block.cell_index,
                    row_index=block.row_index,
                    column_index=block.column_index,
                    heading_path=list(block.heading_path),
                    source_metadata=block.source_metadata,
                    content=block.content,
                    text_hash=block.text_hash,
                    created_by=file_row.updated_by,
                    updated_by=file_row.updated_by,
                )
                db.add(row)
                block_rows[block.source_order] = row
            await db.flush()

            # chunk 与运行一一对应，按 chunk_run_id 隔离当前/历史结果；不软删旧
            # chunk，保证历史 AI 运行和未来 embedding 能继续消费原始上下文。
            chunk_input_hash = hashlib.sha256(
                f"{extraction_run.input_hash}:{CHUNK_VERSION}".encode()
            ).hexdigest()
            # 分块是独立的可回收任务，不能复用上面已经清空的解析租约。
            # 在创建运行记录前保存独立 lease，避免 chunk_run 永远以 NULL
            # 租约落库，导致调度器无法识别/回收卡住的分块任务。
            chunk_lease_until = datetime.now(UTC) + timedelta(
                minutes=EXTRACTION_LEASE_MINUTES
            )
            chunk_run = DocumentChunkRun(
                file_id=file_id,
                extraction_run_id=extraction_run.id,
                chunk_version=CHUNK_VERSION,
                input_hash=chunk_input_hash,
                status=parsed.status,
                chunk_count=len(parsed.chunks),
                char_count=sum(chunk.char_count for chunk in parsed.chunks),
                statistics={"parser_version": PARSER_VERSION},
                started_at=extraction_run.started_at,
                finished_at=datetime.now(UTC),
                worker_token=lease_token,
                lease_until=chunk_lease_until,
                created_by=file_row.updated_by,
                updated_by=file_row.updated_by,
            )
            db.add(chunk_run)
            await db.flush()
            for chunk in parsed.chunks:
                chunk_row = DocumentTextChunk(
                    file_id=file_id,
                    chunk_run_id=chunk_run.id,
                    chunk_order=chunk.chunk_order,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    char_count=chunk.char_count,
                    token_count=chunk.token_count,
                    heading_path=list(chunk.heading_path),
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    source_start=chunk.source_start,
                    source_end=chunk.source_end,
                    chunk_metadata=chunk.metadata,
                    created_by=file_row.updated_by,
                    updated_by=file_row.updated_by,
                )
                db.add(chunk_row)
                await db.flush()
                seen_blocks: set[int] = set()
                offsets_by_order: dict[int, tuple[int | None, int | None]] = {}
                for source_order, char_start, char_end in chunk.block_offsets:
                    previous = offsets_by_order.get(source_order)
                    if previous is None:
                        offsets_by_order[source_order] = (char_start, char_end)
                        continue
                    starts = [
                        value
                        for value in (previous[0], char_start)
                        if value is not None
                    ]
                    ends = [
                        value for value in (previous[1], char_end) if value is not None
                    ]
                    offsets_by_order[source_order] = (
                        min(starts) if starts else None,
                        max(ends) if ends else None,
                    )
                for block_order in chunk.raw_block_orders:
                    if block_order in seen_blocks:
                        continue
                    seen_blocks.add(block_order)
                    raw_row = block_rows.get(block_order)
                    if raw_row is None:
                        continue
                    # 变量名与上面 chunk.block_offsets 的 int 解包区分开：这里的
                    # 偏移允许为 None（旧运行没有 offset 映射）。
                    offset_start, offset_end = offsets_by_order.get(
                        block_order, (None, None)
                    )
                    db.add(
                        DocumentChunkBlock(
                            chunk_id=chunk_row.id,
                            segment_id=raw_row.id,
                            block_order=block_order,
                            char_start=offset_start,
                            char_end=offset_end,
                            created_by=file_row.updated_by,
                            updated_by=file_row.updated_by,
                        )
                    )
            chunk_run.lease_until = None
            chunk_run.worker_token = None
            file_row.current_extraction_run_id = extraction_run.id
            file_row.current_chunk_run_id = chunk_run.id
            file_row.parser_version = PARSER_VERSION
        file_row.extraction_status = parsed.status
        file_row.extraction_error = parsed.error
        file_row.extraction_worker_token = None
        file_row.extraction_lease_until = None
        if parsed.status == ExtractionRunStatus.FAILED.value:
            file_row.retry_count = int(file_row.retry_count or 0) + 1
            extraction_run.retry_count = file_row.retry_count
        else:
            file_row.retry_count = 0
        await db.flush()
        await _audit(
            db,
            action=(
                "extraction_failed"
                if parsed.status == ExtractionRunStatus.FAILED.value
                else "extraction_complete"
            ),
            user=None,
            resource_type="document_file",
            resource_id=file_row.id,
            new_value={
                "status": parsed.status,
                "block_count": len(parsed.blocks),
                "chunk_count": len(parsed.chunks),
            },
            extra={
                "sha256": file_row.sha256,
                "parser_version": PARSER_VERSION,
                "run_id": str(extraction_run.id),
            },
        )
        return file_row
    except asyncio.CancelledError:
        # 调度器超时/停机取消时，回滚本地未提交写入，但故意不清理
        # 已提交的租约 token；由下一轮扫描按 lease_until 回收，避免
        # 旧协程把新 worker 的租约误清掉。
        await db.rollback()
        raise
    except Exception as exc:
        # 解析期间租约可能已经被回收并交给新 worker。不能直接修改
        # ``file_row``/``extraction_run``，否则旧 worker 会把新任务覆盖成
        # FAILED 并清掉新租约。回滚旧事务后按 token + 行锁重新 claim，只有
        # 仍持有本 token 的 worker 才能写失败状态；否则只把自己的运行标记
        # 为 STALE。
        error_text = str(exc)[:2000]
        try:
            await db.rollback()
            claim_result = await db.execute(
                select(DocumentFile)
                .where(
                    DocumentFile.id == file_id,
                    DocumentFile.is_deleted.is_(False),
                    DocumentFile.extraction_worker_token == lease_token,
                )
                .with_for_update()
            )
            claimed_file = claim_result.scalar_one_or_none()
            extraction_row = await db.get(DocumentExtractionRun, extraction_run_id)
            if claimed_file is None:
                # 新 worker 已经取得租约；旧运行只保留为可审计的 stale，
                # 不触碰当前文件状态/租约。
                if extraction_row is not None:
                    extraction_row.status = ExtractionRunStatus.STALE.value
                    extraction_row.error = "解析租约已被回收，旧 worker 结果已丢弃"
                    extraction_row.finished_at = datetime.now(UTC)
                    extraction_row.worker_token = None
                    extraction_row.lease_until = None
                    await db.flush()
                    await db.commit()
                return await get_file(db, file_id) or file_row

            next_retry = int(claimed_file.retry_count or 0) + 1
            claimed_file.extraction_status = ExtractionStatus.FAILED.value
            claimed_file.extraction_error = error_text
            claimed_file.extraction_worker_token = None
            claimed_file.extraction_lease_until = None
            claimed_file.retry_count = next_retry
            if extraction_row is not None:
                extraction_row.status = ExtractionRunStatus.FAILED.value
                extraction_row.error = error_text
                extraction_row.finished_at = datetime.now(UTC)
                extraction_row.worker_token = None
                extraction_row.lease_until = None
                extraction_row.retry_count = next_retry
            await db.flush()
            await _audit(
                db,
                action="extraction_failed",
                user=None,
                resource_type="document_file",
                resource_id=claimed_file.id,
                new_value={
                    "status": claimed_file.extraction_status,
                    "error": error_text,
                },
                extra={
                    "retry_count": next_retry,
                    "sha256": claimed_file.sha256,
                    "parser_version": PARSER_VERSION,
                    "run_id": str(extraction_run_id),
                },
            )
            await db.commit()
            return claimed_file
        except Exception:
            # 失败收尾本身不可用时不要再尝试清理未知 worker 的租约；让
            # 调度器依据 lease_until 回收，并尽量返回数据库中的最新状态。
            logger.exception(
                "QA extraction failure finalization failed",
                extra={"file_id": str(file_id), "run_id": str(extraction_run_id)},
            )
            try:
                await db.rollback()
                return await get_file(db, file_id) or file_row
            except Exception:
                return file_row


async def retry_extraction(
    db: AsyncSession, file_id: uuid.UUID, user: User | None = None
) -> DocumentFile:
    # 人工重试与解析 worker 共用文件行锁：先让正在提交的 worker 完成，
    # 再清理其 token/运行，避免重试事务在 worker 之后把 ready 覆盖回 queued
    # 或反过来误清掉新 worker 的租约。
    file_result = await db.execute(
        select(DocumentFile)
        .where(
            DocumentFile.id == file_id,
            DocumentFile.is_deleted.is_(False),
        )
        .with_for_update()
    )
    file_row = file_result.scalar_one_or_none()
    if file_row is None:
        raise NotFoundException("文件", str(file_id))
    active_runs = await db.execute(
        select(DocumentExtractionRun)
        .where(
            DocumentExtractionRun.file_id == file_id,
            DocumentExtractionRun.status == ExtractionRunStatus.PROCESSING.value,
            DocumentExtractionRun.is_deleted.is_(False),
        )
        .with_for_update()
    )
    for run in active_runs.scalars():
        run.status = ExtractionRunStatus.STALE.value
        run.error = "人工重试已替代当前解析运行"
        run.finished_at = datetime.now(UTC)
        run.worker_token = None
        run.lease_until = None
    file_row.extraction_status = ExtractionStatus.QUEUED.value
    file_row.extraction_error = None
    file_row.retry_count = 0
    file_row.extraction_worker_token = None
    file_row.extraction_lease_until = None
    file_row.updated_by = _actor_id(user)
    await db.flush()
    await _audit(
        db,
        action="extraction_retry",
        user=user,
        resource_type="document_file",
        resource_id=file_id,
    )
    # UPDATE 无 RETURNING：re-fetch 回填 updated_at，否则序列化时 MissingGreenlet
    return await get_file(db, file_id) or file_row


# ───────────────────────── 组装输出 ─────────────────────────


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


async def _relation_dict(db: AsyncSession, row: DocumentMasterLink) -> dict[str, Any]:
    obj = await get_master(db, row.master_object_id)
    return {
        "id": row.id,
        "master_object_id": row.master_object_id,
        "relation_type": row.relation_type,
        "code_snapshot": row.code_snapshot,
        "name_snapshot": row.name_snapshot,
        "object_type": obj.object_type if obj else None,
        "status": obj.status if obj else "inactive",
    }


async def version_to_dict(db: AsyncSession, version: DocumentVersion) -> dict[str, Any]:
    file_row = await get_file_for_version(db, version.id)
    links = await get_links(db, version.id)
    return {
        "id": version.id,
        "document_id": version.document_id,
        "version_label": version.version_label,
        "version_sequence": version.version_sequence,
        "status": version.status,
        "state": version.status,
        "sequence": version.version_sequence,
        "version_no": version.version_sequence,
        "approved_declared": version.approved_declared,
        "is_active": version.status != VersionStatus.INACTIVE.value,
        "locked_at": version.locked_at,
        "first_locked_at": version.first_locked_at,
        "created_at": version.created_at,
        "file": (
            {
                "id": file_row.id,
                "original_filename": file_row.original_filename,
                "extension": file_row.extension,
                "mime_type": file_row.mime_type,
                "size_bytes": file_row.size_bytes,
                "sha256": file_row.sha256,
                "extraction_status": file_row.extraction_status,
                "extraction_error": file_row.extraction_error,
                "retry_count": file_row.retry_count,
                "parser_mode": file_row.parser_mode,
                "parser_version": file_row.parser_version,
                "current_extraction_run_id": file_row.current_extraction_run_id,
                "current_chunk_run_id": file_row.current_chunk_run_id,
                # 新上传文件在 queued/processing 阶段也还没有 parser_version，
                # 不能误报为旧数据；只有已有终态但没有新版运行指针的行才
                # 标记 legacy，提示用户重建解析/分块。
                "legacy": file_row.parser_version is None
                and file_row.current_extraction_run_id is None
                and file_row.extraction_status
                in {
                    ExtractionStatus.READY.value,
                    ExtractionStatus.TEXT_NOT_AVAILABLE.value,
                    ExtractionStatus.UNSUPPORTED.value,
                },
            }
            if file_row
            else None
        ),
        "relations": [await _relation_dict(db, link) for link in links],
    }


def _safe_structure_metadata(value: Any) -> dict[str, Any] | None:
    """保留定位/结构信息，去掉 PDF span 和表格 cell 中的完整正文。"""

    if not isinstance(value, dict):
        return None
    allowed_scalars = {
        "bbox",
        "block_index",
        "line_count",
        "span_count",
        "reading_order",
        "boilerplate_candidate",
        "page_width",
        "page_height",
        "style",
        "numbering",
        "row",
        "row_count",
        "column_count",
        "is_header",
        "is_repeated_header",
    }
    output: dict[str, Any] = {
        key: value[key]
        for key in allowed_scalars
        if key in value
        and isinstance(value[key], (str, int, float, bool, list, dict, type(None)))
    }
    cells = value.get("cells")
    if isinstance(cells, list):
        # cell text 已经由 content_preview 返回；这里仅保留网格和合并信息，
        # 使前端仍能画出表格结构而不绕过正文长度上限。
        safe_cells = [
            {
                key: cell[key]
                for key in ("row", "column", "cell_index", "grid_span", "v_merge")
                if isinstance(cell, dict) and key in cell
            }
            for cell in cells
            if isinstance(cell, dict)
        ]
        output["cells"] = safe_cells[:200]
        if len(safe_cells) > 200:
            output["cells_truncated"] = True
    return output or None


def _safe_chunk_metadata(value: Any) -> dict[str, Any] | None:
    """chunk metadata 仅返回派生统计，不让未来扩展字段绕过正文上限。"""

    if not isinstance(value, dict):
        return None
    allowed = {
        "raw_block_count",
        "contains_table",
        "boilerplate_candidate",
        "boilerplate_block_count",
        "omitted_raw_block_orders",
        "table_header_truncated",
    }
    return {key: value[key] for key in allowed if key in value}


def _run_created_at(row: Any) -> Any:
    # BaseModel.created_at is always present for persisted rows, but keeping this
    # helper tolerant makes the read API compatible with old test doubles.
    return getattr(row, "created_at", None)


def _extraction_run_summary(
    row: Any, current_id: uuid.UUID | None
) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "status": row.status,
        "is_current": current_id is not None and row.id == current_id,
        "parser_mode": row.parser_mode,
        "parser_version": row.parser_version,
        "block_count": int(row.block_count or 0),
        "char_count": int(row.char_count or 0),
        "statistics": row.statistics,
        "error": row.error,
        "retry_count": int(row.retry_count or 0),
        "created_at": _run_created_at(row),
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _chunk_run_summary(row: Any, current_id: uuid.UUID | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row.id,
        "extraction_run_id": row.extraction_run_id,
        "status": row.status,
        "is_current": current_id is not None and row.id == current_id,
        "chunk_version": row.chunk_version,
        "chunk_count": int(row.chunk_count or 0),
        "char_count": int(row.char_count or 0),
        "statistics": row.statistics,
        "error": getattr(row, "error", None),
        "created_at": _run_created_at(row),
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def _bounded_preview(
    value: Any, *, content_limit: int, content_length: int | None = None
) -> tuple[str, int, bool]:
    text = str(value or "")
    length = int(content_length if content_length is not None else len(text))
    return (
        text[:content_limit],
        length,
        length > content_limit or len(text) > content_limit,
    )


async def document_processing_results(
    db: AsyncSession,
    file_id: uuid.UUID,
    *,
    view: str,
    page: int,
    page_size: int,
    content_limit: int,
) -> dict[str, Any]:
    """返回文件解析/分块状态和当前结果的分页预览。

    ``latest_*`` 只用于解释 queued/processing/failed 状态；正文明细始终由
    ``current_*`` 指针（或明确的 legacy 空指针兼容规则）限定，避免在用户
    查看时混入历史解析运行或半写入结果。
    """

    file_row = await get_file(db, file_id)
    if file_row is None:
        raise NotFoundException("文件", str(file_id))

    current_extraction = (
        await get_extraction_run(db, file_row.current_extraction_run_id)
        if file_row.current_extraction_run_id is not None
        else None
    )
    latest_extraction = await get_latest_extraction_run_any_status(db, file_id)
    current_chunk = (
        await get_chunk_run(db, file_row.current_chunk_run_id)
        if file_row.current_chunk_run_id is not None
        else None
    )
    latest_chunk = await get_latest_chunk_run_any_status(db, file_id)
    # 只有没有任何新版解析运行的终态旧文件才允许 raw block legacy 回退。
    # 新上传/重试文件即使暂时没有 current 指针，也不能把旧正文混入本次查看。
    legacy = (
        file_row.parser_version is None
        and file_row.current_extraction_run_id is None
        and latest_extraction is None
        and file_row.extraction_status
        not in {ExtractionStatus.QUEUED.value, ExtractionStatus.PROCESSING.value}
    )

    raw_blocks: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    total = 0
    if view == "raw_blocks":
        rows, total = await list_current_raw_block_previews(
            db,
            file_row,
            page=page,
            page_size=page_size,
            content_limit=content_limit,
            allow_legacy=legacy,
        )
        for row in rows:
            preview, length, truncated = _bounded_preview(
                row.get("content_preview"),
                content_limit=content_limit,
                content_length=row.get("content_length"),
            )
            raw_blocks.append(
                {
                    "id": row["id"],
                    "source_order": row.get("source_order"),
                    "block_type": row["block_type"],
                    "locator": row["locator"],
                    "page_number": row.get("page_number"),
                    "paragraph_index": row.get("paragraph_index"),
                    "table_index": row.get("table_index"),
                    "row_index": row.get("row_index"),
                    "column_index": row.get("column_index"),
                    "heading_path": row.get("heading_path"),
                    "content_preview": preview,
                    "content_length": length,
                    "content_truncated": truncated,
                    "text_hash": row["text_hash"],
                    "structure_metadata": _safe_structure_metadata(
                        row.get("source_metadata")
                    ),
                }
            )
    elif view == "chunks":
        rows, total = await list_current_chunk_previews(
            db,
            file_row,
            page=page,
            page_size=page_size,
            content_limit=content_limit,
        )
        locations = await list_chunk_block_locations(db, [row["id"] for row in rows])
        for row in rows:
            preview, _, truncated = _bounded_preview(
                row.get("content_preview"),
                content_limit=content_limit,
                content_length=row.get("char_count"),
            )
            chunks.append(
                {
                    "id": row["id"],
                    "chunk_order": row["chunk_order"],
                    "char_count": row["char_count"],
                    "token_count": row["token_count"],
                    "heading_path": row.get("heading_path"),
                    "page_start": row.get("page_start"),
                    "page_end": row.get("page_end"),
                    "source_start": row.get("source_start"),
                    "source_end": row.get("source_end"),
                    "content_preview": preview,
                    "content_truncated": truncated,
                    "content_hash": row["content_hash"],
                    "metadata": _safe_chunk_metadata(row.get("chunk_metadata")),
                    "source_blocks": locations.get(row["id"], []),
                }
            )
    else:
        raise AppException(status_code=422, message="view 只能是 raw_blocks 或 chunks")

    return {
        "file_id": file_row.id,
        "extraction_status": file_row.extraction_status,
        "extraction_error": file_row.extraction_error,
        "retry_count": int(file_row.retry_count or 0),
        "parser_mode": file_row.parser_mode,
        "parser_version": file_row.parser_version,
        "legacy": legacy,
        "current_extraction_run": _extraction_run_summary(
            current_extraction, file_row.current_extraction_run_id
        ),
        "latest_extraction_run": _extraction_run_summary(
            latest_extraction, file_row.current_extraction_run_id
        ),
        "current_chunk_run": _chunk_run_summary(
            current_chunk, file_row.current_chunk_run_id
        ),
        "latest_chunk_run": _chunk_run_summary(
            latest_chunk, file_row.current_chunk_run_id
        ),
        "view": view,
        "page": page,
        "page_size": page_size,
        "total": total,
        "raw_blocks": raw_blocks,
        "chunks": chunks,
    }


async def document_to_dict(
    db: AsyncSession, document: Document, *, include_versions: bool = True
) -> dict[str, Any]:
    doc_type = await get_document_type(db, document.document_type_id)
    versions = await get_versions(db, document.id) if include_versions else []
    return {
        "id": document.id,
        "document_no": document.document_no,
        "title": document.title,
        "document_type_id": document.document_type_id,
        "document_type": (
            {
                "id": doc_type.id,
                "code": doc_type.code,
                "name": doc_type.name,
                "status": doc_type.status,
                "description": doc_type.description,
                "ai_source_policy": doc_type.ai_source_policy,
                "created_at": doc_type.created_at,
                "updated_at": doc_type.updated_at,
            }
            if doc_type
            else None
        ),
        "responsible_department_id": document.responsible_department_id,
        "responsible_department_name_snapshot": document.responsible_department_name_snapshot,
        "status": document.status,
        "is_active": document.status == RecordStatus.ACTIVE.value,
        "current_version_id": document.current_version_id,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
        "versions": [await version_to_dict(db, v) for v in versions],
    }


async def document_list_item(db: AsyncSession, document: Document) -> dict[str, Any]:
    doc_type = await get_document_type(db, document.document_type_id)
    versions = await get_versions(db, document.id)
    current = next((v for v in versions if v.id == document.current_version_id), None)
    current_file = await get_file_for_version(db, current.id) if current else None
    return {
        "id": document.id,
        "document_no": document.document_no,
        "title": document.title,
        "document_type_id": document.document_type_id,
        "document_type_name": doc_type.name if doc_type else None,
        "document_type_code": doc_type.code if doc_type else None,
        "responsible_department_id": document.responsible_department_id,
        "responsible_department_name_snapshot": document.responsible_department_name_snapshot,
        "status": document.status,
        "is_active": document.status == RecordStatus.ACTIVE.value,
        "current_version_id": document.current_version_id,
        "current_version_label": current.version_label if current else None,
        "current_extraction_status": current_file.extraction_status
        if current_file
        else None,
        "version_count": len(versions),
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }


# ───────────────────────── 全局检索 ─────────────────────────


def _compact(value: str) -> str:
    """搜索用的紧凑键，允许 ``R101`` 命中 ``R-101``。"""
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _snippet(content: str, query: str, limit: int = 240) -> str:
    clean = " ".join(content.split())
    if len(clean) <= limit:
        return clean
    q = query.strip()
    pos = clean.lower().find(q.lower()) if q else -1
    if pos < 0:
        # 对去标点命中的情况，按首部返回可读片段。
        return clean[: max(0, limit - 1)] + "…"
    start = max(0, pos - 80)
    # 前后省略号也计入上限，保证 API 返回片段不超过 limit 字符。
    prefix = "…" if start else ""
    suffix_budget = 1 if start + limit < len(clean) else 0
    content_limit = max(0, limit - len(prefix) - suffix_budget)
    end = min(len(clean), start + content_limit)
    # 若从中间截取后仍有尾部内容，保留一个省略号字符的预算。
    suffix = "…" if end < len(clean) else ""
    if len(prefix) + len(clean[start:end]) + len(suffix) > limit:
        end = start + max(0, limit - len(prefix) - len(suffix))
    prefix = "…" if start else ""
    return prefix + clean[start:end] + suffix


def _rank(kind: str, field: str, query: str, value: str) -> float:
    q = normalize_text(query)
    v = normalize_text(value)
    if _compact(v) == _compact(q):
        return 100.0 if field in {"code", "document_no"} else 95.0
    if v == q:
        return 98.0 if field in {"code", "document_no"} else 94.0
    if v.startswith(q):
        return 80.0
    if q in v:
        return 70.0 if field in {"name", "title"} else 60.0
    return 0.0


async def search(
    db: AsyncSession,
    query: str,
    *,
    include_history: bool = False,
    include_inactive: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """统一检索主数据、部门、文件及正文片段。

    查询结果在首版按明确的业务优先级排序；PostgreSQL 上模型/迁移提供
    trigram/GIN 索引，Python 层只负责合并跨实体命中和生成片段。
    """
    q = query.strip()
    if not q:
        return [], 0
    q_lower = q.lower()
    compact_q = _compact(q)
    hits: list[dict[str, Any]] = []

    # 主数据、别名及其关联文件。
    master_stmt = select(MasterObject).where(MasterObject.is_deleted.is_(False))
    if not include_inactive:
        master_stmt = master_stmt.where(
            MasterObject.status == RecordStatus.ACTIVE.value
        )
    masters = list((await db.execute(master_stmt)).scalars())
    alias_result = await db.execute(
        select(MasterObjectAlias).where(MasterObjectAlias.is_deleted.is_(False))
    )
    alias_rows = list(alias_result.scalars())
    aliases_by_master: dict[uuid.UUID, list[MasterObjectAlias]] = {}
    for alias in alias_rows:
        aliases_by_master.setdefault(alias.master_object_id, []).append(alias)

    master_ids = [obj.id for obj in masters]
    links_by_master: dict[uuid.UUID, list[DocumentMasterLink]] = {}
    if master_ids:
        link_result = await db.execute(
            select(DocumentMasterLink).where(
                DocumentMasterLink.master_object_id.in_(master_ids),
                DocumentMasterLink.is_deleted.is_(False),
            )
        )
        for link in link_result.scalars():
            links_by_master.setdefault(link.master_object_id, []).append(link)
    linked_version_ids = [
        link.version_id for links in links_by_master.values() for link in links
    ]
    linked_versions: dict[uuid.UUID, DocumentVersion] = {}
    if linked_version_ids:
        version_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.id.in_(linked_version_ids),
                DocumentVersion.is_deleted.is_(False),
            )
        )
        linked_versions = {version.id: version for version in version_result.scalars()}
    linked_document_ids = {version.document_id for version in linked_versions.values()}
    linked_documents: dict[uuid.UUID, Document] = {}
    if linked_document_ids:
        document_result = await db.execute(
            select(Document).where(
                Document.id.in_(linked_document_ids),
                Document.is_deleted.is_(False),
            )
        )
        linked_documents = {
            document.id: document for document in document_result.scalars()
        }

    for obj in masters:
        candidates = [("code", obj.code), ("name", obj.name)]
        candidates.extend(("alias", a.alias) for a in aliases_by_master.get(obj.id, []))
        score = max(
            (_rank("master_object", field, q, value) for field, value in candidates),
            default=0,
        )
        # 紧凑键命中（例如 R101 / R-101）即使普通 SQL contains 不命中也保留。
        if score == 0 and any(
            compact_q and compact_q in _compact(value) for _, value in candidates
        ):
            score = 75.0
        if score:
            hits.append(
                {
                    "kind": "master_object",
                    "id": obj.id,
                    "score": score,
                    "code": obj.code,
                    "name": obj.name,
                    "object_type": obj.object_type,
                    "status": obj.status,
                }
            )

        # 关系命中：返回文件结果，关联快照可用于解释命中。
        links = links_by_master.get(obj.id, [])
        if links:
            for link in links:
                version = linked_versions.get(link.version_id)
                if version is None:
                    continue
                if (
                    not include_history
                    and version.status != VersionStatus.CURRENT.value
                ):
                    continue
                if (
                    not include_inactive
                    and version.status == VersionStatus.INACTIVE.value
                ):
                    continue
                document = linked_documents.get(version.document_id)
                if document is None or (
                    not include_inactive
                    and document.status != RecordStatus.ACTIVE.value
                ):
                    continue
                if not score:
                    continue
                hits.append(
                    {
                        "kind": "document",
                        "id": document.id,
                        "score": max(60.0, score - 20),
                        "code": document.document_no,
                        "title": document.title,
                        "document_id": document.id,
                        "document_no": document.document_no,
                        "version_id": version.id,
                        "version_label": version.version_label,
                        "status": version.status,
                    }
                )

    # 部门是身份平台的只读引用，不复制进 QA。
    try:
        from app.platform.identity.public_api import list_department_briefs

        departments = await list_department_briefs(db, keyword=q)
        for dept in departments:
            score = max(
                _rank("department", "code", q, dept.feishu_department_id),
                _rank("department", "name", q, dept.name),
            )
            if score:
                hits.append(
                    {
                        "kind": "department",
                        "id": dept.id,
                        "score": score,
                        "code": dept.feishu_department_id,
                        "name": dept.name,
                        "status": "active" if dept.is_active else "inactive",
                    }
                )
    except Exception:
        logger.debug("Department search unavailable", exc_info=True)

    # 文件台账、版本和正文片段。这里使用宽松 SQL 初筛，再按业务排序合并。
    doc_stmt = select(Document).where(Document.is_deleted.is_(False))
    if not include_inactive:
        doc_stmt = doc_stmt.where(Document.status == RecordStatus.ACTIVE.value)
    documents = list((await db.execute(doc_stmt)).scalars())
    document_ids = [document.id for document in documents]
    versions_by_document: dict[uuid.UUID, list[DocumentVersion]] = {}
    files_by_version: dict[uuid.UUID, DocumentFile] = {}
    segments_by_file: dict[uuid.UUID, list[DocumentTextSegment]] = {}
    if document_ids:
        version_result = await db.execute(
            select(DocumentVersion).where(
                DocumentVersion.document_id.in_(document_ids),
                DocumentVersion.is_deleted.is_(False),
            )
        )
        versions = list(version_result.scalars())
        for version in versions:
            versions_by_document.setdefault(version.document_id, []).append(version)
        version_ids = [version.id for version in versions]
        if version_ids:
            file_result = await db.execute(
                select(DocumentFile).where(
                    DocumentFile.version_id.in_(version_ids),
                    DocumentFile.is_deleted.is_(False),
                )
            )
            files = list(file_result.scalars())
            files_by_version = {file.version_id: file for file in files}
            file_ids = [file.id for file in files]
            if file_ids:
                segment_result = await db.execute(
                    select(DocumentTextSegment)
                    .join(DocumentFile, DocumentFile.id == DocumentTextSegment.file_id)
                    .where(
                        DocumentTextSegment.file_id.in_(file_ids),
                        DocumentTextSegment.is_deleted.is_(False),
                        DocumentFile.is_deleted.is_(False),
                        current_text_segment_condition(),
                    )
                )
                for segment in segment_result.scalars():
                    segments_by_file.setdefault(segment.file_id, []).append(segment)
    for document in documents:
        doc_score = max(
            _rank("document", "document_no", q, document.document_no),
            _rank("document", "title", q, document.title),
        )
        versions = versions_by_document.get(document.id, [])
        for version in versions:
            if not include_history and version.id != document.current_version_id:
                continue
            if not include_inactive and version.status == VersionStatus.INACTIVE.value:
                continue
            if doc_score:
                hits.append(
                    {
                        "kind": "document",
                        "id": document.id,
                        "score": doc_score,
                        "code": document.document_no,
                        "title": document.title,
                        "document_id": document.id,
                        "document_no": document.document_no,
                        "version_id": version.id,
                        "version_label": version.version_label,
                        "status": version.status,
                    }
                )
            file_row = files_by_version.get(version.id)
            if (
                file_row is None
                or file_row.extraction_status != ExtractionStatus.READY.value
            ):
                continue
            segments = segments_by_file.get(file_row.id, [])
            for segment in segments:
                content = segment.content
                if q_lower in content.lower() or (
                    compact_q and compact_q in _compact(content)
                ):
                    hits.append(
                        {
                            "kind": "document_segment",
                            "id": segment.id,
                            "score": 40.0,
                            "document_id": document.id,
                            "document_no": document.document_no,
                            "title": document.title,
                            "version_id": version.id,
                            "version_label": version.version_label,
                            "snippet": _snippet(content, q),
                            "locator": segment.locator,
                            "page_number": segment.page_number,
                            "paragraph_index": segment.paragraph_index,
                            "table_index": segment.table_index,
                            "row_index": segment.row_index,
                            "column_index": segment.column_index,
                            "segment_type": segment.block_type,
                            "status": version.status,
                        }
                    )

    # 同一文件通过台账和关联对象命中时保留最高分，正文片段独立返回定位。
    hits.sort(
        key=lambda item: (
            -float(item.get("score", 0)),
            str(item.get("document_no") or item.get("code") or ""),
        )
    )
    deduped: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for hit in hits:
        key = (
            hit["kind"],
            hit.get("id"),
            hit.get("version_id"),
            hit.get("locator"),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(hit)
    total = len(deduped)
    start = (page - 1) * page_size
    return deduped[start : start + page_size], total


async def list_audit_logs(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 50,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> tuple[list[Any], int]:
    from app.platform.audit.service import list_audit_logs as _list_audit_logs

    # 审计表由 platform/audit 拥有，这里只绑定 QA 的资源域前缀。
    normalized_resource_type = resource_type
    if normalized_resource_type and not normalized_resource_type.startswith("qa."):
        normalized_resource_type = f"qa.{normalized_resource_type}"
    return await _list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        resource_type_prefix="qa",
        user_id=user_id,
        action=action,
        resource_type=normalized_resource_type,
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
    )


async def list_master_page(
    db: AsyncSession, **kwargs: Any
) -> tuple[list[MasterObject], int]:
    return await list_masters(db, **kwargs)


async def list_document_page(
    db: AsyncSession, **kwargs: Any
) -> tuple[list[Document], int]:
    return await list_documents(db, **kwargs)
