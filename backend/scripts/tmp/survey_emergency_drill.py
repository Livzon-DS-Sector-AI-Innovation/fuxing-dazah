"""emergency_drill 应急演练两表只读探针（直读改造前置盘点，批次二-3）。

只读，零写入。输出：
  1. main/collection 两连接配置与 wiki->base 解析；
  2. 两表 list_fields 全字段盘点：handler 映射期望字段（BITABLE_TO_MODEL 17 +
     PERSON 3 + ATTACHMENT 6 + 计划时间参考）与采集表 4 Bitable 字段 +
     解析状态/解析结果回写列是否在表；枚举字段（演练类型/状态/解析状态）选项值；
  3. 两表行数量级与全量拉取耗时（Q6 量级确认，阈值 3000；<2s TTL 缓存决策输入）；
  4. 关键字段原始值形态抽样（search 口径：日期 ms/多选/person/附件/rich text）；
  5. 口径基线：主表 状态/演练类型 分布 vs 标准 5 类脏值检查、execution_time
     非空行（stage=execution 面）、创建日期公式列存在性（排序 created_at 依据）、
     演练评估表（AI）/演练记录表 非空行（评估触发面/派生态）；
     采集表 解析状态 分布、创建日期公式列存在性。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_emergency_drill.py

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

# 主表 handler 期望字段全集（emergency_drill_bitable_handler.py）
MAIN_MAPPED_FIELDS = [
    "计划时间", "演练类型", "演练内容", "组织人", "演练部门",
    "组织人 (人员 )", "参演人员", "配合部门", "课时", "备  注",
    "提醒人员", "实施时间", "演练问题", "整改时间", "整改责任人", "确认人", "状态",
]
MAIN_PERSON_FIELDS = ["提醒人员 (人员 )", "整改责任人", "确认人"]
MAIN_ATTACHMENT_FIELDS = [
    "演练方案（AI）", "演练方案（定稿）", "签到表",
    "演练评估表", "演练记录表", "演练评估表（AI）",
]
MAIN_DATE_EXTRA = ["计划时间参考"]
# 采集表期望字段（emergency_drill_collection_handler.py 提取 + 回写列）
COLL_BITABLE_FIELDS = ["日期", "演练计划附件", "人员", "部门"]
COLL_WRITEBACK_FIELDS = ["解析状态", "解析结果"]
# 公式创建日期列候选（排序 created_at 依据，contractor 同款）
CREATED_AT_CANDIDATES = ["创建日期", "创建时间"]

SELECT_OPTIONS_FIELDS = {
    "演练类型", "状态", "解析状态",
}
DRILL_TYPE_STANDARD = [
    "应急疏散演练", "现场岗位处置", "专项应急演练", "综合应急演练", "消防器材培训",
]
STATUS_STANDARD = ["已完成", "未完成"]


def _txt(v: Any) -> str:
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return str(v[0].get("text") or "")
    if isinstance(v, dict):
        return str(v.get("text") or "")
    return str(v) if v is not None else ""


async def _get_json(http: httpx.AsyncClient, token: str, url: str,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = await http.get(url, headers={"Authorization": f"Bearer {token}"},
                          params=params)
    d = resp.json()
    if not isinstance(d, dict) or d.get("code", 0) != 0:
        raise RuntimeError(f"API failed: code={d.get('code') if isinstance(d, dict) else '?'}"
                           f" msg={d.get('msg') if isinstance(d, dict) else '?'} url={url}")
    return d.get("data", {}) or {}


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


async def _fetch_all(http: httpx.AsyncClient, token: str, app_token: str,
                     table_id: str) -> tuple[int, int, int, float, list[dict[str, Any]]]:
    t0 = time.perf_counter()
    total, fetched, pages = 0, 0, 0
    all_items: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(MAX_PAGES):
        data = await _search_page(http, token, app_token, table_id, page_token)
        pages += 1
        resp_total = data.get("total")
        if isinstance(resp_total, int) and page_token is None:
            total = resp_total  # 首页 total 免翻页计数
        chunk = list(data.get("items", []) or [])
        all_items.extend(chunk)
        fetched += len(chunk)
        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data.get("page_token")
    elapsed = time.perf_counter() - t0
    return total, fetched, pages, elapsed, all_items


async def _survey_table(http: httpx.AsyncClient, token: str, app_token: str,
                        table_id: str, label: str,
                        expected: list[str], select_fields: set[str]) -> list[dict[str, Any]]:
    print(f"\n== {label}: 字段盘点 ==")
    names = await _get_json(http, token, f"{BASE_URL}/{app_token}/tables")
    tname = next((i.get("name", "") for i in (names.get("items", []) or [])
                  if i.get("table_id") == table_id), "<表名未找到>")
    fields = await _get_json(http, token,
                             f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
    items = list(fields.get("items", []) or [])
    print(f"  {tname}: {len(items)} fields")
    present: set[str] = set()
    for f in items:
        fname, ftype = f.get("field_name", ""), f.get("type", "")
        present.add(fname)
        extra = ""
        prop = f.get("property") or {}
        opts = prop.get("options")
        if isinstance(opts, list) and fname in select_fields:
            labels = [str(o.get("name", "")) for o in opts]
            extra = f"  options={labels}"
        print(f"    - {fname} (type={ftype}){extra}")

    absent = [f for f in expected if f not in present]
    if absent:
        print(f"  [!!] 期望但表缺失: {absent}")
    else:
        print(f"  [OK] 期望 {len(expected)} 字段全部在表")
    created_candidates = [c for c in CREATED_AT_CANDIDATES if c in present]
    print(f"  创建日期公式列候选: {created_candidates or '无（直读 created_at 恒 None，需拍板排序依据）'}")
    print(f"  解析状态/解析结果回写列在表: "
          f"{[c for c in COLL_WRITEBACK_FIELDS if c in present]}")

    total, fetched, pages, elapsed, all_items = await _fetch_all(
        http, token, app_token, table_id)
    verdict = ("全量（<=3000 行，Q6=A 成立）" if fetched <= Q6_THRESHOLD
               else ">3000 行，需复核 Q6")
    print(f"  行数: total={total} fetched={fetched} pages={pages} fetch={elapsed:.2f}s"
          f"  [{verdict}]" + ("" if total == fetched else "  [!!] total!=fetched"))
    return all_items


def _shape_of(v: Any) -> str:
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return "list<dict>"
        if v and isinstance(v[0], str):
            return "list<str>"
        return "list"
    return type(v).__name__


def _sample_shapes(all_items: list[dict[str, Any]], fnames: list[str]) -> None:
    for fname in fnames:
        shapes: dict[str, int] = {}
        sample: Any = None
        for item in all_items:
            v = (item.get("fields", {}) or {}).get(fname)
            if v is None or v == "" or v == []:
                continue
            k = _shape_of(v)
            shapes[k] = shapes.get(k, 0) + 1
            if sample is None:
                sample = v
        if not shapes:
            print(f"    {fname}: <全表空>")
        else:
            top = ", ".join(f"{k} x{n}" for k, n in sorted(shapes.items(),
                                                           key=lambda x: -x[1]))
            print(f"    {fname}: {top}  例: {repr(sample)[:80]}")


def _distribution(all_items: list[dict[str, Any]], fname: str) -> dict[str, int]:
    dist: dict[str, int] = {}
    for item in all_items:
        v = _txt((item.get("fields", {}) or {}).get(fname))
        dist[v or "<空>"] = dist.get(v or "<空>", 0) + 1
    return dist


async def main() -> int:
    main_conn = store.get_connection("emergency_drill", "main")
    coll_conn = store.get_connection("emergency_drill", "collection")
    if main_conn is None or main_conn.status == "disabled":
        print("[x] emergency_drill/main 连接未配置或已停用，中止")
        return 2
    if coll_conn is None or coll_conn.status == "disabled":
        print("[x] emergency_drill/collection 连接未配置或已停用，中止")
        return 2

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. 连接与 wiki->base 解析 ==")
        main_canonical = await resolve_canonical_app_token(http, token, main_conn.app_token)
        mark_main = "wiki->base" if main_canonical != main_conn.app_token else "direct(base token)"
        print(f"  main: {main_conn.app_token} -> {main_canonical} [{mark_main}]"
              f" table_id={main_conn.table_id}")
        same_base = coll_conn.app_token == main_conn.app_token
        print(f"  collection: app_token 同 Base={same_base} table_id={coll_conn.table_id}")
        app_token = main_canonical

        main_items = await _survey_table(
            http, token, app_token, main_conn.table_id, "2. 主表（演练计划统计）",
            MAIN_MAPPED_FIELDS + MAIN_PERSON_FIELDS + MAIN_ATTACHMENT_FIELDS
            + MAIN_DATE_EXTRA,
            SELECT_OPTIONS_FIELDS)

        print("\n== 3. 主表关键字段形态抽样 ==")
        _sample_shapes(main_items, [
            "计划时间", "实施时间", "计划时间参考", "演练类型", "演练部门",
            "参演人员", "配合部门", "组织人 (人员 )", "整改责任人", "状态",
            "演练方案（AI）", "签到表", "演练记录表", "演练评估表（AI）", "演练内容",
        ])

        print("\n== 4. 主表口径基线 ==")
        for fname, standard in (("演练类型", DRILL_TYPE_STANDARD), ("状态", STATUS_STANDARD)):
            dist = _distribution(main_items, fname)
            dirty = sorted(set(dist) - set(standard) - {"<空>"})
            print(f"    {fname} 分布={dist}")
            print(f"    {fname} 非标准选项值={dirty or '无'}")
        exec_nonempty = sum(
            1 for item in main_items
            if (item.get("fields", {}) or {}).get("实施时间") is not None)
        eval_ai_filled = sum(
            1 for item in main_items
            if (item.get("fields", {}) or {}).get("演练评估表（AI）"))
        record_form = sum(
            1 for item in main_items
            if (item.get("fields", {}) or {}).get("演练记录表"))
        plan_ai = sum(
            1 for item in main_items
            if (item.get("fields", {}) or {}).get("演练方案（AI）"))
        print(f"    实施时间非空行（stage=execution 面）={exec_nonempty}")
        print(f"    演练评估表（AI）非空行={eval_ai_filled}（派生态：评估已生成）")
        print(f"    演练记录表非空行={record_form}（评估触发面）")
        print(f"    演练方案（AI）非空行={plan_ai}")

        coll_items = await _survey_table(
            http, token, app_token, coll_conn.table_id, "5. 采集表（演练计划收录）",
            COLL_BITABLE_FIELDS + COLL_WRITEBACK_FIELDS,
            SELECT_OPTIONS_FIELDS)

        print("\n== 6. 采集表形态抽样与基线 ==")
        _sample_shapes(coll_items, ["日期", "演练计划附件", "人员", "部门", "解析状态", "解析结果"])
        print(f"    解析状态 分布={_distribution(coll_items, '解析状态')}")
        parsed_back = sum(
            1 for item in coll_items if _txt((item.get("fields", {}) or {}).get("解析状态")))
        print(f"    解析状态非空行={parsed_back}（回写面；pending/failed 仅在 PG，"
              f"直读派生只含 已解析/空 两态）")

        print("\n== 7. 汇总 ==")
        print(f"  主表行数={len(main_items)} 采集表行数={len(coll_items)}"
              f" 同 Base={same_base}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
