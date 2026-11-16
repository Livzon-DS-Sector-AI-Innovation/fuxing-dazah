"""COA 出具登记：报告 CRUD、docx 导入匹配预览、产品维度矩阵透视。

守卫口径：
- report_no 全局唯一（预检 + SAVEPOINT 409）；(产品, 标准, 批号) 唯一——
  同批同标准只登记一份，补发=软删重登。
- 值的 item 必须归属报告标准；导入确认可带 new_items 并入标准（携带首份
  值，后端按新建 item id 归并，前端无需预知 UUID）。
- 矩阵：列=产品各标准 active 项目（两级列头），行=报告，格=值映射。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.qa.models import CoaReport, CoaSourceType, CoaStandardItem
from app.modules.qa.repository import coa as repo
from app.modules.qa.schemas.coa import CoaReportCreate, CoaReportUpdate, CoaValueIn
from app.modules.qa.service.coa.common import (
    _actor_id,
    get_product_or_404,
    get_report_or_404,
    get_standard_or_404,
    item_dict,
    product_dict,
    report_dict,
    standard_dict,
    value_dict,
)
from app.modules.qa.service.coa.docx_parse import parse_docx
from app.modules.qa.service.coa.standards import _insert_items


def _parse_to_raw(parse: Any) -> dict[str, Any]:
    return {
        "batch_info": parse.batch_info,
        "serial_no": parse.serial_no,
        "report_no": parse.report_no,
        "conclusion": parse.conclusion,
        "items": [
            {
                "name": it.name,
                "spec_text": it.spec_text,
                "result": it.result,
            }
            for it in parse.items
        ],
    }


def _report_draft(parse: Any) -> dict[str, Any]:
    """解析结果 → 报告头草稿（日期已解析为 ISO；出具日期人工填）。"""
    return {
        "report_no": parse.report_no,
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
) -> dict[str, Any]:
    """docx → 标准匹配 + 项目对齐 + 值预填（不落库）。"""
    parse = parse_docx(data)
    if not parse.report_no:
        raise AppException(status_code=400, message="未能从 docx 识别报告编号（No.）")

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
        "raw_extract": _parse_to_raw(parse),
    }

    if standard is not None:
        items = await repo.list_items(db, standard.id, active_only=False)
        by_code = {i.code: i for i in items}
        for it in parse.items:
            hit = by_code.get(it.code)
            if hit is None:
                result["unmatched_items"].append(
                    {
                        "name_cn": it.name,
                        "name_en": it.name_en,
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
            item_dict(i) for i in items if i.is_active and i.code not in hit_codes
        ]
    return result


# ─────────────────────── 报告 CRUD ───────────────────────


async def _validate_report_unique(
    db: AsyncSession,
    *,
    product_id: uuid.UUID,
    standard_id: uuid.UUID,
    report_no: str,
    batch_no: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    if await repo.find_report_by_no(db, report_no, exclude_id=exclude_id):
        raise AppException(status_code=409, message=f"报告编号 {report_no} 已存在")
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
    items = await repo.list_items(db, standard_id, active_only=False)
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


async def get_report_detail(db: AsyncSession, report_id: uuid.UUID) -> dict[str, Any]:
    row = await get_report_or_404(db, report_id)
    values = await repo.list_values_by_report(db, row.id)
    return report_dict(row, values=[value_dict(v) for v in values])


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
        report_no=payload.report_no.strip(),
        batch_no=payload.batch_no.strip(),
    )
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
                report_no=payload.report_no.strip(),
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
                remark=payload.remark,
                created_by=_actor_id(user),
                updated_by=_actor_id(user),
            )
            db.add(report)
            await db.flush()
            await repo.replace_report_values(db, report.id, rows)
    except IntegrityError as exc:
        raise AppException(
            status_code=409, message="报告编号或批号冲突，请刷新后重试"
        ) from exc
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
    head_fields = {
        "report_no",
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
        if key in ("report_no", "batch_no"):
            value = (value or "").strip()
        setattr(report, key, value)
    if "report_no" in touched or "batch_no" in touched:
        await _validate_report_unique(
            db,
            product_id=report.product_id,
            standard_id=report.standard_id,
            report_no=report.report_no,
            batch_no=report.batch_no,
            exclude_id=report.id,
        )
    report.updated_by = _actor_id(user)
    try:
        async with db.begin_nested():
            await db.flush()
            if new_values is not None:
                rows = await _validate_values(db, report.standard_id, new_values)
                await repo.replace_report_values(db, report.id, rows)
    except IntegrityError as exc:
        raise AppException(
            status_code=409, message="报告编号或批号冲突，请刷新后重试"
        ) from exc
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

    std_by_id = {s.id: s for s in standards}
    rows = [
        report_dict(
            r,
            value_map=value_map.get(r.id, {}),
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
            for s in standards
        ],
        "rows": rows,
    }
