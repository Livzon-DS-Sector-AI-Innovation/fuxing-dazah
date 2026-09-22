"""QA 模块 HTTP API。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.exceptions import AppException, NotFoundException
from app.core.response import paginated_response, success_response
from app.modules.qa import ai_analysis, file_service, service
from app.modules.qa.repository import (
    get_ai_run,
    get_document,
    get_file,
    get_latest_ai_run,
    get_master,
    get_versions,
    list_document_types,
)
from app.modules.qa.schemas import (
    AIAnalysisRunOut,
    AIAnalysisTriggerRequest,
    AIRelationConfirmationRequest,
    AliasIn,
    DocumentCreate,
    DocumentProcessingResultOut,
    DocumentTypeCreate,
    DocumentTypeOut,
    DocumentTypeUpdate,
    DocumentUpdate,
    MasterObjectCreate,
    MasterObjectProposalApproveRequest,
    MasterObjectProposalOut,
    MasterObjectSourceOut,
    MasterObjectStatusIn,
    MasterObjectUpdate,
    ProcessingResultView,
    RelationIn,
    SourceLinkIn,
)
from app.platform.identity.models import User
from app.platform.permission.deps import RequireUser, require_permission
from app.shared.module_registry import MODULES_BY_CODE
from app.shared.schemas import ApiResponse

router = APIRouter()
_module = MODULES_BY_CODE["qa"]

_master_create = require_permission("qa:master:create")
_master_update = require_permission("qa:master:update")
_master_deactivate = require_permission("qa:master:deactivate")
_document_create = require_permission("qa:document:create")
_document_update = require_permission("qa:document:update")
_document_deactivate = require_permission("qa:document:deactivate")
_version_create = require_permission("qa:version:create")
_version_current = require_permission("qa:version:make_current")
_version_disable = require_permission("qa:version:disable")
_relation_manage = require_permission("qa:relation:manage")
_config_manage = require_permission("qa:config:manage")
_audit_read = require_permission("qa:audit:read")
_proposal_publish = require_permission("qa:master:create", "qa:master:update")


class AliasUpdateRequest(BaseModel):
    aliases: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, values: list[str]) -> list[str]:
        return [AliasIn(alias=value).alias for value in values]


class SourceUpdateRequest(BaseModel):
    sources: list[SourceLinkIn] = Field(default_factory=list, max_length=50)


class RelationCompatRequest(BaseModel):
    """同时兼容规范的 relations 和前端早期的 master_object_ids。"""

    relations: list[RelationIn] | None = Field(default=None, max_length=200)
    master_object_ids: list[uuid.UUID] | None = Field(default=None, max_length=200)

    def to_relations(self) -> list[RelationIn]:
        if self.relations is not None:
            return self.relations
        return [RelationIn(master_object_id=i) for i in (self.master_object_ids or [])]


def _master_input_compat(payload: MasterObjectCreate) -> MasterObjectCreate:
    return payload


@router.get("/", summary="QA 模块信息")
async def read_module(user: RequireUser) -> dict[str, str]:
    """返回模块元数据；即使是只读信息也要求登录。"""
    return _module.as_dict()


# ───────────────────────── 主数据 ─────────────────────────


@router.get("/master-objects", summary="QA主数据列表")
async def list_master_objects(
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    kind: str | None = Query(default=None),
    object_type: str | None = None,
    keyword: str | None = None,
    status: str | None = None,
    include_inactive: bool = False,
    include_deleted: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    selected_type = object_type or kind
    items, total = await service.list_master_page(
        db,
        object_type=selected_type.upper() if selected_type else None,
        keyword=keyword,
        status=status if status else (None if include_inactive else "active"),
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
    )
    result = await service.master_to_dict_batch(db, items, user=user)
    for item in result:
        # 前端兼容字段；规范字段仍保留。
        item["kind"] = item["object_type"]
        item["is_active"] = item["status"] == "active"
    return paginated_response(result, page, page_size, total)


@router.post("/master-objects", summary="创建QA主数据")
async def create_master_object(
    payload: MasterObjectCreate,
    user: User = Depends(_master_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.create_master(db, payload, user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.get("/master-objects/{object_id}", summary="QA主数据详情")
async def get_master_object(
    object_id: uuid.UUID,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await get_master(db, object_id)
    if obj is None:
        raise NotFoundException("QA主数据", str(object_id))
    data = await service.master_to_dict(db, obj, user=user)
    data["kind"] = data["object_type"]
    data["is_active"] = data["status"] == "active"
    return success_response(data)


@router.put("/master-objects/{object_id}", summary="更新QA主数据")
async def update_master_object(
    object_id: uuid.UUID,
    payload: MasterObjectUpdate,
    user: User = Depends(_master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.update_master(db, object_id, payload, user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.post("/master-objects/{object_id}/status", summary="切换QA主数据状态")
async def change_master_status(
    object_id: uuid.UUID,
    payload: MasterObjectStatusIn,
    user: User = Depends(_master_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.set_master_status(db, object_id, payload.status, user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.post("/master-objects/{object_id}/activate", summary="启用QA主数据")
async def activate_master_object(
    object_id: uuid.UUID,
    user: User = Depends(_master_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.set_master_status(db, object_id, "active", user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.post("/master-objects/{object_id}/deactivate", summary="停用QA主数据")
async def deactivate_master_object(
    object_id: uuid.UUID,
    user: User = Depends(_master_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    obj = await service.set_master_status(db, object_id, "inactive", user)
    return success_response(await service.master_to_dict(db, obj, user=user))


@router.put("/master-objects/{object_id}/aliases", summary="替换QA主数据别名")
async def replace_master_aliases(
    object_id: uuid.UUID,
    payload: AliasUpdateRequest,
    user: User = Depends(_master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.replace_master_aliases(
        db, object_id, payload.aliases, user
    )
    return success_response(
        [
            {"id": row.id, "alias": row.alias, "normalized_alias": row.normalized_alias}
            for row in rows
        ]
    )


@router.post("/master-objects/{object_id}/aliases", summary="新增QA主数据别名")
async def add_master_aliases(
    object_id: uuid.UUID,
    payload: AliasUpdateRequest,
    user: User = Depends(_master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.add_master_aliases(
        db, object_id, payload.aliases, user
    )
    return success_response([{"id": row.id, "alias": row.alias} for row in rows])


@router.put("/master-objects/{object_id}/sources", summary="替换QA主数据来源关联")
async def replace_master_sources(
    object_id: uuid.UUID,
    payload: SourceUpdateRequest,
    user: User = Depends(_master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.replace_master_sources(db, object_id, payload.sources, user)
    return success_response([MasterObjectSourceOut.model_validate(row).model_dump(mode="json") for row in rows])


@router.post("/master-objects/{object_id}/sources", summary="新增QA主数据来源关联")
async def add_master_source_links(
    object_id: uuid.UUID,
    payload: SourceUpdateRequest,
    user: User = Depends(_master_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.add_master_sources(db, object_id, payload.sources, user)
    return success_response([MasterObjectSourceOut.model_validate(row).model_dump(mode="json") for row in rows])


# ───────────────────────── 引用选择器 ─────────────────────────


@router.get("/references/departments", summary="QA责任部门引用")
async def reference_departments(
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    include_inactive: bool = False,
) -> Any:
    from app.platform.identity.public_api import list_department_briefs

    rows = await list_department_briefs(db, keyword=keyword, include_deleted=include_inactive)
    return success_response(
        [
            {
                "id": row.id,
                "feishu_department_id": row.feishu_department_id,
                "name": row.name,
                "parent_feishu_department_id": row.parent_feishu_department_id,
                "path": row.path,
                "available": row.is_active,
            }
            for row in rows
        ]
    )


@router.get("/references/sources/{kind}", summary="QA外部来源引用")
async def reference_sources(
    kind: str,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    value = kind.upper()
    rows: list[Any]
    total: int
    if value == "PRODUCT":
        from app.modules.production.public_api import list_products

        rows, total = await list_products(db, keyword, page, page_size)
        entity = "product"
    elif value in {"MATERIAL", "INTERMEDIATE_TYPE", "INTERMEDIATE-TYPE"}:
        from app.modules.production.public_api import list_intermediate_types

        rows, total = await list_intermediate_types(db, keyword, page, page_size)
        entity = "intermediate_type"
    elif value == "EQUIPMENT":
        from app.modules.equipment.public_api import list_equipment_references

        rows, total = await list_equipment_references(
            db,
            user,
            "qa",
            keyword=keyword,
            page=page,
            page_size=page_size,
        )
        entity = "equipment"
    else:
        raise AppException(status_code=422, message="不支持的外部来源类型")

    def brief_value(row: Any, *names: str) -> Any:
        """兼容 public_api 摘要对象和字典型适配器返回值。"""
        for name in names:
            value = row.get(name) if isinstance(row, dict) else getattr(row, name, None)
            if value not in (None, ""):
                return value
        return None

    data = []
    for row in rows:
        source_id = brief_value(row, "id")
        active = brief_value(row, "is_active")
        deleted = brief_value(row, "is_deleted")
        data.append(
            {
                "id": source_id,
                # production Product 的 product_code 允许为空；引用选择器仍
                # 需要稳定可显示的 code，因此回退到来源 ID。
                "code": brief_value(row, "code", "equipment_no", "product_code") or str(source_id),
                "name": brief_value(row, "name", "product_name", "equipment_name") or str(source_id),
                "source_module": "equipment" if entity == "equipment" else "production",
                "source_entity": entity,
                "source_id": source_id,
                "is_active": active if active is not None else True,
                "is_deleted": deleted if deleted is not None else False,
                # 仅用于选择器分组，不暴露设备台账详情。
                "source": brief_value(row, "source"),
                "category": brief_value(row, "category"),
                "is_product": brief_value(row, "is_product"),
            }
        )
    return paginated_response(data, page, page_size, total)


# ───────────────────────── 文件类型与台账 ─────────────────────────


@router.get("/document-types", summary="文件类型列表")
async def get_document_types(
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    include_inactive: bool = False,
) -> Any:
    rows = await list_document_types(db, include_inactive=include_inactive)
    return success_response([DocumentTypeOut.model_validate(row).model_dump(mode="json") for row in rows])


@router.post("/document-types", summary="创建文件类型")
async def post_document_type(
    payload: DocumentTypeCreate,
    user: User = Depends(_config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.create_document_type(db, payload, user)
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.put("/document-types/{type_id}", summary="更新文件类型")
async def put_document_type(
    type_id: uuid.UUID,
    payload: DocumentTypeUpdate,
    user: User = Depends(_config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document_type(db, type_id, payload, user)
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.post("/document-types/{type_id}/activate", summary="启用文件类型")
async def activate_document_type(
    type_id: uuid.UUID,
    user: User = Depends(_config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document_type(db, type_id, DocumentTypeUpdate(status="active"), user)
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.post("/document-types/{type_id}/deactivate", summary="停用文件类型")
async def deactivate_document_type(
    type_id: uuid.UUID,
    user: User = Depends(_config_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document_type(db, type_id, DocumentTypeUpdate(status="inactive"), user)
    return success_response(DocumentTypeOut.model_validate(row).model_dump(mode="json"))


@router.get("/documents", summary="质量文件台账列表")
async def get_documents(
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    document_type_id: uuid.UUID | None = None,
    responsible_department_id: str | None = None,
    include_inactive: bool = False,
    include_history: bool = False,
    has_current_version: bool | None = None,
    sort_by: str = Query("document_no", description="排序字段：document_no 编号 / title 标题"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> Any:
    documents, total = await service.list_document_page(
        db,
        keyword=keyword,
        document_type_id=document_type_id,
        responsible_department_id=responsible_department_id,
        include_inactive=include_inactive,
        has_current_version=has_current_version,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )
    result = []
    for document in documents:
        item = await service.document_list_item(db, document)
        if include_history:
            item["versions"] = [
                await service.version_to_dict(db, version)
                for version in await get_versions(db, document.id)
            ]
        item["is_active"] = item["status"] == "active"
        result.append(item)
    return paginated_response(result, page, page_size, total)


@router.post("/documents", summary="创建质量文件台账")
async def post_document(
    payload: DocumentCreate,
    user: User = Depends(_document_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.create_document(db, payload, user)
    return success_response(await service.document_to_dict(db, row, include_versions=False))


@router.get("/documents/{document_id}", summary="质量文件详情")
async def get_document_detail(
    document_id: uuid.UUID,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    return success_response(await service.document_to_dict(db, row))


@router.put("/documents/{document_id}", summary="更新质量文件台账")
async def put_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    user: User = Depends(_document_update),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.update_document(db, document_id, payload, user)
    return success_response(await service.document_to_dict(db, row, include_versions=False))


@router.post("/documents/{document_id}/activate", summary="启用质量文件")
async def activate_document(
    document_id: uuid.UUID,
    user: User = Depends(_document_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.set_document_status(db, document_id, "active", user)
    return success_response(await service.document_to_dict(db, row, include_versions=False))


@router.post("/documents/{document_id}/deactivate", summary="停用质量文件")
async def deactivate_document(
    document_id: uuid.UUID,
    user: User = Depends(_document_deactivate),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.set_document_status(db, document_id, "inactive", user)
    return success_response(await service.document_to_dict(db, row, include_versions=False))


# ───────────────────────── 版本与关联 ─────────────────────────


@router.post("/documents/{document_id}/versions", summary="上传并登记质量文件版本")
async def post_document_version(
    document_id: uuid.UUID,
    version_label: str = Form(..., min_length=1, max_length=64),
    approved_declared: bool = Form(False),
    file: UploadFile = File(...),
    user: User = Depends(_version_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    data = await file.read(file_service.MAX_FILE_SIZE + 1)
    try:
        row = await service.create_version(
            db,
            document_id,
            version_label=version_label,
            approved_declared=approved_declared,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
            user=user,
        )
    except file_service.FileValidationError as exc:
        raise AppException(status_code=422, message=str(exc)) from exc
    return success_response(await service.version_to_dict(db, row))


@router.get("/documents/{document_id}/versions", summary="质量文件版本列表")
async def get_document_versions(
    document_id: uuid.UUID,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    versions = await get_versions(db, document_id)
    return success_response([await service.version_to_dict(db, v) for v in versions])


@router.put("/document-versions/{version_id}/relations", summary="维护文件版本关联")
async def put_version_relations(
    version_id: uuid.UUID,
    payload: RelationCompatRequest,
    user: User = Depends(_relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.set_relations(db, version_id, payload.to_relations(), user)
    return success_response([await service._relation_dict(db, row) for row in rows])


@router.post("/document-versions/{version_id}/ai-analysis", response_model=ApiResponse, summary="异步触发文档 AI 分析")
async def post_ai_analysis(
    version_id: uuid.UUID,
    payload: AIAnalysisTriggerRequest | None = None,
    user: User = Depends(_relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    run = await ai_analysis.create_analysis_run(
        db, version_id, user, force=bool(payload and payload.force)
    )
    return success_response({"run_id": run.id, "status": run.status})


@router.get("/document-versions/{version_id}/ai-analysis/latest", response_model=ApiResponse, summary="获取版本最近一次 AI 分析")
async def get_latest_ai_analysis(
    version_id: uuid.UUID,
    user: User = Depends(_relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    run = await get_latest_ai_run(db, version_id)
    if run is None:
        raise NotFoundException("AI 分析运行", str(version_id))
    data = await ai_analysis.analysis_to_dict(db, run, user=user)
    return success_response(AIAnalysisRunOut.model_validate(data).model_dump(mode="json"))


@router.get("/ai-analysis/{run_id}", response_model=ApiResponse, summary="获取指定 AI 分析运行及证据")
async def get_ai_analysis(
    run_id: uuid.UUID,
    user: User = Depends(_relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    run = await get_ai_run(db, run_id)
    if run is None:
        raise NotFoundException("AI 分析运行", str(run_id))
    data = await ai_analysis.analysis_to_dict(db, run, user=user)
    return success_response(AIAnalysisRunOut.model_validate(data).model_dump(mode="json"))


@router.post("/ai-analysis/{run_id}/confirm-relations", response_model=ApiResponse, summary="确认 AI 候选文件关联")
async def post_confirm_ai_relations(
    run_id: uuid.UUID,
    payload: AIRelationConfirmationRequest,
    user: User = Depends(_relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await ai_analysis.confirm_relations(
        db,
        run_id,
        accepted_suggestion_ids=payload.accepted_suggestion_ids,
        manual_master_object_ids=payload.manual_master_object_ids,
        remove_master_object_ids=payload.remove_master_object_ids,
        user=user,
    )
    return success_response([await service._relation_dict(db, row) for row in rows])


@router.get("/master-object-proposals", response_model=ApiResponse, summary="QA 主数据 AI 提案箱")
async def get_master_object_proposals(
    user: User = Depends(_proposal_publish),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    items, total = await ai_analysis.list_proposal_page(db, status=status, page=page, page_size=page_size)
    return paginated_response(items, page, page_size, total)


@router.post("/master-object-proposals/{proposal_id}/approve", response_model=ApiResponse, summary="审批 QA 主数据 AI 提案")
async def approve_master_object_proposal(
    proposal_id: uuid.UUID,
    payload: MasterObjectProposalApproveRequest | None = None,
    user: User = Depends(_proposal_publish),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row, auto_link_skipped = await ai_analysis.approve_proposal(db, proposal_id, payload.payload if payload else None, user)
    body = MasterObjectProposalOut.model_validate(row).model_dump(mode="json")
    body["auto_linked"] = auto_link_skipped is None
    body["auto_link_skipped_reason"] = auto_link_skipped
    return success_response(body)


@router.post("/master-object-proposals/{proposal_id}/reject", response_model=ApiResponse, summary="拒绝 QA 主数据 AI 提案")
async def reject_master_object_proposal(
    proposal_id: uuid.UUID,
    user: User = Depends(_proposal_publish),
    db: AsyncSession = Depends(get_db),
) -> Any:
    # 拒绝即软删除，不回传提案内容：调用方只需知道已处理。
    await ai_analysis.reject_proposal(db, proposal_id, user)
    return success_response({"id": str(proposal_id), "status": "rejected"})


@router.post("/documents/{document_id}/versions/{version_id}/copy-relations", summary="显式复制上一当前版本关联")
async def post_copy_relations(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(_relation_manage),
    db: AsyncSession = Depends(get_db),
) -> Any:
    rows = await service.copy_current_relations(db, document_id, version_id, user)
    return success_response([await service._relation_dict(db, row) for row in rows])


@router.post("/documents/{document_id}/versions/{version_id}/make-current", summary="将版本设为当前")
async def post_make_current(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    user: User = Depends(_version_current),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await service.make_current(db, document_id, version_id, user)
    row = await get_document(db, document_id)
    if row is None:
        raise NotFoundException("质量文件", str(document_id))
    return success_response(await service.document_to_dict(db, row))


@router.post("/document-versions/{version_id}/activate", summary="启用质量文件版本")
async def activate_version(
    version_id: uuid.UUID,
    user: User = Depends(_version_disable),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.activate_version(db, version_id, user)
    return success_response(await service.version_to_dict(db, row))


@router.post("/document-versions/{version_id}/deactivate", summary="停用质量文件版本")
async def deactivate_version(
    version_id: uuid.UUID,
    user: User = Depends(_version_disable),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.disable_version(db, version_id, user)
    return success_response(await service.version_to_dict(db, row))


@router.post("/document-files/{file_id}/retry", summary="重试正文提取")
async def retry_file_extraction(
    file_id: uuid.UUID,
    user: User = Depends(_version_create),
    db: AsyncSession = Depends(get_db),
) -> Any:
    row = await service.retry_extraction(db, file_id, user)
    return success_response({"id": row.id, "extraction_status": row.extraction_status})


@router.get(
    "/document-files/{file_id}/processing-results",
    response_model=ApiResponse,
    summary="查看文件解析与分块结果",
)
async def get_file_processing_results(
    file_id: uuid.UUID,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    view: ProcessingResultView = Query("raw_blocks"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    content_limit: int = Query(
        800,
        ge=100,
        le=2000,
        description="每个正文预览最多返回的字符数；完整正文仍保留在受保护的内部存储中",
    ),
) -> Any:
    data = await service.document_processing_results(
        db,
        file_id,
        view=view,
        page=page,
        page_size=page_size,
        content_limit=content_limit,
    )
    # 本端点能按页把整篇正文取走（content_limit 上限 2000），与 /content
    # 预览/下载是同一份受保护内容；不写审计等于把下载审计整条绕过去。
    from app.modules.qa.service import _audit

    await _audit(
        db,
        action="view_processing_results",
        user=user,
        resource_type="document_file",
        resource_id=file_id,
        extra={"view": view, "page": page, "page_size": page_size},
    )
    return success_response(
        DocumentProcessingResultOut.model_validate(data).model_dump(mode="json")
    )


@router.get("/document-files/{file_id}/content", summary="预览或下载质量文件")
async def get_file_content(
    file_id: uuid.UUID,
    user: RequireUser,
    db: AsyncSession = Depends(get_db),
    download: bool = False,
) -> StreamingResponse:
    row = await get_file(db, file_id)
    if row is None:
        raise NotFoundException("文件", str(file_id))
    # MinIO 客户端与本地 read_bytes 都是阻塞调用，单文件最大 50MB：放进线程池，
    # 否则会占住事件循环，阻塞同 worker 的其它请求。
    content = await asyncio.to_thread(file_service.read_file, row.storage_key)
    if content is None:
        raise NotFoundException("文件内容", str(file_id))
    data, stored_mime = content
    mime = row.mime_type or stored_mime
    from app.modules.qa.service import _audit

    await _audit(
        db,
        action="download" if download else "preview",
        user=user,
        resource_type="document_file",
        resource_id=row.id,
        extra={"sha256": row.sha256, "size_bytes": row.size_bytes},
    )
    disposition = (
        "attachment"
        if download or row.extension.lower().lstrip(".") != "pdf"
        else "inline"
    )
    headers = {
        "Content-Disposition": file_service.content_disposition(
            disposition, row.original_filename
        ),
        "X-Content-SHA256": row.sha256,
    }
    return StreamingResponse(iter([data]), media_type=mime, headers=headers)


# ───────────────────────── 搜索与审计 ─────────────────────────


@router.get("/search", summary="QA全局检索")
async def search_qa(
    user: RequireUser,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    include_history: bool = False,
    include_inactive: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=200),
) -> Any:
    items, total = await service.search(
        db,
        q,
        include_history=include_history,
        include_inactive=include_inactive,
        page=page,
        page_size=page_size,
    )
    return paginated_response(items, page, page_size, total)


@router.get("/audit-logs", summary="QA审计日志")
async def get_qa_audit_logs(
    user: User = Depends(_audit_read),
    db: AsyncSession = Depends(get_db),
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = Query(default=None, alias="user_id"),
    start_at: datetime | None = Query(default=None, alias="from"),
    end_at: datetime | None = Query(default=None, alias="to"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Any:
    logs, total = await service.list_audit_logs(
        db,
        page=page,
        page_size=page_size,
        user_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        start_at=start_at,
        end_at=end_at,
    )
    from app.platform.identity.public_api import get_user_names

    # 审计表只存 user_id；列表要给人看，批量换成姓名（查不到的前端回退显示 ID）
    names = await get_user_names(db, [log.user_id for log in logs])
    data = [
        {
            "id": log.id,
            "user_id": log.user_id,
            "actor_id": log.user_id,
            "actor_name": names.get(log.user_id),
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "object_type": log.resource_type,
            "object_id": log.resource_id,
            "old_value": log.old_value,
            "new_value": log.new_value,
            "before_value": log.old_value,
            "after_value": log.new_value,
            "extra": log.extra,
            "metadata": log.extra,
            "created_at": log.created_at,
            "file_sha256": (log.extra or {}).get("sha256") if log.extra else None,
        }
        for log in logs
    ]
    return paginated_response(data, page, page_size, total)
