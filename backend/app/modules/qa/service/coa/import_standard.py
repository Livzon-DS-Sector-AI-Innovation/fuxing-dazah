"""COA docx → 客户标准草稿（预览不落库）。

提取只产草稿，正式落库走 POST /coa/standards（人工编辑确认后提交），
与 qa 域「AI 只产提案、写入必经人工确认」同口径。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.repository import coa as repo
from app.modules.qa.service.coa.common import product_dict
from app.modules.qa.service.coa.docx_parse import parse_docx


def _parse_to_raw(parse: Any) -> dict[str, Any]:
    """解析结果 → raw_extract 留底（复核/重放用，只留可序列化部分）。"""
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


async def import_standard_preview(db: AsyncSession, data: bytes) -> dict[str, Any]:
    parse = parse_docx(data)

    # 产品匹配：短码建议 → 中文名精确；都不中则返回建品草稿
    matched = None
    if parse.suggested_product_code:
        matched = await repo.find_product_by_code(db, parse.suggested_product_code)
    if matched is None and parse.product_cn:
        matched = await repo.find_product_by_name(db, parse.product_cn)

    items = [
        {
            "name_cn": it.name,
            "name_en": it.name_en,
            "value_type": it.value_type,
            "spec_text": it.spec_text,
            "spec_min": it.spec_min,
            "spec_max": it.spec_max,
            "sort_order": idx,
            "is_active": True,
        }
        for idx, it in enumerate(parse.items)
    ]
    return {
        "product": product_dict(matched) if matched else None,
        "product_draft": {
            "code": parse.suggested_product_code,
            "name": parse.product_cn,
            "name_en": parse.product_en,
        },
        "standard_draft": {
            "code": parse.suggested_standard_code,
            "name": f"COA 标准 {parse.suggested_standard_code or ''}".strip(),
            "customer": None,
            "market": None,
            "version": None,
            "items": items,
        },
        "raw_extract": _parse_to_raw(parse),
    }
