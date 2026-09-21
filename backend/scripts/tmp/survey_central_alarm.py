"""中控报警 15 表只读探针（直读改造前置盘点，批次一-1）。

只读，零写入。输出：
  1. 白名单 15 表的表名（GET /tables），标注 workshop/line 推导结果与配置表排除；
  2. 每表 list_fields 字段名/类型（同构性核对，标记各表差异）；
  3. 每表全量行数（分页计数）与近 30 天「日期」窗口行数（下推过滤）；
  4. 全量拉取 15 表总耗时与总行数（评估 API 直读 <2s 可行性）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_central_alarm.py

退出码：0 成功；2 连接未配置或停用；3 拉取失败。
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import Counter
from typing import Any

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.client import get_safety_tenant_token  # noqa: E402
from app.modules.safety.service.central_alarm.bitable_mapper import (  # noqa: E402
    derive_workshop_line,
)
from app.modules.safety.service.central_alarm.service import (  # noqa: E402
    _is_config_table,
    central_alarm_app_token,
    central_alarm_table_ids,
)

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50
WINDOW_DAYS = 30


async def _get_json(http: httpx.AsyncClient, token: str, url: str,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = await http.get(url, headers={"Authorization": f"Bearer {token}"},
                          params=params)
    d = resp.json()
    if not isinstance(d, dict) or d.get("code", 0) != 0:
        raise RuntimeError(f"API failed: code={d.get('code') if isinstance(d, dict) else '?'}"
                           f" msg={d.get('msg') if isinstance(d, dict) else '?'} url={url}")
    return d.get("data", {}) or {}


async def _fetch_table_names(http: httpx.AsyncClient, token: str,
                             app_token: str) -> dict[str, str]:
    data = await _get_json(http, token, f"{BASE_URL}/{app_token}/tables")
    return {i.get("table_id", ""): i.get("name", "")
            for i in (data.get("items", []) or [])}


async def _list_fields(http: httpx.AsyncClient, token: str, app_token: str,
                       table_id: str) -> list[dict[str, Any]]:
    data = await _get_json(http, token,
                           f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
    return list(data.get("items", []) or [])


async def _count_all(http: httpx.AsyncClient, token: str, app_token: str,
                     table_id: str) -> tuple[int, float, int]:
    """全量分页计数。返回 (行数, 耗时秒, 页数)。"""
    t0 = time.perf_counter()
    total, pages = 0, 0
    page_token: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, Any] = {"page_size": PAGE_SIZE}
        if page_token:
            params["page_token"] = page_token
        data = await _get_json(
            http, token, f"{BASE_URL}/{app_token}/tables/{table_id}/records",
            params=params,
        )
        total += len(data.get("items", []) or [])
        pages += 1
        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data.get("page_token")
    return total, time.perf_counter() - t0, pages


async def _count_window(http: httpx.AsyncClient, token: str, app_token: str,
                        table_id: str) -> int:
    """近 N 天「日期」窗口行数（filter 下推 ExactDate，北京时间按天）。"""
    from datetime import datetime, timedelta, timezone

    bj = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj)
    start_day = (now_bj - timedelta(days=WINDOW_DAYS)).date()

    def _exact(moment: datetime) -> list[str]:
        return ["ExactDate", str(int(moment.timestamp() * 1000))]

    conds = [{
        "field_name": "日期",
        "operator": "isGreater",
        "value": _exact(datetime.combine(start_day, datetime.min.time(), tzinfo=bj)),
    }, {
        "field_name": "日期",
        "operator": "isLess",
        "value": _exact(datetime.combine(
            now_bj.date() + timedelta(days=1), datetime.min.time(), tzinfo=bj,
        )),
    }]
    total = 0
    page_token: str | None = None
    for _ in range(MAX_PAGES):
        body: dict[str, Any] = {
            "page_size": PAGE_SIZE,
            "filter": {"conjunction": "and", "conditions": conds},
        }
        # page_token 必须放 URL query（放 body 会被飞书忽略，恒返第一页）
        params: dict[str, str] = {"field_name_type": "name"}
        if page_token:
            params["page_token"] = page_token
        resp = await http.post(
            f"{BASE_URL}/{app_token}/tables/{table_id}/records/search",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=body,
        )
        d = resp.json()
        if not isinstance(d, dict) or d.get("code", 0) != 0:
            return -1  # 过滤失败（如列名/类型不符），调用方标注
        data = d.get("data", {}) or {}
        resp_total = data.get("total")
        if isinstance(resp_total, int) and resp_total > 0 and not page_token:
            return resp_total  # 首页即带 total，免翻页
        total += len(data.get("items", []) or [])
        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data.get("page_token")
    return total


async def main() -> int:
    conn = store.get_connection("central_alarm", "alarm")
    if conn is None or not conn.enabled:
        print("[x] central_alarm/alarm 连接未配置或已停用，中止")
        return 2
    app_token = central_alarm_app_token()
    table_ids = central_alarm_table_ids()
    print(f"[i] app_token={app_token} whitelist_tables={len(table_ids)}")

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        name_map = await _fetch_table_names(http, token, app_token)

        print("\n== 1. 白名单表与 workshop/line 推导 ==")
        biz_tables: list[tuple[str, str]] = []
        for tid in table_ids:
            name = name_map.get(tid, "<表名未找到>")
            cfg = _is_config_table(name)
            workshop, line = derive_workshop_line(name)
            print(f"  {tid}  {name}  -> workshop={workshop} line={line}"
                  + ("  [配置表，排除]" if cfg else ""))
            if not cfg:
                biz_tables.append((tid, name))

        print("\n== 2. 字段同构性（list_fields）==")
        field_sig: dict[str, Counter] = {}
        per_table_fields: dict[str, set] = {}
        for tid, name in biz_tables:
            fields = await _list_fields(http, token, app_token, tid)
            sig = [(f.get("field_name", ""), f.get("type", "")) for f in fields]
            print(f"  {name}: {len(sig)} fields -> {sig}")
            per_table_fields[name] = {fname for fname, _ in sig}
            for fname, ftype in sig:
                field_sig.setdefault(fname, Counter())[ftype] += 1
        print("  -- 字段名 -> 类型分布（type 相同数 / 业务表数）--")
        n = len(biz_tables)
        for fname, counter in sorted(field_sig.items()):
            mark = "OK" if sum(counter.values()) == n else "!!"
            print(f"  [{mark}] {fname}: {dict(counter)} / {n}")
        base = None
        for name, fs in per_table_fields.items():
            if base is None:
                base = fs
            elif fs != base:
                print(f"  [!!] {name} 与首表字段差异: 多={fs - base} 少={base - fs}")

        print("\n== 3. 行数量级（全量分页计数 + 近30天窗口）==")
        grand_total, grand_window = 0, 0
        timings: list[float] = []
        for tid, name in biz_tables:
            cnt, elapsed, pages = await _count_all(http, token, app_token, tid)
            win = await _count_window(http, token, app_token, tid)
            timings.append(elapsed)
            grand_total += cnt
            win_s = str(win) if win >= 0 else "FILTER_FAIL"
            if win > 0:
                grand_window += win
            print(f"  {name}: total={cnt} last{WINDOW_DAYS}d={win_s}"
                  f" pages={pages} fetch={elapsed:.2f}s")

        print("\n== 4. 汇总 ==")
        print(f"  业务表数={len(biz_tables)} 总行数={grand_total}"
              f" 近{WINDOW_DAYS}天={grand_window}")
        print(f"  全量拉取串行耗时={sum(timings):.1f}s"
              f"（单表最大={max(timings):.2f}s）")
        print("  结论参考: API 直读若需 <2s，全量串行超限时须默认窗口/倒序提前终止")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
