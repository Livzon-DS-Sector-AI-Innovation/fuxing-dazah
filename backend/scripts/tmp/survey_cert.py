"""cert 持证台账 3 表只读探针（直读改造前置盘点，批次一-2，回填 Q6）。

只读，零写入。输出：
  1. cert 域 3 连接（special_op/guardian_a/guardian_b）配置与 wiki->base token 解析；
  2. 每表 list_fields 字段名/类型（与 cert_bitable.py 映射函数期望字段核对）；
  3. 每表全量行数（records/search 首页 total 免翻页）；
  4. 全量拉取 3 表串行总耗时与总行数（评估 Q6：全量 vs 增量预筛，阈值 3000 行）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_cert.py

退出码：0 成功；2 连接未配置或停用；3 拉取失败。
"""

from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

sys.path.insert(0, ".")

import httpx  # noqa: E402

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.client import get_safety_tenant_token  # noqa: E402
from app.modules.safety.feishu.subscribe import (  # noqa: E402
    resolve_canonical_app_token,
)

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50
Q6_THRESHOLD = 3000

# cert_bitable.py 两个映射函数期望的字段名（缺列标注）
EXPECTED: dict[str, set[str]] = {
    "special_op": {
        "姓名 (人员 )", "姓名", "部门", "作业类别", "项目",
        "证件编号", "再复审时间", "取证日期", "复审频次",
    },
    "guardian_a": {
        "姓名", "部门", "证件类型", "取证日期",
        "第一次复审截止日期", "第二次复审截止日期",
        "应换证日期", "已换证日期",
    },
    "guardian_b": {
        "姓名", "部门", "证件类型", "取证日期",
        "第一次复审截止日期", "第二次复审截止日期",
        "应换证日期", "已换证日期",
    },
}


async def _get_json(http: httpx.AsyncClient, token: str, url: str,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = await http.get(url, headers={"Authorization": f"Bearer {token}"},
                          params=params)
    d = resp.json()
    if not isinstance(d, dict) or d.get("code", 0) != 0:
        raise RuntimeError(f"API failed: code={d.get('code') if isinstance(d, dict) else '?'}"
                           f" msg={d.get('msg') if isinstance(d, dict) else '?'} url={url}")
    return d.get("data", {}) or {}


async def _list_fields(http: httpx.AsyncClient, token: str, app_token: str,
                       table_id: str) -> list[dict[str, Any]]:
    data = await _get_json(http, token,
                           f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
    return list(data.get("items", []) or [])


async def _search_page(http: httpx.AsyncClient, token: str, app_token: str,
                       table_id: str, page_token: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {"page_size": PAGE_SIZE}
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
        raise RuntimeError(
            f"records/search failed: code={d.get('code') if isinstance(d, dict) else '?'}"
            f" msg={d.get('msg') if isinstance(d, dict) else '?'} table={table_id}")
    return d.get("data", {}) or {}


async def main() -> int:
    conns = {v.kind: v for v in store.get_connections("cert")}
    kinds = ["special_op", "guardian_a", "guardian_b"]
    missing = [k for k in kinds if conns.get(k) is None or not conns[k].enabled]
    if missing:
        print(f"[x] cert 域连接未配置或已停用: {missing}，中止")
        return 2

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. cert 域连接与 wiki->base 解析 ==")
        resolved: dict[str, tuple[str, str]] = {}
        for kind in kinds:
            c = conns[kind]
            canonical = await resolve_canonical_app_token(http, token, c.app_token)
            mark = "wiki->base" if canonical != c.app_token else "direct"
            resolved[kind] = (canonical, c.table_id)
            print(f"  {kind}: app_token={c.app_token} -> {canonical} [{mark}]"
                  f" table_id={c.table_id}")

        print("\n== 2. 表名与字段同构性（list_fields）==")
        for kind in kinds:
            app_token, table_id = resolved[kind]
            names = await _get_json(
                http, token, f"{BASE_URL}/{app_token}/tables")
            tname = next((i.get("name", "") for i in (names.get("items", []) or [])
                          if i.get("table_id") == table_id), "<表名未找到>")
            fields = await _list_fields(http, token, app_token, table_id)
            sig = [(f.get("field_name", ""), f.get("type", "")) for f in fields]
            print(f"  {kind} [{tname}]: {len(sig)} fields")
            for fname, ftype in sig:
                print(f"    - {fname} (type={ftype})")
            absent = EXPECTED[kind] - {fname for fname, _ in sig}
            if absent:
                print(f"    [!!] 映射函数期望但表缺失: {sorted(absent)}")
            else:
                print("    [OK] 映射函数期望字段全部在表")

        print("\n== 3. 行数量级与全量拉取耗时 ==")
        grand_total = 0
        timings: list[float] = []
        per_table: dict[str, int] = {}
        for kind in kinds:
            app_token, table_id = resolved[kind]
            t0 = time.perf_counter()
            total, pages, fetched = 0, 0, 0
            page_token: str | None = None
            for _ in range(MAX_PAGES):
                data = await _search_page(http, token, app_token, table_id,
                                          page_token)
                pages += 1
                resp_total = data.get("total")
                if isinstance(resp_total, int) and page_token is None:
                    total = resp_total  # 首页 total 免翻页计数
                fetched += len(data.get("items", []) or [])
                if not data.get("has_more") or not data.get("page_token"):
                    break
                page_token = data.get("page_token")
            elapsed = time.perf_counter() - t0
            timings.append(elapsed)
            per_table[kind] = fetched
            grand_total += fetched
            print(f"  {kind}: total={total} fetched={fetched} pages={pages}"
                  f" fetch={elapsed:.2f}s"
                  + ("" if total == fetched else "  [!!] total!=fetched"))

        print("\n== 4. 汇总（回填 Q6）==")
        print(f"  3 表行数: {per_table}")
        print(f"  总行数={grand_total} 全量串行耗时={sum(timings):.1f}s"
              f"（单表最大={max(timings):.2f}s）")
        verdict = "A) 全量（<=3000 行，单轮分页可承受）" if grand_total <= Q6_THRESHOLD \
            else "B) 需评估增量窗口 + 到期月份预筛（>3000 行）"
        print(f"  Q6 倾向: {verdict}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
