"""危化品库存总表单表只读探针（直读改造前置盘点，批次一-3，照 survey_cert.py 模板）。

默认只读，零写入。输出：
  1. inventory 单连接配置与 wiki->base token 解析；
  2. list_fields 字段名/类型 + select/multi-select 选项，与 handler 枚举映射核对
     （_DEPT/_UNIT/_HAZARD/_RISK_FLAG/_ALERT_TYPE 五组标签，映射漂移会打断直读侧枚举化）；
  3. 全量行数（首页 total 免翻页）+ 全量拉取耗时（Q6 量级确认，阈值 3000 行）；
  4. 关键字段原始值形态抽样（select/富文本/多选/数字/日期 直读解析要对上）；
  5. 【默认关】写后可见性延迟（--write-test）：对 1 条记录做「同值无变化 batch_update」
     后轮询 search 观察可见耗时 + get_record 是否 1254607。同值写不改动任何数据，
     但会产生一次与每日 19:30 写入同类的平台事件（生产侧会做一次幂等重算）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_chemical_inventory.py
    .venv/Scripts/python.exe scripts/tmp/survey_chemical_inventory.py --write-test

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
from app.modules.safety.feishu.chemical_inventory_bitable_handler import (  # noqa: E402
    _ALERT_TYPE_LABEL_TO_ENUM,
    _DEPT_LABEL_TO_ENUM,
    _HAZARD_LABEL_TO_ENUM,
    _RISK_FLAG_LABEL_TO_ENUM,
    _UNIT_LABEL_TO_ENUM,
)
from app.modules.safety.feishu.client import get_safety_tenant_token  # noqa: E402
from app.modules.safety.feishu.subscribe import (  # noqa: E402
    resolve_canonical_app_token,
)

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50
Q6_THRESHOLD = 3000

# registry INVENTORY_BITABLE_TO_MODEL 期望的字段名（缺列标注）
EXPECTED_FIELDS = {
    "部门", "存放部位", "物料名称", "包装规格", "库存数量", "单位",
    "现场物料总量(T)", "库存上限", "上限单位", "危险性", "品类",
    "最后更新时间", "备注", "风险标记", "风险说明",
}

# 字段名 → (枚举映射名, 标签集合)：select 选项须覆盖标签（表里可多、映射不可缺）
EXPECTED_OPTIONS: dict[str, tuple[str, set[str]]] = {
    "部门": ("_DEPT", set(_DEPT_LABEL_TO_ENUM)),
    "单位": ("_UNIT", set(_UNIT_LABEL_TO_ENUM)),
    "危险性": ("_HAZARD", set(_HAZARD_LABEL_TO_ENUM)),
    "风险标记": ("_RISK_FLAG", set(_RISK_FLAG_LABEL_TO_ENUM)),
    "风险说明": ("_ALERT_TYPE", set(_ALERT_TYPE_LABEL_TO_ENUM)),
}

# 抽样观察原始值形态的字段
SAMPLE_FIELDS = [
    "部门", "存放部位", "物料名称", "包装规格", "库存数量", "单位",
    "现场物料总量(T)", "库存上限", "危险性", "品类",
    "最后更新时间", "风险标记", "风险说明",
]

def _shape(v: Any) -> str:
    """值形态摘要：类型 + （容器时）元素类型。"""
    if v is None:
        return "null"
    if isinstance(v, list):
        inner = _shape(v[0]) if v else "empty"
        return f"list<{inner}>x{len(v)}"
    if isinstance(v, dict):
        return f"dict keys={sorted(v)[:4]}"
    return type(v).__name__


def _brief(v: Any, limit: int = 40) -> str:
    s = repr(v)
    return s if len(s) <= limit else s[:limit] + "…"


async def _get_json(http: httpx.AsyncClient, token: str, url: str,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = await http.get(url, headers={"Authorization": f"Bearer {token}"},
                          params=params)
    d = resp.json()
    if not isinstance(d, dict) or d.get("code", 0) != 0:
        raise RuntimeError(f"API failed: code={d.get('code') if isinstance(d, dict) else '?'}"
                           f" msg={d.get('msg') if isinstance(d, dict) else '?'} url={url}")
    return d.get("data", {}) or {}


async def _search(http: httpx.AsyncClient, token: str, app_token: str,
                  table_id: str, body: dict[str, Any]) -> dict[str, Any]:
    # page_token 必须放 URL query（放 body 会被飞书忽略，恒返第一页）
    params: dict[str, str] = {"field_name_type": "name"}
    if body.get("page_token"):
        params["page_token"] = body.pop("page_token")
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


async def _get_record(http: httpx.AsyncClient, token: str, app_token: str,
                      table_id: str, record_id: str) -> tuple[int, Any]:
    """单条 get_record（坑位：4-5s 慢 + 1254607 Data not ready 高发，观测用）。"""
    t0 = time.perf_counter()
    resp = await http.get(
        f"{BASE_URL}/{app_token}/tables/{table_id}/records/{record_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    elapsed = time.perf_counter() - t0
    d = resp.json()
    return elapsed, d


async def main(write_test: bool) -> int:
    conn = store.get_connection("chemical_inventory", "inventory")
    if conn is None or conn.status == "disabled":
        print("[x] chemical_inventory/inventory 连接未配置或已停用，中止")
        return 2

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. 连接与 wiki->base 解析 ==")
        canonical = await resolve_canonical_app_token(http, token, conn.app_token)
        mark = "wiki->base" if canonical != conn.app_token else "direct(base token)"
        print(f"  inventory: app_token={conn.app_token} -> {canonical} [{mark}]"
              f" table_id={conn.table_id}")
        app_token, table_id = canonical, conn.table_id

        print("\n== 2. 表名与字段盘点（list_fields + 选项 vs 枚举映射）==")
        names = await _get_json(http, token, f"{BASE_URL}/{app_token}/tables")
        tname = next((i.get("name", "") for i in (names.get("items", []) or [])
                      if i.get("table_id") == table_id), "<表名未找到>")
        fields = await _get_json(http, token,
                                 f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
        items = list(fields.get("items", []) or [])
        print(f"  {tname}: {len(items)} fields")
        present: set[str] = set()
        options_by_field: dict[str, list[str]] = {}
        for f in items:
            fname, ftype = f.get("field_name", ""), f.get("type", "")
            present.add(fname)
            extra = ""
            prop = f.get("property") or {}
            opts = prop.get("options")
            if isinstance(opts, list):
                labels = [str(o.get("name", "")) for o in opts]
                options_by_field[fname] = labels
                extra = f"  options={labels}"
            print(f"    - {fname} (type={ftype}){extra}")
        absent = EXPECTED_FIELDS - present
        if absent:
            print(f"  [!!] registry 期望但表缺失: {sorted(absent)}")
        else:
            print("  [OK] registry 期望字段全部在表")
        for fname, (map_name, labels) in EXPECTED_OPTIONS.items():
            if fname not in options_by_field:
                print(f"  [??] {fname}: 无 select 选项 property（type 或非单/多选）")
                continue
            missing = labels - set(options_by_field[fname])
            if missing:
                print(f"  [!!] {fname}: 映射 {map_name} 有而表选项缺: {sorted(missing)}")
            else:
                extra_opts = set(options_by_field[fname]) - labels
                note = f"（表多出: {sorted(extra_opts)}）" if extra_opts else ""
                print(f"  [OK] {fname}: {map_name} 标签全覆盖{note}")

        print("\n== 3. 行数量级与全量拉取耗时 ==")
        t0 = time.perf_counter()
        total, fetched, pages = 0, 0, 0
        all_items: list[dict[str, Any]] = []
        page_token: str | None = None
        for _ in range(MAX_PAGES):
            data = await _search(http, token, app_token, table_id,
                                 {"page_size": PAGE_SIZE, "page_token": page_token})
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
        print(f"  total={total} fetched={fetched} pages={pages} fetch={elapsed:.2f}s"
              + ("" if total == fetched else "  [!!] total!=fetched"))
        verdict = ("全量（<=3000 行，Q6=A 成立）" if fetched <= Q6_THRESHOLD
                   else ">3000 行，需复核 Q6")
        print(f"  Q6 量级: {verdict}")

        print("\n== 4. 关键字段原始值形态抽样 ==")
        for fname in SAMPLE_FIELDS:
            shapes: dict[str, int] = {}
            sample: Any = None
            for item in all_items:
                v = (item.get("fields", {}) or {}).get(fname)
                if v is None or v == "" or v == []:
                    continue
                k = _shape(v)
                shapes[k] = shapes.get(k, 0) + 1
                if sample is None:
                    sample = v
            if not shapes:
                print(f"    {fname}: <全表空>")
            else:
                top = ", ".join(f"{k} x{n}" for k, n in sorted(shapes.items(),
                                                               key=lambda x: -x[1]))
                print(f"    {fname}: {top}  例: {_brief(sample)}")
        lm_keys = sorted(k for k in all_items[0] if k not in ("fields", "record_id")) \
            if all_items else []
        print(f"    [record 层键] {lm_keys}")

        # 口径基线（供 ticket 08 比对与镜像回填核对）
        def _txt(item: dict[str, Any], fname: str) -> str:
            v = (item.get("fields", {}) or {}).get(fname)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return str(v[0].get("text") or "")
            return str(v) if v is not None else ""
        flag_cnt: dict[str, int] = {}
        unmapped_unit = 0
        no_hazard = 0
        for item in all_items:
            f = item.get("fields", {}) or {}
            flag_cnt[_txt(item, "风险标记")] = flag_cnt.get(_txt(item, "风险标记"), 0) + 1
            u = _txt(item, "单位")
            if u and u not in _UNIT_LABEL_TO_ENUM:
                unmapped_unit += 1
            if not f.get("危险性"):
                no_hazard += 1
        print(f"    [基线] 风险标记分布={flag_cnt}"
              f" 单位未映射标签行数={unmapped_unit} 危险性为空行数={no_hazard}")

        if not write_test:
            print("\n== 5. 写后可见性延迟 ==（--write-test 未开，跳过；零写入）")
            print("  汇总: 见上。")
            return 0

        print("\n== 5. 写后可见性延迟（--write-test：同值无变化 batch_update 1 条）==")
        target = None
        for item in sorted(all_items, key=lambda x: x.get("record_id", "")):
            qty = (item.get("fields", {}) or {}).get("库存数量")
            if isinstance(qty, (int, float)):
                target = item
                break
        if target is None:
            print("  [x] 未找到 库存数量 为数值的记录，跳过写测")
            return 0
        rid = target.get("record_id", "")
        qty = target["fields"]["库存数量"]
        name = _txt(target, "物料名称")
        print(f"  目标 record_id={rid} 物料名称={name!r} 库存数量={qty}")
        print("  （search 响应无 last_modified_time，口径=同值写后读回一致 + get_record 1254607 观测）")

        # 同值写：只写 库存数量=原值（不改动任何数据；与每日 19:30 写入同类事件）
        w0 = time.perf_counter()
        resp = await http.post(
            f"{BASE_URL}/{app_token}/tables/{table_id}/records/batch_update",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"records": [{"record_id": rid, "fields": {"库存数量": qty}}]},
        )
        wd = resp.json()
        if not isinstance(wd, dict) or wd.get("code", 0) != 0:
            print(f"  [x] batch_update 失败: code={wd.get('code')} msg={wd.get('msg')}")
            return 3
        w_done = time.perf_counter() - w0
        print(f"  同值 batch_update 返回 code=0（{w_done:.2f}s），立即读回")

        # t≈0 全量 search：读回一致 + filter 物料名称 下推双验
        s0 = time.perf_counter()
        data = await _search(http, token, app_token, table_id, {"page_size": PAGE_SIZE})
        s_elapsed = time.perf_counter() - s0
        full_items = list(data.get("items", []) or [])
        match = next((i for i in full_items if i.get("record_id") == rid), None)
        same = match is not None and (match.get("fields", {}) or {}).get("库存数量") == qty
        print(f"  [search 全量 t≈0] {s_elapsed:.2f}s 命中={match is not None}"
              f" 值一致={same}（{'[OK]' if same else '[!!]'}）")

        f0 = time.perf_counter()
        data = await _search(http, token, app_token, table_id, {"page_size": PAGE_SIZE, "filter": {
            "conjunction": "and",
            "conditions": [{"field_name": "物料名称", "operator": "is", "value": [name]}],
        }})
        f_hits = list(data.get("items", []) or [])
        print(f"  [search filter 物料名称 下推] {time.perf_counter() - f0:.2f}s"
              f" 命中={len(f_hits)} 条含目标={any(i.get('record_id') == rid for i in f_hits)}")

        # 2s 后再读一次 + get_record 观测（1254607 Data not ready 高发即写后读坑）
        await asyncio.sleep(2.0)
        g_elapsed, gd = await _get_record(http, token, app_token, table_id, rid)
        code = gd.get("code") if isinstance(gd, dict) else "?"
        note = "Data not ready（写后 get_record 不可靠，印证必须走 search）" if code == 1254607 else ""
        print(f"  [get_record t+2s] {g_elapsed:.2f}s code={code} {note}")

        print("\n== 6. 汇总 ==")
        print(f"  行数={fetched} 全量拉取={elapsed:.2f}s 字段={len(items)}"
              f" 缺失={sorted(EXPECTED_FIELDS - present) or '无'}")
        print(f"  写后读回: search t≈0 值一致={same}（{s_elapsed:.2f}s）"
              f" get_record code={code}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main("--write-test" in sys.argv)))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
