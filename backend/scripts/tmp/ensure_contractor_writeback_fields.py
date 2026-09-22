"""相关方准入回写 3 列幂等核对/建列脚本（contractor-admission-direct Ticket 02）。

dry-run（默认）只报告：AI审核结论/AI审核报告/AI不符合项 3 列契约核对（含选项值域）；
--apply 才真正补建缺失列。探针（2026-09-22）实证生产表 3 列已在且值域与插件一致
——生产预期全「exists 跳过」，本脚本对新环境兜底；重复执行输出一致（幂等）。

安全约束（底座 ensure_field）：已存在的列绝不修改（不一致只报 conflict 人工确认）；
只调 create_field，无删除/更新接口。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/ensure_contractor_writeback_fields.py           # dry-run
    .venv/Scripts/python.exe scripts/tmp/ensure_contractor_writeback_fields.py --apply   # 补建缺失列
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.modules.safety.service.bitable_direct import writer as bd_writer  # noqa: E402
from app.modules.safety.service.contractor_admission_direct.contract import (  # noqa: E402
    CONCLUSION_VALUES,
    DEFECT_CATEGORY_VALUES,
    WRITEBACK_CONCLUSION_FIELD,
    WRITEBACK_DEFECTS_FIELD,
    WRITEBACK_FIELD_TYPES,
    WRITEBACK_REPORT_FIELD,
)

SPECS: list[bd_writer.FieldSpec] = [
    bd_writer.FieldSpec(
        name=WRITEBACK_CONCLUSION_FIELD,
        field_type=WRITEBACK_FIELD_TYPES[WRITEBACK_CONCLUSION_FIELD],
        property_={"options": [{"name": o} for o in CONCLUSION_VALUES]},
    ),
    bd_writer.FieldSpec(
        name=WRITEBACK_REPORT_FIELD,
        field_type=WRITEBACK_FIELD_TYPES[WRITEBACK_REPORT_FIELD],
    ),
    bd_writer.FieldSpec(
        name=WRITEBACK_DEFECTS_FIELD,
        field_type=WRITEBACK_FIELD_TYPES[WRITEBACK_DEFECTS_FIELD],
        property_={"options": [{"name": o} for o in DEFECT_CATEGORY_VALUES]},
    ),
]


async def main(apply: bool) -> int:
    # SafetyBitableClient 同时满足 BitableFieldAdmin（list_fields/create_field）
    client = bd_writer.open_writer("contractor_admission", "admission")

    fields = await client.list_fields()
    print(f"== 回写 3 列契约核对 ==（表内 {len(fields)} 列，"
          f"{'APPLY' if apply else 'DRY-RUN'}）")
    rc = 0
    for spec in SPECS:
        result = await bd_writer.ensure_field(client, spec, apply=apply)
        print(f"  [{result.status}] {bd_writer.describe_spec(spec)}: {result.message}")
        if not result.ok:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv)))
