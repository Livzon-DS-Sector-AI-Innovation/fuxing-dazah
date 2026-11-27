"""PQR 服务层共享助手：操作日志（值变更 diff）、404 定位、年度锁定拦截、
文字结果白名单口径、各 ORM 序列化与 #min/#max 显示名——跨域共用，
只依赖 repo 与模型。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any
from unicodedata import normalize as _nfkc

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException, NotFoundException
from app.modules.qa.models import AprBatch, AprItem, AprProduct, AprSection
from app.modules.qa.repository import apr as repo
from app.platform.audit.service import record_audit_log
from app.platform.identity.models import User


def _actor_id(user: User | None) -> uuid.UUID | None:
    return user.id if user is not None else None


# PQR 操作日志动作词表：操作日志页按这组动作过滤，与删除前的旧审计事件
# （create/update/save_values 等）天然隔离，互不污染。
APR_LOG_ACTION_SAVED = "values_saved"
APR_LOG_ACTION_IMPORTED = "values_imported"
APR_LOG_ACTION_BATCH_DELETED = "batch_deleted"
APR_LOG_ACTIONS = (
    APR_LOG_ACTION_SAVED,
    APR_LOG_ACTION_IMPORTED,
    APR_LOG_ACTION_BATCH_DELETED,
)


def _cell_field(cell: Any, key: str) -> Any:
    """AprValue ORM 与待写 dict 统一按 key 取字段。"""
    if isinstance(cell, dict):
        return cell.get(key)
    return getattr(cell, key, None)


def _cell_snapshot(cell: Any) -> dict[str, Any] | None:
    """AprValue 或待写行 → 统一快照 dict；空值格返回 None。

    只保留有内容的部分（值/备注/行标签），无内容格在 diff 里表现为「空」。
    """
    if cell is None:
        return None
    value_num = _cell_field(cell, "value_num")
    value_text = _cell_field(cell, "value_text")
    remark = _cell_field(cell, "remark")
    row_label = _cell_field(cell, "row_label")
    snapshot: dict[str, Any] = {}
    if value_num is not None:
        snapshot["值"] = value_num
    elif value_text is not None:
        snapshot["值"] = value_text
    if row_label:
        snapshot["行标签"] = row_label
    if remark:
        snapshot["备注"] = remark
    return snapshot or None


def _diff_cell_values(
    old_values: Sequence[Any],
    new_rows: Sequence[Any],
    items_by_id: dict[uuid.UUID, AprItem],
    *,
    multi_row: bool,
    touched_only: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """逐格 diff 出变更前/后快照：键为「列名（第N行）」，只含实际变化的格。

    - touched_only=False（整批替换）：新旧并集都是 diff 候选，旧有新无 = 清空。
    - touched_only=True（merge 导入）：只看本次写入的格，未触及的旧值不参与。
    """
    old_map = {(v.item_id, v.row_seq): v for v in old_values}
    new_map = {
        (_cell_field(r, "item_id"), _cell_field(r, "row_seq")): r for r in new_rows
    }
    keys = new_map.keys() if touched_only else old_map.keys() | new_map.keys()

    def _key(item_id: uuid.UUID, row_seq: int, item: AprItem | None) -> tuple[Any, ...]:
        name = item.name_cn if item is not None else str(item_id)
        return (item.sort_order if item else 0, name, row_seq)

    old_out: dict[str, Any] = {}
    new_out: dict[str, Any] = {}
    for item_id, row_seq in sorted(keys, key=lambda k: _key(k[0], k[1], items_by_id.get(k[0]))):
        item = items_by_id.get(item_id)
        label = (
            f"{item.name_cn}（第{row_seq}行）"
            if item is not None and multi_row
            else (item.name_cn if item is not None else str(item_id))
        )
        old_snap = _cell_snapshot(old_map.get((item_id, row_seq)))
        new_snap = _cell_snapshot(new_map.get((item_id, row_seq)))
        if old_snap == new_snap:
            continue
        old_out[label] = old_snap
        new_out[label] = new_snap
    return old_out, new_out


def _value_log_extra(
    batch: AprBatch, section: AprSection, product: AprProduct, **extra: Any
) -> dict[str, Any]:
    """操作日志的定位上下文：产品/年度/批号/段——列表页与人读详情都靠它。"""
    return {
        "product_id": str(product.id),
        "product_name": product.name,
        "year": batch.year,
        "batch_no": batch.batch_no,
        "batch_id": str(batch.id),
        "section_id": str(section.id),
        "section_name": section.name,
        **extra,
    }


async def _record_value_changes(
    db: AsyncSession,
    *,
    user: User | None,
    batch: AprBatch,
    section: AprSection,
    product: AprProduct,
    items_by_id: dict[uuid.UUID, AprItem],
    old_values: Sequence[Any],
    new_rows: Sequence[Any],
    touched_only: bool,
    source: str,
    mode: str | None = None,
) -> bool:
    """PQR 值变更操作日志：一次保存一条，含全部变更格的前后快照。

    无实际变化时不落记录（保存成功但内容未变不算操作日志事件）。
    返回是否写了记录。
    """
    old_snap, new_snap = _diff_cell_values(
        old_values,
        new_rows,
        items_by_id,
        multi_row=section.multi_row,
        touched_only=touched_only,
    )
    if not old_snap and not new_snap:
        return False
    action = APR_LOG_ACTION_IMPORTED if source == "import" else APR_LOG_ACTION_SAVED
    await record_audit_log(
        db,
        action=action,
        user=user,
        user_id=_actor_id(user),
        resource_type="qa.apr_batch",
        resource_id=batch.id,
        old_value=old_snap or None,
        new_value=new_snap or None,
        extra=_value_log_extra(
            batch, section, product, source=source, changed=len(new_snap), **({"mode": mode} if mode else {})
        ),
    )
    return True


async def _get_product_or_404(db: AsyncSession, product_id: uuid.UUID) -> AprProduct:
    product = await repo.get_product(db, product_id)
    if product is None:
        raise NotFoundException("PQR 产品", str(product_id))
    return product


async def _get_section_or_404(db: AsyncSession, section_id: uuid.UUID) -> AprSection:
    section = await repo.get_section(db, section_id)
    if section is None:
        raise NotFoundException("模板段", str(section_id))
    return section


async def _get_batch_or_404(db: AsyncSession, batch_id: uuid.UUID) -> AprBatch:
    batch = await repo.get_batch(db, batch_id)
    if batch is None:
        raise NotFoundException("批次", str(batch_id))
    return batch


async def _get_item_or_404(db: AsyncSession, item_id: uuid.UUID) -> AprItem:
    item = await repo.get_item(db, item_id)
    if item is None:
        raise NotFoundException("列定义", str(item_id))
    return item


async def _ensure_year_open(db: AsyncSession, product_id: uuid.UUID, year: int) -> None:
    """产品×年度已锁定则拒绝写操作。

    行已存在时对锁定行加 FOR UPDATE：与 set_annual_review_lock 的读-改
    串行化，堵住「写入方读到 open → 锁定方提交 locked → 写入方提交」的
    交错（deviation 状态流转同模式）。行不存在时无行可锁，窗口收窄为
    「锁定行首次创建」的瞬间，内部系统可接受。
    """
    review = await repo.get_annual_review(db, product_id, year, for_update=True)
    if review is not None and review.status == "locked":
        raise AppException(
            status_code=422,
            message=f"{year} 年度已锁定（年终定稿），如需修改请先解锁。",
        )


def _normalize_quick_values(quick_values: list[str] | None) -> list[str]:
    """数值列文字结果白名单（NFKC 归一去空白）：行内保存与 Excel 导入同口径。"""
    return [_nfkc("NFKC", q).strip() for q in (quick_values or [])]


def _quick_values_hint(quick_values: list[str] | None) -> str:
    allowed = _normalize_quick_values(quick_values)
    if allowed:
        return f"文字结果只能填：{'、'.join(allowed)}。"
    return "未配置文字结果，请填数字。"


def _product_dict(
    row: AprProduct,
    *,
    section_count: int | None = None,
    item_count: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "name_en": row.name_en,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
        "remark": row.remark,
    }
    if section_count is not None:
        data["section_count"] = section_count
    if item_count is not None:
        data["item_count"] = item_count
    return data


def _section_dict(
    row: AprSection, *, items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "name": row.name,
        "data_kind": row.data_kind,
        "market": row.market,
        "stage": row.stage,
        "multi_row": row.multi_row,
        "sort_order": row.sort_order,
        "remark": row.remark,
    }
    if items is not None:
        data["items"] = items
    return data


def _item_dict(row: AprItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "section_id": str(row.section_id),
        "code": row.code,
        "group_name": row.group_name,
        "category": row.category,
        "name_cn": row.name_cn,
        "name_en": row.name_en,
        "value_type": row.value_type,
        "unit": row.unit,
        "spec_text": row.spec_text,
        "spec_min": row.spec_min,
        "spec_max": row.spec_max,
        "oot_min": row.oot_min,
        "oot_max": row.oot_max,
        "nd_policy": row.nd_policy,
        "quick_values": list(row.quick_values or []),
        "stat_precision": row.stat_precision,
        "trend_enabled": row.trend_enabled,
        "required": row.required,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
        "remark": row.remark,
    }


def _batch_dict(row: AprBatch) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "section_id": str(row.section_id),
        "year": row.year,
        "batch_no": row.batch_no,
        "seq": row.seq,
        "parent_batch_id": (
            str(row.parent_batch_id) if row.parent_batch_id is not None else None
        ),
        "remark": row.remark,
    }


def _display_name(name_cn: str, code: str) -> str:
    """#min/#max 成对列带 MIN/MAX 后缀：导出表头、导入模板与列匹配同口径。"""
    if code.endswith("#min"):
        return f"{name_cn} MIN"
    if code.endswith("#max"):
        return f"{name_cn} MAX"
    return name_cn


def _item_precision(item: dict[str, Any]) -> int:
    """列级统计精度；空 = 2（0 是合法精度，不能用 or 短路）。"""
    return 2 if item.get("stat_precision") is None else int(item["stat_precision"])
