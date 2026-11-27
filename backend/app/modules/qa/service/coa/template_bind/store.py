"""COA 模板文件与人工确认标注的存取。

上传/替换模板（换文件后原标注作废）、查看模板与标注、保存人工确认后的标注、
列表上的标注偏差查询。标注保存前服务端对着模板重新校验一遍，不信任前端算的结果。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa import file_service
from app.modules.qa.models import (
    CoaProductField,
    CoaStandard,
    CoaStandardField,
    CoaStandardItem,
)
from app.modules.qa.repository import coa as repo
from app.modules.qa.schemas.coa import CoaTemplateBindingIn
from app.modules.qa.service.coa.common import (
    _actor_id,
    effective_fields,
    get_standard_or_404,
    template_status_of,
)
from app.modules.qa.service.coa.template_address import TemplateDoc, TemplateDocError
from app.modules.qa.service.coa.template_bind.fields import (
    build_fields,
    field_defs,
    field_dict,
)
from app.modules.qa.service.coa.template_bind.formats import (
    DEFAULTS,
    binding_drift,
    field_config,
    normalize_fmt,
)
from app.modules.qa.service.coa.template_bind.review import (
    derive_slot,
    describe_binding,
    result_residue,
)
from app.platform.identity.models import User

# 2：标注里记下确认时的字段清单和各字段的配置（field_set / config），用来发现之后的配置变化
BINDING_VERSION = 2
# 确认保存时记下产生提案的提示词版本（AI 提示词演进时便于追溯）
BIND_PROMPT_VERSION = "coa-template-bind-v1"


def template_status(standard: CoaStandard, drift: Mapping[str, Any] | None = None) -> str:
    """none=没上传模板；unbound=已上传未确认标注；bound=标注已确认；stale=需重新核对。"""
    return template_status_of(standard, drift)


def template_summary(
    standard: CoaStandard, drift: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    binding = standard.template_binding or {}
    return {
        "status": template_status(standard, drift),
        "filename": standard.template_filename,
        "sha256": standard.template_sha256,
        "bound_at": binding.get("confirmed_at"),
        "prompt_version": binding.get("prompt_version"),
    }


async def load_template_data(standard: CoaStandard) -> bytes:
    if not standard.template_key:
        raise AppException(status_code=400, message="该标准尚未上传 COA 模板")
    content = await asyncio.to_thread(file_service.read_file, standard.template_key)
    if content is None:
        raise AppException(status_code=409, message="模板文件已不存在，请重新上传")
    return content[0]


def parse_template(data: bytes) -> TemplateDoc:
    """docx 字节 → 带地址视图；解析不了（加密/损坏）转 400。

    调用方请用 ``asyncio.to_thread``（单进程部署下解析大文件会卡住全站请求）。
    """
    try:
        return TemplateDoc(data)
    except TemplateDocError as exc:
        raise AppException(status_code=400, message=str(exc)) from exc


def _validate_template_file(
    filename: str | None, content_type: str | None, data: bytes
) -> None:
    extension = f".{filename.rsplit('.', 1)[-1].lower()}" if filename and "." in filename else ""
    if extension != ".docx":
        raise AppException(
            status_code=400,
            message="COA 模板必须是 .docx 文件（.doc 请先用 Word 另存为 .docx）",
        )
    try:
        file_service.validate_file(filename, content_type, data)
    except file_service.FileValidationError as exc:
        raise AppException(status_code=400, message=str(exc)) from exc


async def upload_template(
    db: AsyncSession,
    standard_id: uuid.UUID,
    data: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    user: User | None,
) -> dict[str, Any]:
    """上传/替换模板；换了文件，原标注一律作废（标注是针对具体文件的）。"""
    standard = await get_standard_or_404(db, standard_id)
    _validate_template_file(filename, content_type, data)
    await asyncio.to_thread(parse_template, data)
    stored = await asyncio.to_thread(file_service.store_file, filename, content_type, data)
    old_key = standard.template_key
    standard.template_key = stored.key
    standard.template_filename = stored.original_filename
    standard.template_sha256 = stored.sha256
    standard.template_binding = None
    standard.updated_by = _actor_id(user)
    await db.flush()
    if old_key and old_key != stored.key:
        await asyncio.to_thread(file_service.cleanup_stored_file, old_key)
    return await get_template(db, standard_id)


async def get_template(db: AsyncSession, standard_id: uuid.UUID) -> dict[str, Any]:
    """模板状态 + 网格 + 字段清单 + 已确认的标注（没有就是 None）。

    drift：标注确认之后字段配置的变化（没有为 None）。抽屉据此列出要重新
    核对的条目，并让用户不改别的也能直接重新确认保存。
    """
    standard = await get_standard_or_404(db, standard_id)
    info: dict[str, Any] = {"template": template_summary(standard)}
    if not standard.template_key:
        return info
    doc = await asyncio.to_thread(parse_template, await load_template_data(standard))
    fields = await build_fields(db, standard)
    binding = standard.template_binding
    drift = binding_drift(fields, binding) if binding else None
    info["template"] = template_summary(standard, drift)
    info["grid"] = doc.grid()
    # 项目表的结果列（表地址 → 网格列）：前端据此判断哪些格子绑定/解绑后要进「待处理」
    info["result_columns"] = doc.result_columns()
    info["fields"] = [field_dict(f) for f in fields]
    info["drift"] = drift
    info["binding"] = describe_binding(doc, fields, binding, drift) if binding else None
    return info


async def drift_by_standard(
    db: AsyncSession, standards: Sequence[CoaStandard]
) -> dict[uuid.UUID, dict[str, Any] | None]:
    """一批标准的标注偏差（列表上的模板状态用）：固定三次查询，不逐份去取。

    只算已确认标注的标准，其余不在结果里（调用方按没有偏差处理）。
    """
    bound = [s for s in standards if s.template_binding]
    if not bound:
        return {}
    items_by_std: dict[uuid.UUID, list[CoaStandardItem]] = {}
    for item in await repo.list_items_of_standards(db, [s.id for s in bound]):
        items_by_std.setdefault(item.standard_id, []).append(item)
    custom = [s for s in bound if s.batch_fields_overridden]
    inherited = [s for s in bound if not s.batch_fields_overridden]
    overrides: dict[uuid.UUID, list[CoaStandardField]] = {}
    for standard_field_row in await repo.list_standard_fields_of(db, [s.id for s in custom]):
        overrides.setdefault(standard_field_row.standard_id, []).append(standard_field_row)
    defaults: dict[uuid.UUID, list[CoaProductField]] = {}
    for product_field_row in await repo.list_product_fields_of(
        db, list({s.product_id for s in inherited})
    ):
        defaults.setdefault(product_field_row.product_id, []).append(product_field_row)
    drifts: dict[uuid.UUID, dict[str, Any] | None] = {}
    for standard in bound:
        effective, _custom = effective_fields(
            standard,
            overrides.get(standard.id, []),
            defaults.get(standard.product_id, []),
        )
        fields = field_defs(effective, items_by_std.get(standard.id, []))
        drifts[standard.id] = binding_drift(fields, standard.template_binding or {})
    return drifts


async def save_template_binding(
    db: AsyncSession,
    standard_id: uuid.UUID,
    payload: CoaTemplateBindingIn,
    user: User | None,
) -> dict[str, Any]:
    """保存人工确认后的标注：服务端对着模板重新校验一遍，不信任前端算的结果。"""
    standard = await get_standard_or_404(db, standard_id)
    doc = await asyncio.to_thread(parse_template, await load_template_data(standard))
    fields = await build_fields(db, standard)
    by_key = {f.key: f for f in fields}
    used: dict[str, str] = {}
    saved: list[dict[str, Any]] = []
    for entry in payload.fields:
        field = by_key.get(entry.field)
        if field is None:
            raise AppException(
                status_code=400, message=f"字段 {entry.field} 不在当前标准的字段清单中"
            )
        slots: list[dict[str, Any]] = []
        cells_here: list[str | None] = []
        for slot_in in entry.slots:
            slot = doc.resolve(slot_in.sid)
            if slot is None:
                raise AppException(
                    status_code=400, message=f"数据位 {slot_in.sid} 在模板中不存在"
                )
            if slot.sid in used:
                raise AppException(
                    status_code=400,
                    message=f"数据位 {slot.sid} 不能同时绑定 {used[slot.sid]} 和 {entry.field}",
                )
            try:
                mode, sample = derive_slot(slot, slot_in.sample)
            except ValueError as exc:
                raise AppException(status_code=400, message=str(exc)) from exc
            used[slot.sid] = entry.field
            try:
                fmt = normalize_fmt(slot_in.fmt.model_dump())
            except ValueError as exc:
                raise AppException(status_code=400, message=str(exc)) from exc
            slots.append({"sid": slot.sid, "mode": mode, "sample": sample, "fmt": fmt})
            cells_here.append(slot.cell)
        if not slots:
            raise AppException(status_code=400, message=f"字段 {entry.field} 没有绑定任何位置")
        if len(set(cells_here)) < len(cells_here):
            raise AppException(
                status_code=400,
                message=f"字段 {entry.field} 在同一格里绑定了多个段落；中英分两段的格子请只绑定中文段",
            )
        saved.append(
            {
                "field": entry.field,
                # 字段之后被移除时，提示里还叫得出它的名字
                "label_cn": field.label_cn,
                "required": entry.required,
                # 确认时的类型/单位：之后变了，这里的格式规则要重新过目
                "config": field_config(field),
                "slots": slots,
            }
        )
    static: list[str] = []
    for sid in payload.static_slots:
        slot = doc.resolve(sid)
        if slot is None:
            raise AppException(status_code=400, message=f"数据位 {sid} 在模板中不存在")
        if slot.sid in used:
            raise AppException(
                status_code=400, message=f"数据位 {slot.sid} 已绑定字段，不能再标记为固定文字"
            )
        if slot.sid not in static:
            static.append(slot.sid)
    unhandled = [r for r in result_residue(doc, set(used)) if r["sid"] not in static]
    if unhandled:
        raise AppException(
            status_code=400,
            message="结果列还有未处理的非空格子（可能残留模板旧值）：请绑定到字段，或标记为固定文字",
            detail=unhandled,
        )
    actor = _actor_id(user)
    standard.template_binding = {
        "version": BINDING_VERSION,
        "prompt_version": BIND_PROMPT_VERSION,
        "template_sha256": standard.template_sha256,
        "confirmed_by": str(actor) if actor else None,
        "confirmed_at": datetime.now().isoformat(timespec="seconds"),
        "defaults": dict(DEFAULTS),
        "verdicts": dict(payload.verdicts),
        # 确认那一刻的字段清单：之后新增的字段还没经过人工过目，要重新核对
        "field_set": sorted(by_key),
        "fields": saved,
        "static_slots": static,
    }
    standard.updated_by = actor
    await db.flush()
    return await get_template(db, standard_id)
