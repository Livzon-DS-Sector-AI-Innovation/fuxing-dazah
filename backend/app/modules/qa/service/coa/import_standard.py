"""COA docx → 客户标准草稿（预览不落库）。

提取只产草稿，正式落库走 POST /coa/standards（人工编辑确认后提交），
与 qa 域「AI 只产提案、写入必经人工确认」同口径。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.qa.repository import coa as repo
from app.modules.qa.service.coa.ai_parse import (
    COA_AI_PROMPT_VERSION_STRUCTURE,
    parse_docx_ai,
)
from app.modules.qa.service.coa.common import builtin_key_of, product_dict


def _parse_to_raw(parse: Any) -> dict[str, Any]:
    """解析结果 → raw_extract 留底（复核/重放用，含中英分列与来源版本）。"""
    raw: dict[str, Any] = {
        "source": "ai",
        "prompt_version": COA_AI_PROMPT_VERSION_STRUCTURE,
        "batch_info": parse.batch_info,
        "serial_no": parse.serial_no,
        "report_no": parse.report_no,
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
            {"label_cn": f.label_cn, "label_en": f.label_en}
            for f in parse.batch_fields
        ]
    return raw


async def import_standard_preview(
    db: AsyncSession, data: bytes, *, filename: str = "coa.docx"
) -> dict[str, Any]:
    # 模板导入只要结构（字段标签+项目定义），值类字段由报告导入的 values 模式负责
    parse = await parse_docx_ai(data, filename, mode="structure")

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
            "unit": it.unit,
            "value_type": it.value_type,
            "spec_text": it.spec_text,
            "spec_min": it.spec_min,
            "spec_max": it.spec_max,
            "sort_order": idx,
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
        # 品名/批号/流水号及同义变体恒为内置字段，不进草稿（raw_extract 留底原文）
        "batch_fields_draft": [
            {
                "key": f.key,
                "label_cn": f.label_cn,
                "label_en": f.label_en,
                "field_type": f.field_type,
            }
            for f in parse.batch_fields
            if builtin_key_of(f.key) is None and builtin_key_of(f.label_cn) is None
        ],
        "standard_draft": {
            "code": parse.suggested_standard_code,
            # 标准名称默认取上传文件名（去扩展名），人工可改
            "name": Path(filename).stem or filename,
            "customer": None,
            "market": None,
            "version": None,
            "items": items,
        },
        "raw_extract": _parse_to_raw(parse),
    }
