"""COA 服务层共享助手：404 定位、内置批次字段、ORM 序列化 dict（响应统一形态）。"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundException
from app.modules.qa.models import (
    CoaProduct,
    CoaProductField,
    CoaReport,
    CoaReportValue,
    CoaStandard,
    CoaStandardField,
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


# ─────────────────────── 内置批次字段 ───────────────────────
# 品名/批号/流水号恒定存在且必填：代码常量不落库，读时合并置顶、
# 写路径拒绝保留键（DB 只存自定义字段，后续填数据/填模板的稳定锚点）。

BUILTIN_BATCH_FIELDS: tuple[dict[str, Any], ...] = (
    {"key": "product_name", "label_cn": "品名", "label_en": "Product Name", "field_type": "text"},
    {"key": "batch_no", "label_cn": "批号", "label_en": "Batch No.", "field_type": "text"},
    {"key": "serial_no", "label_cn": "流水号", "label_en": "Serial No.", "field_type": "text"},
)
RESERVED_BATCH_KEYS = frozenset(f["key"] for f in BUILTIN_BATCH_FIELDS)

# 同义变体（含标签原文）→ 内置键：归一后比对，防模板同义标签产出重复字段
_BUILTIN_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "product_name",
        ("productname", "product", "品名", "产品名称", "产品名"),
    ),
    (
        "batch_no",
        ("batchno", "batchnumber", "batch", "lot", "lotno", "lotnumber", "批号", "批次号", "批次编号"),
    ),
    (
        "serial_no",
        ("serialno", "serialnumber", "sn", "series", "流水号", "序列号"),
    ),
)


def _normalize_field_token(value: str) -> str:
    """别名比对归一：NFKC + casefold + 去除空白与标点（保留字母数字与中文）。"""
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(ch for ch in text if ch.isalnum())


_BUILTIN_ALIAS_MAP: dict[str, str] = {
    _normalize_field_token(alias): key
    for key, aliases in _BUILTIN_ALIASES
    for alias in (key, *aliases)
}


def builtin_key_of(key_or_label: str) -> str | None:
    """字段键/标签归一后命中内置字段 → 返回内置键，否则 None。"""
    return _BUILTIN_ALIAS_MAP.get(_normalize_field_token(key_or_label))


def merge_builtin_fields(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """生效字段集 = 内置 3 字段置顶（必填锁定）+ 自定义字段顺延。"""
    builtin_rows = [
        {
            "id": None,
            "key": field["key"],
            "label_cn": field["label_cn"],
            "label_en": field["label_en"],
            "field_type": field["field_type"],
            "sort_order": idx,
            "builtin": True,
            "required": True,
        }
        for idx, field in enumerate(BUILTIN_BATCH_FIELDS)
    ]
    return builtin_rows + list(rows)


def effective_fields(
    standard: CoaStandard,
    overrides: Sequence[CoaStandardField],
    product_defaults: Sequence[CoaProductField],
) -> tuple[list[dict[str, Any]], bool]:
    """生效字段集（纯函数）：覆盖标志为真用标准覆盖行，否则用产品默认行。

    覆盖与否看标准上的 batch_fields_overridden 标志，而不是「有没有行」：
    显式保存的空自定义集也是覆盖（不回落产品默认）。
    返回 (字段列表, 是否自定义覆盖)；覆盖行不含内置键（写路径已拒绝）。
    """
    if standard.batch_fields_overridden:
        return merge_builtin_fields([standard_field_dict(r) for r in overrides]), True
    return merge_builtin_fields([product_field_dict(r) for r in product_defaults]), False


async def resolve_standard_fields(
    db: AsyncSession, standard_id: uuid.UUID
) -> tuple[list[dict[str, Any]], bool]:
    """生效字段集 = 内置 3 字段置顶 +（标准覆盖 ?? 产品默认）。"""
    standard = await get_standard_or_404(db, standard_id)
    if standard.batch_fields_overridden:
        return effective_fields(
            standard, await repo.list_standard_fields(db, standard_id), []
        )
    return effective_fields(
        standard, [], await repo.list_product_fields(db, standard.product_id)
    )


# ─────────────────────── 报告固定列对齐 ───────────────────────
# 模板自定义字段的 key/标签归一后命中下列报告固定列时，值镜像写固定列
# （否则进 batch_data JSONB）；读取时按同口径合成回字段键视图。
# 与内置字段别名同思路：NFKC + casefold + 去空白标点后比对。

_REPORT_COLUMN_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "mfg_date",
        ("mfgdate", "manufacturingdate", "manufacturedate", "productiondate",
         "生产日期", "制造日期"),
    ),
    (
        "exp_date",
        ("expdate", "expirydate", "expirationdate", "expiry", "expiration",
         "有效期", "有效期至", "失效期", "失效日期", "有效日期"),
    ),
    (
        "packaging",
        ("package", "packing", "packagingspec", "包装", "包装规格", "包装形式"),
    ),
    ("batch_size", ("batchsize", "quantity", "批量", "数量")),
    (
        "storage",
        ("storagecondition", "storecondition", "storageconditions",
         "储存条件", "贮存条件", "储藏条件", "储存", "贮存"),
    ),
)

_REPORT_COLUMN_ALIAS_MAP: dict[str, str] = {
    _normalize_field_token(alias): key
    for key, aliases in _REPORT_COLUMN_ALIASES
    for alias in (key, *aliases)
}

# 固定列 → 值读取器（date 列转 ISO 文本，其余原样）
_REPORT_COLUMN_GETTERS: dict[str, Any] = {
    "mfg_date": lambda row: row.mfg_date.isoformat() if row.mfg_date else None,
    "exp_date": lambda row: row.exp_date.isoformat() if row.exp_date else None,
    "packaging": lambda row: row.packaging,
    "batch_size": lambda row: row.batch_size,
    "storage": lambda row: row.storage,
}


def report_column_key_of(key_or_label: str) -> str | None:
    """字段键/标签归一后命中报告固定列 → 返回列名，否则 None。"""
    return _REPORT_COLUMN_ALIAS_MAP.get(_normalize_field_token(key_or_label))


def compose_batch_info(
    report: CoaReport,
    fields: Sequence[dict[str, Any]],
    *,
    product_name: str | None = None,
) -> dict[str, str]:
    """报告批次信息合成视图：key=生效字段集字段键（含内置 3 键）。

    内置键走报告头/产品名；自定义键经固定列别名取列值，否则取 batch_data；
    空值不入（前端按字段集渲染，缺键即空格）。
    """
    info: dict[str, str] = {}
    for f in fields:
        key = f["key"]
        if key == "product_name":
            value = product_name
        elif key == "batch_no":
            value = report.batch_no
        elif key == "serial_no":
            value = report.serial_no
        else:
            column = report_column_key_of(key)
            if column is not None:
                value = _REPORT_COLUMN_GETTERS[column](report)
            else:
                value = (report.batch_data or {}).get(key)
        if value:
            info[key] = str(value)
    return info


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


def product_field_dict(row: CoaProductField) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "key": row.key,
        "label_cn": row.label_cn,
        "label_en": row.label_en,
        "field_type": row.field_type,
        "sort_order": row.sort_order,
        "builtin": False,
        "required": False,
    }


def standard_field_dict(row: CoaStandardField) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "standard_id": str(row.standard_id),
        "key": row.key,
        "label_cn": row.label_cn,
        "label_en": row.label_en,
        "field_type": row.field_type,
        "sort_order": row.sort_order,
        "builtin": False,
        "required": False,
    }


def template_status_of(
    row: CoaStandard, drift: Mapping[str, Any] | None = None
) -> str:
    """none=没上传模板；unbound=已上传未确认标注；bound=标注已确认；
    stale=标注确认后字段配置变了，要重新核对才能生成 COA。

    偏差要对着当前字段配置算（template_bind.binding_drift），调用方查好了传进来；
    没传按没有偏差处理。
    """
    if not row.template_key:
        return "none"
    if not row.template_binding:
        return "unbound"
    return "stale" if drift else "bound"


def standard_dict(
    row: CoaStandard,
    *,
    item_count: int | None = None,
    report_count: int | None = None,
    items: list[dict[str, Any]] | None = None,
    template_drift: Mapping[str, Any] | None = None,
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
        "template_status": template_status_of(row, template_drift),
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
        "default_value": row.default_value,
        "remark": row.remark,
    }


def report_dict(
    row: CoaReport,
    *,
    values: list[dict[str, Any]] | None = None,
    value_map: dict[str, dict[str, Any]] | None = None,
    batch_info: dict[str, str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(row.id),
        "product_id": str(row.product_id),
        "standard_id": str(row.standard_id),
        "serial_no": row.serial_no,
        "batch_no": row.batch_no,
        "mfg_date": row.mfg_date.isoformat() if row.mfg_date else None,
        "exp_date": row.exp_date.isoformat() if row.exp_date else None,
        "packaging": row.packaging,
        "batch_size": row.batch_size,
        "storage": row.storage,
        "source": row.source,
        "remark": row.remark,
    }
    if values is not None:
        data["values"] = values
    if value_map is not None:
        data["value_map"] = value_map
    if batch_info is not None:
        data["batch_info"] = batch_info
    return data


def value_dict(row: CoaReportValue) -> dict[str, Any]:
    return {
        "item_id": str(row.item_id),
        "value_num": row.value_num,
        "value_text": row.value_text,
        "remark": row.remark,
    }
