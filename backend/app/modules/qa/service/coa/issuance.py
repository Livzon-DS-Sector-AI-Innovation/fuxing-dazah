"""COA 出具登记：报告 CRUD、docx 导入匹配预览、产品维度矩阵透视。

守卫口径：
- 无报告编号（业务键=产品+模板+批号）：(产品, 标准, 批号) 唯一——同批同
  标准只登记一份，补发=软删重登；docx 里印的编号仅作导入解析匹配锚点。
- 值的 item 必须归属报告标准；导入确认可带 new_items 并入标准（携带首份
  值，后端按新建 item id 归并，前端无需预知 UUID）。
- batch_data 键必须命中标准生效字段集自定义键；固定列别名键镜像写报告
  固定列，其余进 JSONB；读取按字段集合成 batch_info 视图。
- 矩阵：列=产品各标准项目（两级列头），行=报告，格=值映射。
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.qa.models import CoaReport, CoaSourceType, CoaStandardItem
from app.modules.qa.repository import coa as repo
from app.modules.qa.schemas.coa import CoaReportCreate, CoaReportUpdate, CoaValueIn
from app.modules.qa.service.coa.ai_parse import (
    COA_AI_PROMPT_VERSION_VALUES,
    parse_docx_ai,
)
from app.modules.qa.service.coa.common import (
    _actor_id,
    _normalize_field_token,
    builtin_key_of,
    compose_batch_info,
    get_product_or_404,
    get_report_or_404,
    get_standard_or_404,
    item_dict,
    product_dict,
    report_column_key_of,
    report_dict,
    standard_dict,
    value_dict,
)
from app.modules.qa.service.coa.docx_parse import parse_date_text
from app.modules.qa.service.coa.standards import _insert_items, resolve_standard_fields


def _parse_to_raw(parse: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "source": "ai",
        "prompt_version": COA_AI_PROMPT_VERSION_VALUES,
        "batch_info": parse.batch_info,
        "serial_no": parse.serial_no,
        "report_no": parse.report_no,
        "conclusion": parse.conclusion,
        "items": [
            {
                "name": it.name,
                "name_en": it.name_en,
                "unit": it.unit,
                "spec_text": it.spec_text,
                "spec_text_en": it.spec_en,
                "result": it.result,
                "result_en": it.result_en,
            }
            for it in parse.items
        ],
    }
    if parse.batch_fields:
        raw["batch_info_fields"] = [
            {"label_cn": f.label_cn, "label_en": f.label_en, "value": f.value}
            for f in parse.batch_fields
        ]
    return raw


def _legacy_standard_code(report_no: str | None) -> str | None:
    """旧建议口径的模板码：编号倒数第二个纯数字段（COA-HAF-3205-006 → 3205）。

    改造前导入的标准按此码落库；自动匹配先按新口径（整段），查不到再用它
    兜底，避免存量标准全部退化成手动选择。
    """
    if not report_no:
        return None
    digits = [s for s in re.split(r"[-_/]", report_no) if s.isdigit()]
    if len(digits) >= 2:
        return digits[-2]
    return digits[-1] if digits else None


def _dynamic_batch_fields(
    parsed_fields: list[Any], fields: list[dict[str, Any]]
) -> list[dict[str, str]]:
    """值版提取的批次字段标签 → 生效字段集键（内置 3 键跳过）。

    标签/英文标签/键归一后与生效自定义字段比对；命中且值非空才返回。
    固定列别名键也返回——create_report 的 _split_batch_data 会镜像写列。
    """
    by_token: dict[str, dict[str, Any]] = {}
    for f in fields:
        if f.get("builtin"):
            continue
        for token in (
            _normalize_field_token(f["key"]),
            _normalize_field_token(f["label_cn"]),
            _normalize_field_token(f["label_en"]) if f["label_en"] else "",
        ):
            if token:
                by_token.setdefault(token, f)
    matched: list[dict[str, str]] = []
    seen: set[str] = set()
    for pf in parsed_fields:
        value = (pf.value or "").strip()
        if not value:
            continue
        for candidate in (pf.key, pf.label_cn, pf.label_en):
            token = _normalize_field_token(candidate) if candidate else ""
            field = by_token.get(token) if token else None
            if field is None:
                continue
            if field["key"] not in seen:
                seen.add(field["key"])
                matched.append(
                    {"key": field["key"], "label_cn": field["label_cn"], "value": value}
                )
            break
    return matched


def _report_draft(parse: Any) -> dict[str, Any]:
    """解析结果 → 报告头草稿（日期已解析为 ISO；出具日期人工填）。"""
    return {
        "serial_no": parse.serial_no,
        "batch_no": parse.batch_info.get("batch_no"),
        "mfg_date": parse.mfg_date.isoformat() if parse.mfg_date else None,
        "exp_date": parse.exp_date.isoformat() if parse.exp_date else None,
        "issued_date": None,
        "packaging": parse.batch_info.get("packaging"),
        "batch_size": parse.batch_info.get("batch_size"),
        "storage": parse.batch_info.get("storage"),
        "conclusion": parse.conclusion,
    }


# ─────────────────────── 导入匹配预览 ───────────────────────


async def import_report_preview(
    db: AsyncSession,
    data: bytes,
    *,
    standard_id: uuid.UUID | None = None,
    filename: str = "coa.docx",
) -> dict[str, Any]:
    """docx → 标准匹配 + 项目对齐 + 值预填（不落库）。

    docx 里印的报告编号只用于推导产品短码/模板码做自动匹配（识别不到就
    返回候选清单让用户手选），不作为报告字段落库。
    """
    parse = await parse_docx_ai(data, filename)

    # 产品与标准解析：显式指定 → 直接用；否则按 产品短码+模板码 自动匹配
    product = None
    if parse.suggested_product_code:
        product = await repo.find_product_by_code(db, parse.suggested_product_code)
    standard = None
    if standard_id is not None:
        standard = await get_standard_or_404(db, standard_id)
        product = await repo.get_product(db, standard.product_id)
    elif product is not None and parse.suggested_standard_code:
        standard = await repo.find_standard_by_code(
            db, product.id, parse.suggested_standard_code
        )
        # 存量标准按旧口径建码（3205），新建议是整段（HAF-3205-006）→ 再试一次
        if standard is None:
            legacy_code = _legacy_standard_code(parse.report_no)
            if legacy_code and legacy_code != parse.suggested_standard_code:
                standard = await repo.find_standard_by_code(
                    db, product.id, legacy_code
                )

    candidates: list[dict[str, Any]] = []
    if standard is None:
        scope = product.id if product is not None else None
        candidates = [
            standard_dict(r) for r in await repo.list_standards(db, product_id=scope)
        ]

    result: dict[str, Any] = {
        "product": product_dict(product) if product else None,
        "product_draft": {
            "code": parse.suggested_product_code,
            "name": parse.product_cn,
            "name_en": parse.product_en,
        },
        "standard": standard_dict(standard) if standard else None,
        "standard_candidates": candidates,
        "report_draft": _report_draft(parse),
        "matched_items": [],
        "unmatched_items": [],  # docx 有、标准无 → 可勾选并入标准（带值）
        "missing_items": [],  # 标准有、docx 无（提示留空/补录）
        # 模板动态批次字段值（key=生效字段集键，label 供预览展示）→ 确认时传 batch_data
        "batch_dynamic": [],
        "raw_extract": _parse_to_raw(parse),
    }

    if standard is not None and parse.batch_fields:
        fields, _custom = await resolve_standard_fields(db, standard.id)
        result["batch_dynamic"] = _dynamic_batch_fields(parse.batch_fields, fields)

    if standard is not None:
        items = await repo.list_items(db, standard.id)
        by_code = {i.code: i for i in items}
        for it in parse.items:
            hit = by_code.get(it.code)
            if hit is None:
                result["unmatched_items"].append(
                    {
                        "name_cn": it.name,
                        "name_en": it.name_en,
                        "unit": it.unit,
                        "value_type": it.value_type,
                        "spec_text": it.spec_text,
                        "spec_min": it.spec_min,
                        "spec_max": it.spec_max,
                        "value_num": it.value_num,
                        "value_text": it.result,
                    }
                )
            else:
                result["matched_items"].append(
                    {
                        "item_id": str(hit.id),
                        "name": hit.name_cn,
                        "spec_text": hit.spec_text,
                        "value_num": it.value_num,
                        "value_text": it.result,
                    }
                )
        hit_codes = {it.code for it in parse.items}
        result["missing_items"] = [
            item_dict(i) for i in items if i.code not in hit_codes
        ]
    return result


# ─────────────────────── 报告 CRUD ───────────────────────


async def _validate_report_unique(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    standard_id: uuid.UUID,
    batch_no: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if await repo.find_report_by_batch(
        db, product_id, standard_id, batch_no, exclude_id=exclude_id
    ):
        raise AppException(
            status_code=409,
            message=f"批号 {batch_no} 在该标准下已登记（补发请先作废原记录）",
        )


async def _validate_values(
    db: AsyncSession,
    standard_id: uuid.UUID,
    values: list[CoaValueIn],
) -> list[dict[str, Any]]:
    """values 只允许引用既有项目；新项目的值走 new_items 归并。"""
    if not values:
        return []
    items = await repo.list_items(db, standard_id)
    valid_ids = {i.id for i in items}
    rows: list[dict[str, Any]] = []
    seen: set[uuid.UUID] = set()
    for v in values:
        item_uuid = uuid.UUID(v.item_id)
        if item_uuid not in valid_ids:
            raise NotFoundException("结果值项目", v.item_id)
        if item_uuid in seen:
            raise AppException(status_code=400, message="结果值项目重复")
        seen.add(item_uuid)
        if v.value_num is None and not (v.value_text or "").strip():
            raise AppException(status_code=400, message="结果值不能为空（数值或文字）")
        rows.append(
            {
                "item_id": item_uuid,
                "value_num": v.value_num,
                "value_text": v.value_text,
                "remark": v.remark,
            }
        )
    return rows


# ─────────────────────── 批次字段解析 ───────────────────────


def _require_date(key: str, value: str) -> Any:
    """date 型批次字段值：确定性解析，解析不动 → 400。"""
    parsed = parse_date_text(value)
    if parsed is None:
        raise AppException(
            status_code=400, message=f"批次字段 {key} 的值「{value}」不是有效日期"
        )
    return parsed


def _split_batch_data(
    fields: list[dict[str, Any]],
    batch_data: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """批次字段值 → (固定列镜像更新, batch_data JSONB 值)。

    键必须命中生效字段集自定义键；内置键 400（走报告头字段）；date 型
    字段值经确定性日期解析（固定日期列存 date，非列 date 字段存 ISO 文本）。
    """
    field_by_key = {f["key"]: f for f in fields if not f.get("builtin")}
    col_updates: dict[str, Any] = {}
    jsonb: dict[str, str] = {}
    for key, value in batch_data.items():
        builtin_key = builtin_key_of(key)
        if builtin_key is not None:
            raise AppException(
                status_code=400,
                message=f"批次字段 {key} 是内置字段（{builtin_key}），请走报告头字段",
            )
        field = field_by_key.get(key)
        if field is None:
            raise AppException(
                status_code=400, message=f"批次字段 {key} 不在模板字段集中"
            )
        column = report_column_key_of(key)
        if column == "mfg_date":
            col_updates["mfg_date"] = _require_date(key, value)
        elif column == "exp_date":
            col_updates["exp_date"] = _require_date(key, value)
        elif field["field_type"] == "date":
            jsonb[key] = _require_date(key, value).isoformat()
        elif column is not None:
            col_updates[column] = value
        else:
            jsonb[key] = value
    return col_updates, jsonb


def _zero_missing_column_targets(
    col_updates: dict[str, Any],
    fields: list[dict[str, Any]],
    provided_keys: set[str],
) -> None:
    """全量替换语义：生效集中未被载荷覆盖的固定列别名目标置 None（清零）。"""
    for f in fields:
        if f.get("builtin") or f["key"] in provided_keys:
            continue
        column = report_column_key_of(f["key"])
        if column is not None and column not in col_updates:
            col_updates[column] = None


async def get_report_detail(db: AsyncSession, report_id: uuid.UUID) -> dict[str, Any]:
    row = await get_report_or_404(db, report_id)
    values = await repo.list_values_by_report(db, row.id)
    fields, _custom = await resolve_standard_fields(db, row.standard_id)
    product = await repo.get_product(db, row.product_id)
    return report_dict(
        row,
        values=[value_dict(v) for v in values],
        batch_info=compose_batch_info(
            row, fields, product_name=product.name if product else None
        ),
    )


async def list_reports(db: AsyncSession, product_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await repo.list_reports(db, product_id)
    return [report_dict(r) for r in rows]


async def create_report(
    db: AsyncSession, payload: CoaReportCreate, user: Any
) -> dict[str, Any]:
    product = await get_product_or_404(db, uuid.UUID(payload.product_id))
    standard = await get_standard_or_404(db, uuid.UUID(payload.standard_id))
    if standard.product_id != product.id:
        raise AppException(status_code=400, message="标准不属于该产品")
    await _validate_report_unique(
        db,
        product_id=product.id,
        standard_id=standard.id,
        batch_no=payload.batch_no.strip(),
    )
    # 批次字段先解析（键/日期校验失败即 400，不进事务）
    col_updates: dict[str, Any] = {}
    jsonb: dict[str, str] = {}
    if payload.batch_data:
        fields, _custom = await resolve_standard_fields(db, standard.id)
        col_updates, jsonb = _split_batch_data(fields, payload.batch_data)
    try:
        async with db.begin_nested():
            rows = await _validate_values(db, standard.id, payload.values)
            # 导入确认的未命中项先并入标准（人工勾选过 = 人工确认），
            # 其首份值按新建 item id 归并
            if payload.new_items:
                created = await _insert_items(db, standard.id, payload.new_items)
                for src, row in zip(payload.new_items, created, strict=True):
                    if src.value_num is not None or (src.value_text or "").strip():
                        rows.append(
                            {
                                "item_id": row.id,
                                "value_num": src.value_num,
                                "value_text": src.value_text,
                                "remark": None,
                            }
                        )
            report = CoaReport(
                product_id=product.id,
                standard_id=standard.id,
                serial_no=payload.serial_no,
                batch_no=payload.batch_no.strip(),
                mfg_date=payload.mfg_date,
                exp_date=payload.exp_date,
                issued_date=payload.issued_date,
                packaging=payload.packaging,
                batch_size=payload.batch_size,
                storage=payload.storage,
                conclusion=payload.conclusion,
                source=CoaSourceType.IMPORT.value
                if payload.raw_extract
                else CoaSourceType.MANUAL.value,
                raw_extract=payload.raw_extract,
                batch_data=jsonb or None,
                remark=payload.remark,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
            for key, value in col_updates.items():
                setattr(report, key, value)
            db.add(report)
            await db.flush()
            await repo.replace_report_values(db, report.id, rows)
    except IntegrityError as exc:
        raise AppException(status_code=409, message="批号冲突，请刷新后重试") from exc
    return await get_report_detail(db, report.id)


async def update_report(
    db: AsyncSession,
    report_id: uuid.UUID,
    payload: CoaReportUpdate,
    user: Any,
) -> dict[str, Any]:
    report = await get_report_or_404(db, report_id)
    updates = payload.model_dump(exclude_unset=True)
    new_values = updates.pop("values", None)
    new_batch_data = updates.pop("batch_data", None)
    head_fields = {
        "serial_no",
        "batch_no",
        "mfg_date",
        "exp_date",
        "issued_date",
        "packaging",
        "batch_size",
        "storage",
        "conclusion",
        "remark",
    }
    touched = {k: v for k, v in updates.items() if k in head_fields}
    for key, value in touched.items():
        if key == "batch_no":
            value = (value or "").strip()
        setattr(report, key, value)
    if "batch_no" in touched:
        await _validate_report_unique(
            db,
            product_id=report.product_id,
            standard_id=report.standard_id,
            batch_no=report.batch_no,
            exclude_id=report.id,
        )
    if new_batch_data is not None:
        fields, _custom = await resolve_standard_fields(db, report.standard_id)
        col_updates, jsonb = _split_batch_data(fields, new_batch_data)
        _zero_missing_column_targets(col_updates, fields, set(new_batch_data))
        for key, value in col_updates.items():
            setattr(report, key, value)
        report.batch_data = jsonb or None
    report.updated_by = _actor_id(user)
    try:
        async with db.begin_nested():
            await db.flush()
            if new_values is not None:
                rows = await _validate_values(db, report.standard_id, new_values)
                await repo.replace_report_values(db, report.id, rows)
    except IntegrityError as exc:
        raise AppException(status_code=409, message="批号冲突，请刷新后重试") from exc
    return await get_report_detail(db, report_id)


async def delete_report(db: AsyncSession, report_id: uuid.UUID, user: Any) -> None:
    """作废 = 报告软删 + 值硬删（值矩阵单元格非审计对象）。"""
    report = await get_report_or_404(db, report_id)
    async with db.begin_nested():
        await repo.delete_report_values(db, report.id)
        report.is_deleted = True
        report.updated_by = _actor_id(user)
        await db.flush()


# ─────────────────────── 矩阵透视 ───────────────────────


async def matrix(
    db: AsyncSession,
    product_id: uuid.UUID,
    *,
    standard_ids: list[uuid.UUID] | None = None,
) -> dict[str, Any]:
    """产品维度矩阵：列=各标准 active 项目按名称归并（跨标准同 code 同列），
    行=报告，格=值。"""
    product = await get_product_or_404(db, product_id)
    standards = [
        s
        for s in await repo.list_standards(db, product_id=product_id, active_only=True)
        if standard_ids is None or s.id in standard_ids
    ]
    std_ids = [s.id for s in standards]
    items = await repo.list_items_of_standards(db, std_ids)
    items_by_std: dict[uuid.UUID, list[CoaStandardItem]] = {}
    for it in items:
        items_by_std.setdefault(it.standard_id, []).append(it)

    # 合并列：跨标准同名（同 code）项目共用一列，首次出现定列位；
    # item_ids 供前端按报告值回填（一份报告只属一个标准，至多命中一个 id）
    columns: list[dict[str, Any]] = []
    col_by_code: dict[str, dict[str, Any]] = {}
    for s in standards:
        for it in items_by_std.get(s.id, []):
            col = col_by_code.get(it.code)
            if col is None:
                col = {
                    "code": it.code,
                    "name_cn": it.name_cn,
                    "item_ids": [str(it.id)],
                    "spec_texts": [it.spec_text] if it.spec_text else [],
                }
                col_by_code[it.code] = col
                columns.append(col)
            else:
                col["item_ids"].append(str(it.id))
                if it.spec_text and it.spec_text not in col["spec_texts"]:
                    col["spec_texts"].append(it.spec_text)

    reports = await repo.list_reports(db, product_id)
    if standard_ids is not None:
        reports = [r for r in reports if r.standard_id in set(std_ids)]
    values = await repo.list_values_of_reports(db, [r.id for r in reports])
    value_map: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
    for v in values:
        value_map.setdefault(v.report_id, {})[str(v.item_id)] = {
            "num": v.value_num,
            "text": v.value_text,
        }

    # 各标准生效批次字段集（出具页动态渲染列/弹窗表单用）与行级合成视图
    fields_by_std: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for s in standards:
        fields_by_std[s.id], _custom = await resolve_standard_fields(db, s.id)

    std_by_id = {s.id: s for s in standards}
    rows = [
        report_dict(
            r,
            value_map=value_map.get(r.id, {}),
            batch_info=compose_batch_info(
                r, fields_by_std.get(r.standard_id, []), product_name=product.name
            ),
        )
        | {
            "standard_code": std_by_id[r.standard_id].code
            if r.standard_id in std_by_id
            else None
        }
        for r in reports
    ]
    return {
        "product": product_dict(product),
        "columns": columns,
        "standards": [
            standard_dict(
                s,
                item_count=len(items_by_std.get(s.id, [])),
                items=[item_dict(i) for i in items_by_std.get(s.id, [])],
            )
            | {"batch_fields": fields_by_std.get(s.id, [])}
            for s in standards
        ],
        "rows": rows,
    }
