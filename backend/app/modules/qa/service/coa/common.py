"""COA 服务层共享助手：404 定位、ORM 序列化 dict（响应统一形态）。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.qa.models import (
    CoaProduct,
    CoaReport,
    CoaReportValue,
    CoaStandard,
    CoaStandardItem,
)
from app.modules.qa.repository import coa as repo
from app.platform.identity.models import User


def _actor_id(user: User | None) -> uuid.UUID | None:
    return user.id if user is not None else None


async def get_product_or_404(db: AsyncSession, product_id: uuid.UUID) -> CoaProduct:
    row = await repo.get_product(db, product_id)
    if row is None:
        raise NotFoundException("COA 产品")
    return row


async def get_standard_or_404(db: AsyncSession, standard_id: uuid.UUID) -> CoaStandard:
    row = await repo.get_standard(db, standard_id)
    if row is None:
        raise NotFoundException("客户标准")
    return row


async def get_item_or_404(
    db: AsyncSession, item_id: uuid.UUID, *, standard_id: uuid.UUID | None = None
) -> CoaStandardItem:
    row = await repo.get_item(db, item_id)
    if row is None or (standard_id is not None and row.standard_id != standard_id):
        raise NotFoundException("标准项目")
    return row


async def get_report_or_404(db: AsyncSession, report_id: uuid.UUID) -> CoaReport:
    row = await repo.get_report(db, report_id)
    if row is None:
        raise NotFoundException("COA 报告")
    return row


# ─────────────────────── 序列化 ───────────────────────


def product_dict(
    row: CoaProduct, *, standard_count: int | None = None
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
    if standard_count is not None:
        data["standard_count"] = standard_count
    return data


def standard_dict(
    row: CoaStandard,
    *,
    item_count: int | None = None,
    report_count: int | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if item_count is None and items is not None:
        item_count = len(items)
    data: dict[str, Any] = {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "code": row.code,
        "name": row.name,
        "customer": row.customer,
        "market": row.market,
        "version": row.version,
        "is_active": row.is_active,
        "source": row.source,
        "remark": row.remark,
    }
    if item_count is not None:
        data["item_count"] = item_count
    if report_count is not None:
        data["report_count"] = report_count
    if items is not None:
        data["items"] = items
    return data


def item_dict(row: CoaStandardItem) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "standard_id": str(row.standard_id),
        "code": row.code,
        "group_name": row.group_name,
        "name_cn": row.name_cn,
        "name_en": row.name_en,
        "value_type": row.value_type,
        "unit": row.unit,
        "spec_text": row.spec_text,
        "spec_min": row.spec_min,
        "spec_max": row.spec_max,
        "sort_order": row.sort_order,
        "is_active": row.is_active,
        "remark": row.remark,
    }


def report_dict(
    row: CoaReport,
    *,
    values: list[dict[str, Any]] | None = None,
    value_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "standard_id": str(row.standard_id),
        "report_no": row.report_no,
        "serial_no": row.serial_no,
        "batch_no": row.batch_no,
        "mfg_date": row.mfg_date.isoformat() if row.mfg_date else None,
        "exp_date": row.exp_date.isoformat() if row.exp_date else None,
        "issued_date": row.issued_date.isoformat() if row.issued_date else None,
        "packaging": row.packaging,
        "batch_size": row.batch_size,
        "storage": row.storage,
        "conclusion": row.conclusion,
        "source": row.source,
        "remark": row.remark,
    }
    if values is not None:
        data["values"] = values
    if value_map is not None:
        data["value_map"] = value_map
    return data


def value_dict(row: CoaReportValue) -> dict[str, Any]:
    return {
        "item_id": str(row.item_id),
        "value_num": row.value_num,
        "value_text": row.value_text,
        "remark": row.remark,
    }
