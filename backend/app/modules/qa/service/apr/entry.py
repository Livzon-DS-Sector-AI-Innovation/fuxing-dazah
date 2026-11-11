"""PQR 批次与录入值：批次登记/编辑/删除、录入表单数据、整批全量替换保存。"""

from __future__ import annotations

import uuid
from typing import Any
from unicodedata import normalize as _nfkc

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.modules.qa.models import AprBatch, AprValueType
from app.modules.qa.repository import apr as repo
from app.modules.qa.schemas.apr import (
    AprBatchCreate,
    AprBatchUpdate,
    AprBatchValuesIn,
)
from app.modules.qa.service.apr.common import (
    APR_LOG_ACTION_BATCH_DELETED,
    _actor_id,
    _batch_dict,
    _ensure_year_open,
    _get_batch_or_404,
    _get_product_or_404,
    _get_section_or_404,
    _item_dict,
    _normalize_quick_values,
    _product_dict,
    _quick_values_hint,
    _record_value_changes,
    _section_dict,
    _value_log_extra,
)
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User


async def list_batches(
    db: AsyncSession,
    *,
    section_id: uuid.UUID,
    year: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = await repo.list_batches(
        db,
        section_id=section_id,
        year=year,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return [_batch_dict(r) for r in rows], total


async def create_batch(
    db: AsyncSession, payload: AprBatchCreate, user: User | None
) -> dict[str, Any]:
    section = await _get_section_or_404(db, payload.section_id)
    await _ensure_year_open(db, section.product_id, payload.year)
    if (
        await repo.find_batch(db, payload.section_id, payload.year, payload.batch_no)
        is not None
    ):
        raise AppException(
            status_code=409,
            message=f"批号 {payload.batch_no} 在该段 {payload.year} 年度已登记",
        )
    row = AprBatch(
        product_id=section.product_id,
        section_id=payload.section_id,
        year=payload.year,
        batch_no=payload.batch_no,
        seq=payload.seq,
        parent_batch_id=payload.parent_batch_id,
        remark=payload.remark,
        created_by=_actor_id(user),
        updated_by=_actor_id(user),
    )
    try:
        # 预检后仍可能与他人并发撞唯一索引（uq_qa_apr_batches_section_year_no），
        # 只回滚到 SAVEPOINT 转 409，不冒泡成 500（deviation 同模式）。
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise AppException(
            status_code=409,
            message=f"批号 {payload.batch_no} 在该段 {payload.year} 年度已登记",
        ) from None
    return _batch_dict(row)


async def update_batch(
    db: AsyncSession,
    batch_id: uuid.UUID,
    payload: AprBatchUpdate,
    user: User | None,
) -> dict[str, Any]:
    row = await _get_batch_or_404(db, batch_id)
    await _ensure_year_open(db, row.product_id, row.year)
    data = payload.model_dump(exclude_unset=True)
    new_year = data.get("year", row.year)
    new_no = data.get("batch_no", row.batch_no)
    # 改年度即迁移批次（连带其值）：旧年度开放不代表目标年度开放，
    # 必须按目标年度再校验锁定，否则批次可整体迁入已冻结年度。
    if new_year != row.year:
        await _ensure_year_open(db, row.product_id, new_year)
    if (new_year != row.year or new_no != row.batch_no) and (
        await repo.find_batch(db, row.section_id, new_year, new_no) is not None
    ):
        raise AppException(
            status_code=409, message=f"批号 {new_no} 在该段 {new_year} 年度已登记"
        )
    for field, value in data.items():
        setattr(row, field, value)
    row.updated_by = _actor_id(user)
    await db.flush()
    return _batch_dict(row)


async def delete_batch(
    db: AsyncSession, batch_id: uuid.UUID, user: User | None
) -> None:
    row = await _get_batch_or_404(db, batch_id)
    await _ensure_year_open(db, row.product_id, row.year)
    # 批次删除级联硬删全部录入值：操作日志记一条汇总（值随批次消失不留逐格明细）。
    old_values = await repo.list_values_of_batch(db, batch_id)
    section = await _get_section_or_404(db, row.section_id)
    product = await _get_product_or_404(db, row.product_id)
    await repo.delete_values_of_batch(db, batch_id)
    row.is_deleted = True
    row.updated_by = _actor_id(user)
    await db.flush()
    await record_audit_log(
        db,
        action=APR_LOG_ACTION_BATCH_DELETED,
        user=user,
        user_id=_actor_id(user),
        resource_type="qa.apr_batch",
        resource_id=row.id,
        old_value={"值数量": len(old_values)},
        new_value=None,
        extra=_value_log_extra(row, section, product, source="entry"),
    )


async def batch_values(db: AsyncSession, batch_id: uuid.UUID) -> dict[str, Any]:
    """录入表单渲染数据：批次 + 段内列定义 + 现有值 + 锁定状态。"""
    batch = await _get_batch_or_404(db, batch_id)
    section = await _get_section_or_404(db, batch.section_id)
    product = await _get_product_or_404(db, batch.product_id)
    items = [
        _item_dict(i)
        for i in await repo.list_items(db, batch.section_id, active_only=True)
    ]
    values = await repo.list_values_of_batch(db, batch_id)
    review = await repo.get_annual_review(db, batch.product_id, batch.year)
    return {
        "batch": _batch_dict(batch),
        "section": _section_dict(section),
        "product": _product_dict(product),
        "items": items,
        "values": [
            {
                "item_id": str(v.item_id),
                "row_seq": v.row_seq,
                "row_label": v.row_label,
                "value_num": v.value_num,
                "value_text": v.value_text,
                "remark": v.remark,
            }
            for v in values
        ],
        "locked": review is not None and review.status == "locked",
    }


async def save_batch_values(
    db: AsyncSession,
    batch_id: uuid.UUID,
    payload: AprBatchValuesIn,
    user: User | None,
) -> dict[str, Any]:
    """整批全量替换保存：锁拦截 + 列归属校验 + 值类型匹配 + (item,row) 去重。"""
    batch = await _get_batch_or_404(db, batch_id)
    await _ensure_year_open(db, batch.product_id, batch.year)
    section = await _get_section_or_404(db, batch.section_id)
    if not section.multi_row:
        # 单行段只认第 1 行：放任 row_seq>1 落库会在汇总里展开出幻影行。
        bad_rows = sorted({v.row_seq for v in payload.values if v.row_seq != 1})
        if bad_rows:
            raise AppException(
                status_code=422,
                message=f"该段为单行段，不支持第 {bad_rows[0]} 行等多行数据。",
            )
    items = {
        i.id: i for i in await repo.list_items(db, batch.section_id, active_only=True)
    }
    seen: set[tuple[uuid.UUID, int]] = set()
    rows: list[dict[str, Any]] = []
    for v in payload.values:
        item = items.get(v.item_id)
        if item is None:
            raise AppException(
                status_code=422,
                message="存在不属于该批次所在段（或已停用）的列定义。",
            )
        key = (v.item_id, v.row_seq)
        if key in seen:
            raise AppException(
                status_code=422,
                message=f"列「{item.name_cn}」第 {v.row_seq} 行重复提交。",
            )
        seen.add(key)
        if v.value_num is None and v.value_text is None and not v.remark:
            # 空值占位不落库。
            continue
        if item.value_type == AprValueType.NUMBER.value:
            # 数值列允许只填文字结果，但必须是列定义 quick_values 白名单里的
            # 值（如 未检出/<0.01）；NFKC 顺带修正全角数字与 ＜ 等兼容字符。
            if v.value_num is None and v.value_text is None:
                raise AppException(
                    status_code=422,
                    message=(
                        f"列「{item.name_cn}」为数值型，"
                        "须填写数值或文字结果（如 未检出）。"
                    ),
                )
            if v.value_text is not None:
                text = _nfkc("NFKC", v.value_text).strip()
                if text not in _normalize_quick_values(item.quick_values):
                    raise AppException(
                        status_code=422,
                        message=(
                            f"列「{item.name_cn}」为数值型，"
                            f"{_quick_values_hint(item.quick_values)}"
                        ),
                    )
                v.value_text = text
            rows.append(
                {
                    "item_id": v.item_id,
                    "row_seq": v.row_seq,
                    "row_label": v.row_label,
                    "value_num": v.value_num,
                    "value_text": v.value_text,
                    "remark": v.remark,
                }
            )
        else:
            if v.value_text is None:
                raise AppException(
                    status_code=422,
                    message=f"列「{item.name_cn}」为文字型，必须填写文字结果。",
                )
            rows.append(
                {
                    "item_id": v.item_id,
                    "row_seq": v.row_seq,
                    "row_label": v.row_label,
                    "value_num": None,
                    "value_text": v.value_text,
                    "remark": v.remark,
                }
            )
    # 必填校验：整批替换语义下，漏填的必填项会被静默清掉，这里显式拦下来。
    required_items = [item for item in items.values() if item.required]
    if required_items:
        filled = {(row["item_id"], row["row_seq"]) for row in rows}
        if section.multi_row:
            # 多行段只校验「有内容的行」；全空时回退到第 1 行，避免空批次整批清空。
            row_scope = sorted({row["row_seq"] for row in rows}) or [1]
        else:
            row_scope = [1]
        missing: list[str] = []
        for row_seq in row_scope:
            for item in required_items:
                if (item.id, row_seq) in filled:
                    continue
                missing.append(
                    f"第 {row_seq} 行「{item.name_cn}」"
                    if section.multi_row
                    else f"「{item.name_cn}」"
                )
        if missing:
            raise AppException(
                status_code=422,
                message="以下必填项未填写：" + "、".join(missing),
            )
    # 操作日志：替换前先取旧值做逐格 diff（含停用列——被清掉的旧值也要留痕）。
    old_values = await repo.list_values_of_batch(db, batch_id)
    items_all = {
        i.id: i for i in await repo.list_items(db, batch.section_id, active_only=False)
    }
    count = await repo.replace_batch_values(
        db, batch_id, rows, actor_id=_actor_id(user)
    )
    await _record_value_changes(
        db,
        user=user,
        batch=batch,
        section=section,
        product=await _get_product_or_404(db, batch.product_id),
        items_by_id=items_all,
        old_values=old_values,
        new_rows=rows,
        touched_only=False,
        source="entry",
    )
    return {"batch_id": str(batch_id), "saved": count}
