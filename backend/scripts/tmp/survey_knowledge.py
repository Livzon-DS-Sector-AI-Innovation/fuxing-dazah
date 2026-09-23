"""knowledge 法规标准两表只读探针（直读改造前置盘点，批次二-4）。

只读，零写入。输出：
  1. collection/collection_env 两连接配置与 wiki->base 解析（共用 app_token 按
     table_id 区分）；
  2. 两表 list_fields 全字段盘点：handler 映射期望字段（KNOWLEDGE_BITABLE_TO_MODEL
     8 + 法规原件附件 + article_no 回写列 + 更新状态爬虫写列）；枚举字段
     （法规类别/法规状态）选项值 vs handler CATEGORY_CN_TO_EN / STATUS_CN_TO_EN
     脏值核对；创建日期公式列候选（query_latest_regulations created_at 语义依据）；
  3. 两表行数量级与全量拉取耗时（Q6 量级确认，阈值 3000；<2s TTL 缓存决策输入，
     key_risk_op 1585 行 4.9s 加缓存先例对照）；
  4. 关键字段原始值形态抽样（search 口径：日期 ms/选择/富文本/附件）；
  5. 口径基线：法规类别/法规状态 分布 vs 标准映射键脏值检查、article_no 非空行
     （回写覆盖面）、备注含「影响等级:」行（query_latest_regulations 过滤面）、
     颁布修订日期非空行（直读排序候选键）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_knowledge.py

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

# 两表同构：handler 期望字段全集（knowledge_bitable_handler.py
# KNOWLEDGE_BITABLE_TO_MODEL 8 + 附件 + 回写/爬虫写列）
EXPECTED_FIELDS = [
    "法律法规及标准名称", "法规类别", "颁布机关", "颁布修订日期",
    "实施日期", "法规状态", "核心要点总结", "备注",
    "法规原件", "article_no", "更新状态", "入库日期", "适用部门",
]
SELECT_OPTIONS_FIELDS = {"法规类别", "法规状态", "更新状态"}
# handler CATEGORY_CN_TO_EN 全集（枚举脏值核对基准）
CATEGORY_STANDARD = [
    "安全类", "建筑防火与消防", "特种设备", "特殊作业", "职业健康",
    "环境类", "化学品管理", "其他相关法规", "二职业健康类", "三环境保护类",
]
STATUS_STANDARD = ["现行有效", "现行有效(新)", "征求意见中", "即将实施"]
# 公式创建日期列候选（query_latest_regulations「最近 N 天」排序/过滤语义依据）
CREATED_AT_CANDIDATES = ["创建日期", "创建时间"]


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
                        table_id: str, label: str) -> list[dict[str, Any]]:
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
        if isinstance(opts, list) and fname in SELECT_OPTIONS_FIELDS:
            labels = [str(o.get("name", "")) for o in opts]
            extra = f"  options={labels}"
        print(f"    - {fname} (type={ftype}){extra}")

    absent = [f for f in EXPECTED_FIELDS if f not in present]
    if absent:
        print(f"  [!!] 期望但表缺失: {absent}")
    else:
        print(f"  [OK] 期望 {len(EXPECTED_FIELDS)} 字段全部在表")
    created_candidates = [c for c in CREATED_AT_CANDIDATES if c in present]
    print(f"  创建日期公式列候选: {created_candidates or '无（直读 created_at 恒 None，需拍板排序依据）'}")

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


def _nonempty(items: list[dict[str, Any]], fname: str) -> int:
    return sum(1 for it in items
               if (it.get("fields", {}) or {}).get(fname) not in (None, "", []))


def _notes_with_impact(items: list[dict[str, Any]]) -> int:
    return sum(1 for it in items
               if "影响等级:" in str((it.get("fields", {}) or {}).get("备注") or ""))


async def main() -> int:
    conns: list[tuple[str, Any]] = []
    for kind in ("collection", "collection_env"):
        conn = store.get_connection("knowledge", kind)
        if conn is None or conn.status == "disabled":
            print(f"[x] knowledge/{kind} 连接未配置或已停用，中止")
            return 2
        conns.append((kind, conn))

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. 连接与 wiki->base 解析 ==")
        kind0, conn0 = conns[0]
        canonical = await resolve_canonical_app_token(http, token, conn0.app_token)
        mark = "wiki->base" if canonical != conn0.app_token else "direct(base token)"
        print(f"  {kind0}: {conn0.app_token} -> {canonical} [{mark}]"
              f" table_id={conn0.table_id}")
        same_base = conns[1][1].app_token == conn0.app_token
        print(f"  {conns[1][0]}: app_token 同 Base={same_base}"
              f" table_id={conns[1][1].table_id}")
        app_token = canonical

        labels = {"collection": "安全法规标准", "collection_env": "环保法规标准"}
        results: dict[str, list[dict[str, Any]]] = {}
        for i, (kind, conn) in enumerate(conns, start=2):
            results[kind] = await _survey_table(
                http, token, app_token, conn.table_id,
                f"{i}. {labels[kind]}（{kind}）")

        for kind, items in results.items():
            print(f"\n== {labels[kind]} 形态抽样与口径基线 ==")
            _sample_shapes(items, [
                "法律法规及标准名称", "法规类别", "颁布机关", "颁布修订日期",
                "实施日期", "法规状态", "核心要点总结", "备注", "法规原件",
                "article_no", "更新状态", "入库日期", "适用部门",
            ])
            for fname, standard in (
                ("法规类别", CATEGORY_STANDARD), ("法规状态", STATUS_STANDARD),
            ):
                dist = _distribution(items, fname)
                dirty = sorted(set(dist) - set(standard) - {"<空>"})
                print(f"    {fname} 分布={dist}")
                print(f"    {fname} 非标准选项值={dirty or '无'}")
            print(f"    article_no 非空行={_nonempty(items, 'article_no')}"
                  f"（回写覆盖面；空=手动建行未被事件同步或回写跳过）")
            print(f"    备注含「影响等级:」行={_notes_with_impact(items)}"
                  f"（query_latest_regulations impact_level 过滤面）")
            print(f"    颁布修订日期非空行={_nonempty(items, '颁布修订日期')}"
                  f"（直读排序候选键）")
            print(f"    入库日期非空行={_nonempty(items, '入库日期')}"
                  f"（created_at 直读等价键候选）")
            recent = sum(
                1 for it in items
                if isinstance((it.get("fields", {}) or {}).get("入库日期"), (int, float))
                and (it["fields"]["入库日期"] > 0)
            )
            print(f"    入库日期为正时间戳行={recent}")
            print(f"    法规原件非空行={_nonempty(items, '法规原件')}")
            print(f"    适用部门非空行={_nonempty(items, '适用部门')}"
                  f"（handler 未映射列，两侧一致不展示）")

        print("\n== 7. 汇总 ==")
        print(f"  安全法规={len(results['collection'])} 行"
              f" 环保法规={len(results['collection_env'])} 行"
              f" 同 Base={same_base}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
