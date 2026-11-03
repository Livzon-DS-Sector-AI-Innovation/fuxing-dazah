"""QA 文件版本服务：不可变版本登记、关系锁定、设为当前与启停。"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
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
    Document,
    DocumentFile,
    DocumentMasterLink,
    DocumentVersion,
    ExtractionStatus,
    MasterObject,
    RecordStatus,
    RelationType,
    VersionStatus,
)
from app.modules.qa.repository import (
    get_document,
    get_file_for_version,
    get_links,
    get_master,
    get_version,
)
from app.modules.qa.service._shared import (
    _actor_id,
    _audit,
)
from app.platform.identity.models import User

logger = logging.getLogger(__name__)


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
