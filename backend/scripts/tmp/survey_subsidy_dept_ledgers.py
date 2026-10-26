"""提炼四部/六部监护补贴台账只读探查（换源前置盘点）。

只读，零写入。对两条 wiki 挂载的 Bitable 各输出：
  1. wiki 节点 token → 底层 Base app_token 解析 + 应用名（判定四部/六部归属）；
  2. list_fields 全字段盘点（与五部模板 7 列核对：监护人/监护人级别/特殊作业类型/
     作业级别/开始时间/结束时间/作业地点+作业内容）；
  3. 首 3 行样例（字段值形态：人员字段/select/毫秒时间戳）。

用法（backend 目录下）：

    .venv/bin/python scripts/tmp/survey_subsidy_dept_ledgers.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402
from app.modules.safety.feishu.client import get_safety_tenant_token  # noqa: E402
from app.modules.safety.feishu.subscribe import (  # noqa: E402
    resolve_canonical_app_token,
)

SOURCES = [
    ("wiki-A", "Kq15wDxPoibykdkBZ12ce0wjnSh", "tblGELhxJrfIyBal"),
    ("wiki-B", "EpW4wkioGivl13kihomcDA0AnTd", "tblDqCn4k6cnGD0V"),
]

BITABLE_APP_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"


async def app_meta(http: httpx.AsyncClient, bearer: str, token: str) -> dict[str, Any]:
    resp = await http.get(
        BITABLE_APP_URL.format(app_token=token),
        headers={"Authorization": f"Bearer {bearer}"},
    )
    return resp.json()


def brief(value: Any, limit: int = 120) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


async def main() -> int:
    bearer = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=20) as http:
        for label, wiki_token, table_id in SOURCES:
            print(f"\n{'=' * 70}\n[{label}] wiki={wiki_token} table={table_id}")

            meta = await app_meta(http, bearer, wiki_token)
            app = (meta.get("data") or {}).get("app") or {}
            print(f"meta code={meta.get('code')} name={app.get('name')!r}")
            canonical = await resolve_canonical_app_token(http, bearer, wiki_token)
            print(f"canonical app_token={canonical}")

            client = SafetyBitableClient(app_token=wiki_token, table_id=table_id)
            fields = await client.list_fields(table_id=table_id)
            print(f"fields({len(fields)}):")
            for f in fields:
                ui = f.get("ui_type")
                ui = ui.get("ui_type") if isinstance(ui, dict) else ui
                print(f"  - {f.get('field_name')}  type={f.get('type')} ui_type={ui}")

            rows = await client.search_records(table_id=table_id, page_size=3)
            items = rows if isinstance(rows, list) else (rows or {}).get("items", [])
            print(f"sample rows({len(items)}):")
            for row in items[:3]:
                fields_data = row.get("fields") or {}
                for k, v in fields_data.items():
                    print(f"    {k} = {brief(v)}")
                print("    ---")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
