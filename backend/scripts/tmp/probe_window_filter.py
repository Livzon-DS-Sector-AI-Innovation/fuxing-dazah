"""中控报警窗口过滤异常验证（只读）：对单表跑 ExactDate 窗口 search，
打印命中数、首末记录的「日期」原始值与分页行为，判断过滤是否生效。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app.modules.safety.feishu.client import get_safety_tenant_token  # noqa: E402
from app.modules.safety.service.central_alarm.service import (  # noqa: E402
    central_alarm_app_token,
)

TABLE = "tblpO3p8tMal4B1n"  # 车间一（达托）
NAME = "日期"


def _exact(moment: datetime) -> list[str]:
    return ["ExactDate", str(int(moment.timestamp() * 1000))]


async def main() -> None:
    token = await get_safety_tenant_token()
    bj = timezone(timedelta(hours=8))
    now = datetime.now(bj)
    start_day = (now - timedelta(days=7)).date()

    conds_and = [{
        "field_name": NAME, "operator": "isGreater",
        "value": _exact(datetime.combine(start_day, datetime.min.time(), tzinfo=bj)),
    }, {
        "field_name": NAME, "operator": "isLess",
        "value": _exact(datetime.combine(
            now.date() + timedelta(days=1), datetime.min.time(), tzinfo=bj,
        )),
    }]

    async with httpx.AsyncClient(timeout=30) as http:
        # 形态 A： ExactDate 双条件 and
        async def search(body: dict[str, Any]) -> dict[str, Any]:
            resp = await http.post(
                f"https://open.feishu.cn/open-apis/bitable/v1/apps"
                f"/{central_alarm_app_token()}/tables/{TABLE}/records/search",
                headers={"Authorization": f"Bearer {token}"}, json=body,
            )
            return resp.json()

        d = await search({"page_size": 20, "filter": {
            "conjunction": "and", "conditions": conds_and}})
        print("A) ExactDate and-window: code=", d.get("code"), "msg=", d.get("msg"))
        data = d.get("data", {}) or {}
        items = data.get("items", []) or []
        print("   first_page=", len(items), "has_more=", data.get("has_more"))
        for rec in items[:3]:
            print("   raw 日期 =", (rec.get("fields") or {}).get(NAME))
        # 翻页 3 次看是否收敛
        total_pages, seen = 1, len(items)
        pt = data.get("page_token")
        while data.get("has_more") and pt and total_pages < 3:
            d2 = await search({"page_size": 20, "page_token": pt, "filter": {
                "conjunction": "and", "conditions": conds_and}})
            data2 = d2.get("data", {}) or {}
            seen += len(data2.get("items", []) or [])
            pt = data2.get("page_token")
            total_pages += 1
            if not (d2.get("data", {}) or {}).get("has_more"):
                break
        print("   pages_walked=", total_pages, "seen=", seen)

        # 形态 B：不带 filter 的 search（对照全量）
        d3 = await search({"page_size": 20})
        data3 = d3.get("data", {}) or {}
        print("B) no-filter search: first_page=",
              len(data3.get("items", []) or []),
              "has_more=", data3.get("has_more"))

        # 形态 C：单条件 ExactDate（只下界）
        d4 = await search({"page_size": 20, "filter": {
            "conjunction": "and", "conditions": conds_and[:1]}})
        data4 = d4.get("data", {}) or {}
        print("C) single-bound ExactDate: code=", d4.get("code"),
              "first_page=", len(data4.get("items", []) or []),
              "has_more=", data4.get("has_more"))
        items4 = data4.get("items", []) or []
        for rec in items4[:3]:
            print("   raw 日期 =", (rec.get("fields") or {}).get(NAME))


if __name__ == "__main__":
    asyncio.run(main())
