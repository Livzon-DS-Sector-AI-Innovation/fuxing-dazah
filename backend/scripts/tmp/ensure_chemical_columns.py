"""危化品库存总表回写列幂等核对/建列脚本（chemical_inventory-direct Ticket 02）。

dry-run（默认）只报告：两列风险列 + 15 字段契约核对；--apply 才真正补建缺失的风险列。
探针（2026-09-22）实证生产表两列已在且选项与契约一致——生产预期全「exists 跳过」，
本脚本对新环境兜底；重复执行输出一致（幂等）。

安全约束（底座 ensure_field）：已存在的列绝不修改；只调 create_field，无删除接口。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/ensure_chemical_columns.py           # dry-run
    .venv/Scripts/python.exe scripts/tmp/ensure_chemical_columns.py --apply   # 补建缺失列
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.modules.safety.service.bitable_direct import writer as bd_writer  # noqa: E402
from app.modules.safety.service.chemical_inventory_direct.contract import (  # noqa: E402
    EXPECTED_BITABLE_FIELDS,
    RISK_FLAG_FIELD,
    RISK_FLAG_OPTIONS,
    RISK_NOTE_FIELD,
    RISK_NOTE_OPTIONS,
)

SELECT_TYPE = 3        # Bitable 单选
MULTI_SELECT_TYPE = 4  # Bitable 多选

SPECS: list[bd_writer.FieldSpec] = [
    bd_writer.FieldSpec(
        name=RISK_FLAG_FIELD,
        field_type=SELECT_TYPE,
        property_={"options": [{"name": o} for o in RISK_FLAG_OPTIONS]},
    ),
    bd_writer.FieldSpec(
        name=RISK_NOTE_FIELD,
        field_type=MULTI_SELECT_TYPE,
        property_={"options": [{"name": o} for o in RISK_NOTE_OPTIONS]},
    ),
]


async def main(apply: bool) -> int:
    # SafetyBitableClient 同时满足 BitableFieldAdmin（list_fields/create_field）
    client = bd_writer.open_writer("chemical_inventory", "inventory")

    fields = await client.list_fields()
    present = {f.get("field_name") for f in fields}
    missing_contract = sorted(set(EXPECTED_BITABLE_FIELDS) - present)
    print(f"== 字段契约核对 ==（表内 {len(fields)} 列）")
    if missing_contract:
        print(f"  [!!] 契约字段缺失: {missing_contract}")
    else:
        print("  [OK] 15 列契约字段全部在表")

    print(f"== 回写列核对 ==（{'APPLY' if apply else 'DRY-RUN'}）")
    rc = 0
    for spec in SPECS:
        result = await bd_writer.ensure_field(client, spec, apply=apply)
        print(f"  [{result.status}] {spec.name}: {result.message}")
        if not result.ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv)))
