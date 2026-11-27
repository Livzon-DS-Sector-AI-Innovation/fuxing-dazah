"""COA 模板可回填的字段清单：批次信息字段与标准检测项目。

品名、储存条件是产品级常量：系统里照常登记，COA 上保持模板原文（不进字段清单）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.models import CoaStandard, CoaStandardItem
from app.modules.qa.repository import coa as repo
from app.modules.qa.service.coa.common import (
    report_column_key_of,
    resolve_standard_fields,
)

# 品名、储存条件是产品级常量：系统里照常登记，COA 上保持模板原文
TEMPLATE_EXCLUDED_BATCH_FIELDS = frozenset({"product_name", "storage"})


@dataclass(frozen=True)
class FieldDef:
    """可以写进模板的一个字段：批次信息字段或标准检测项目。"""

    key: str  # batch:<字段键> | item:<项目 id>
    kind: str  # batch | item
    label_cn: str
    label_en: str | None
    field_type: str | None = None  # batch: text/date
    unit: str | None = None
    spec_text: str | None = None
    value_type: str | None = None


def field_dict(field: FieldDef) -> dict[str, Any]:
    return {
        "field": field.key,
        "kind": field.kind,
        "label_cn": field.label_cn,
        "label_en": field.label_en,
        "type": field.field_type,
        "unit": field.unit,
        "spec_text": field.spec_text,
        "value_type": field.value_type,
    }


def _batch_type(field: Mapping[str, Any]) -> str:
    """批次字段的写入类型：对应固定日期列（生产日期/有效期）或字段本身标了日期 → date。"""
    if _batch_column(field) in ("mfg_date", "exp_date") or field.get("field_type") == "date":
        return "date"
    return "text"


def _batch_column(field: Mapping[str, Any]) -> str | None:
    """批次字段键/标签对应的报告固定列（storage_conditions → storage），没有则 None。"""
    key = str(field["key"])
    return report_column_key_of(key) or (
        report_column_key_of(str(field.get("label_cn") or "")) or None
    )


def field_defs(
    effective: Sequence[Mapping[str, Any]], items: Iterable[CoaStandardItem]
) -> list[FieldDef]:
    """生效批次字段（去品名/储存条件）+ 标准项目 → 可以写进模板的字段（纯函数）。"""
    fields = [
        FieldDef(
            key=f"batch:{f['key']}",
            kind="batch",
            label_cn=str(f["label_cn"]),
            label_en=f.get("label_en"),
            field_type=_batch_type(f),
        )
        for f in effective
        # 品名/储存条件不回填：按「键或标签对应的固定列」排除——产品里这个字段的键
        # 可能叫 storage_conditions，只有标签「储存条件」能认出它是储存条件
        if (report_column_key_of(str(f["key"])) or str(f["key"])) not in TEMPLATE_EXCLUDED_BATCH_FIELDS
    ]
    for item in items:
        fields.append(
            FieldDef(
                key=f"item:{item.id}",
                kind="item",
                label_cn=item.name_cn,
                label_en=item.name_en,
                unit=item.unit,
                spec_text=item.spec_text,
                value_type=item.value_type,
            )
        )
    return fields


async def build_fields(db: AsyncSession, standard: CoaStandard) -> list[FieldDef]:
    """标准当前配置下可以回填的字段：生效批次字段（去品名/储存条件）+ 标准项目。"""
    effective, _custom = await resolve_standard_fields(db, standard.id)
    return field_defs(effective, await repo.list_items(db, standard.id))
