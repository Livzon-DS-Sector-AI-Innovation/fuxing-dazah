"""四部/六部监护补贴台账全量取值盘点（解析器设计前置）。

只读。拉全量表，输出：
  - 行数；
  - 特殊作业类型 / 作业级别 / 监护证类别 全部去重值及计数；
  - 日期 / 时间段 全部去重原文（文本列，格式盘点）；
  - 姓名列形态（text 数组）。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from typing import Any

sys.path.insert(0, ".")

from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.service.bitable_direct.reader import (
    fetch_all_records,  # noqa: E402
)

SOURCES = [
    ("六部", "Kq15wDxPoibykdkBZ12ce0wjnSh", "tblGELhxJrfIyBal",
     ["姓名", "特殊作业类型", "作业级别", "作业地点及内容", "日期", "时间段"]),
    ("四部", "EpW4wkioGivl13kihomcDA0AnTd", "tblDqCn4k6cnGD0V",
     ["姓名", "特殊作业类型", "监护内容（具体到作业位置）", "日期", "作业级别",
      "时间段（写全：如8:30-11:00  13:30-17:00）", "监护证类别"]),
]


def as_text(value: Any) -> str:
    """Text 列 list[{text}] → str；其余 JSON 化。"""
    if isinstance(value, list):
        return "".join(
            item.get("text", "") for item in value if isinstance(item, dict)
        )
    return json.dumps(value, ensure_ascii=False)


def as_label(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    return str(value)


async def main() -> int:
    for label, token, table, fields in SOURCES:
        client = SafetyBitableClient(app_token=token, table_id=table)
        rows = await fetch_all_records(client, table_id=table, field_names=fields)
        print(f"\n{'=' * 70}\n[{label}] rows={len(rows)}")

        for field in fields:
            counter: Counter[str] = Counter()
            for row in rows:
                fv = (row.get("fields") or {}).get(field)
                if field in ("日期",) or "时间段" in field or "地点" in field or "内容" in field:
                    continue
                counter[as_label(fv)] += 1
            if counter:
                print(f"\n{field}: {dict(counter)}")

        for field in ("日期", "时间段", "时间段（写全：如8:30-11:00  13:30-17:00）"):
            if field not in fields:
                continue
            values = Counter(as_text((row.get("fields") or {}).get(field)) for row in rows)
            print(f"\n{field} 去重 {len(values)} 种:")
            for value, count in values.most_common():
                print(f"  {count:>2} × {value!r}")

        names = Counter(as_text((row.get("fields") or {}).get("姓名")) for row in rows)
        print(f"\n姓名 {len(names)} 人: {dict(names)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
