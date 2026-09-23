"""knowledge 法规两表 article_no 建列幂等脚本（knowledge-direct Ticket 02，黄色操作）。

探针（2026-09-23）实证两表均无 article_no 列——handler 回写自始 FieldNameNotFound
静默失败（emergency_drill 采集表同款病灶），法规编号现只在 PG。本脚本为两表
（knowledge/collection 安全法规标准 + knowledge/collection_env 环保法规标准）
补建 article_no 文本列；建列后 handler 既有回写代码自动生效（零代码改动），
直读 query_latest_regulations 的 article_no 字段开始有值。

dry-run（默认）只报告；--apply 才真正 create_field。
安全约束（底座 ensure_field）：已存在的列绝不修改（不一致只报 conflict 人工确认）；
只调 create_field，无删除/更新接口；重复执行输出一致（幂等）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/create_article_no_field.py           # dry-run
    .venv/Scripts/python.exe scripts/tmp/create_article_no_field.py --apply   # 建列
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.modules.safety.service.bitable_direct import reader as bd_reader  # noqa: E402
from app.modules.safety.service.bitable_direct import writer as bd_writer  # noqa: E402

ARTICLE_NO_SPEC = bd_writer.FieldSpec(name="article_no", field_type=1)  # 文本

_KINDS = ("collection", "collection_env")


async def main(apply: bool) -> int:
    print(f"== knowledge 两表 article_no 建列契约核对 =="
          f"（{'APPLY' if apply else 'DRY-RUN'}）")
    rc = 0
    for kind in _KINDS:
        client = bd_reader.resolve_client("knowledge", kind)
        label = "安全法规标准" if kind == "collection" else "环保法规标准"
        fields = await client.list_fields()
        existing = [f.get("field_name") for f in fields]
        if "article_no" in existing:
            print(f"  [exists] {label}（{kind}）: article_no 列已在，跳过")
            continue
        result = await bd_writer.ensure_field(client, ARTICLE_NO_SPEC, apply=apply)
        print(f"  [{result.status}] {label}（{kind}）: {result.message}")
        if not result.ok:
            rc = 1
    if not apply and rc == 0:
        print("  dry-run 完成：加 --apply 执行建列（黄色操作，请人工确认后执行）")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--apply" in sys.argv)))
