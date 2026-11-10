"""PQR 服务层共享助手：审计、404 定位、年度锁定拦截、文字结果白名单
口径、各 ORM 序列化与 #min/#max 显示名——跨域共用，只依赖 repo 与模型。"""

from __future__ import annotations

import uuid
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
