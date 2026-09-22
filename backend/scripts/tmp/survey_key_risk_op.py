"""key_risk_op 每日关键风险预报表只读探针（直读改造前置盘点，批次二-1，回填 Q6）。

只读，零写入。输出：
  1. daily 单连接配置与 wiki->base 解析；
  2. list_fields 全字段盘点：基础 24 字段 + 多作业块 ×{1,2} + 三阶段现场确认
     （与 map_bitable_fields 实际读取的字段核对，registry default_mappings 是子集）；
  3. 全量行数（首页 total 免翻页）+ 全量拉取耗时（Q6 量级确认，阈值 3000 行）；
  4. 关键字段原始值形态抽样（Url/Person/SingleSelect/ms 时间戳）；
  5. 口径基线：申请状态分布（含「已删除」排除行数）、report_no 空行数、
     作业开始时间范围（直读窗口字段的健康度）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_key_risk_op.py

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

# map_bitable_fields 实际读取的字段全集（registry default_mappings 只是子集）
BASE_FIELDS = [
    "申请编号", "申请状态", "审批节点", "审批流程", "当前处理人",
    "发起人", "发起人部门", "发起时间", "完成时间",
    "部门", "区域", "作业内容", "作业开始时间", "作业结束时间", "时长", "备注",
    "个人防护", "准备措施", "操作注意事项", "应急措施",
    "现场作业监护人", "现场监护人", "部门安全员", "SourceID",
]
SUFFIX_FIELDS = ["部门", "区域", "作业内容", "作业时间段", "个人防护",
                 "准备措施", "操作注意事项", "应急措施", "现场作业监护人"]
PHASE_KEYS = ["作业前", "作业中", "作业后"]
PHASE_TEMPLATES = ["日期（{k}）", "现场确认（{k}）", "问题描述（{k}）"]


def _expected_fields() -> set[str]:
    out = set(BASE_FIELDS)
    for suffix in ("1", "2"):
        out |= {f + suffix for f in SUFFIX_FIELDS}
    for k in PHASE_KEYS:
        out |= {t.format(k=k) for t in PHASE_TEMPLATES}
    return out


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


async def main() -> int:
    conn = store.get_connection("key_risk_op", "daily")
    if conn is None or conn.status == "disabled":
        print("[x] key_risk_op/daily 连接未配置或已停用，中止")
        return 2

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. 连接与 wiki->base 解析 ==")
        canonical = await resolve_canonical_app_token(http, token, conn.app_token)
        mark = "wiki->base" if canonical != conn.app_token else "direct(base token)"
        print(f"  daily: app_token={conn.app_token} -> {canonical} [{mark}]"
              f" table_id={conn.table_id}")
        app_token, table_id = canonical, conn.table_id

        print("\n== 2. 表名与字段盘点 ==")
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
            if isinstance(opts, list) and fname in ("申请状态", "审批流程"):
                labels = [str(o.get("name", "")) for o in opts]
                extra = f"  options={labels}"
            print(f"    - {fname} (type={ftype}){extra}")
        expected = _expected_fields()
        absent = expected - present
        if absent:
            print(f"  [!!] map_bitable_fields 期望但表缺失: {sorted(absent)}")
        else:
            print(f"  [OK] 映射期望字段全部在表（{len(expected)} 个）")

        print("\n== 3. 行数量级与全量拉取耗时 ==")
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
        print(f"  total={total} fetched={fetched} pages={pages} fetch={elapsed:.2f}s"
              + ("" if total == fetched else "  [!!] total!=fetched"))
        verdict = ("全量（<=3000 行，Q6=A 成立）" if fetched <= Q6_THRESHOLD
                   else ">3000 行，需复核 Q6")
        print(f"  Q6 量级: {verdict}")

        print("\n== 4. 关键字段原始值形态抽样 ==")
        for fname in ("申请编号", "申请状态", "审批节点", "当前处理人", "发起人",
                      "发起时间", "部门", "作业开始时间", "时长", "部门1", "作业时间段1",
                      "日期（作业前）", "现场确认（作业前）", "SourceID"):
            shapes: dict[str, int] = {}
            sample: Any = None
            for item in all_items:
                v = (item.get("fields", {}) or {}).get(fname)
                if v is None or v == "" or v == []:
                    continue
                k = ("list<dict>" if isinstance(v, list) and v and isinstance(v[0], dict)
                     else type(v).__name__)
                shapes[k] = shapes.get(k, 0) + 1
                if sample is None:
                    sample = v
            if not shapes:
                print(f"    {fname}: <全表空>")
            else:
                top = ", ".join(f"{k} x{n}" for k, n in sorted(shapes.items(),
                                                               key=lambda x: -x[1]))
                print(f"    {fname}: {top}  例: {repr(sample)[:60]}")

        print("\n== 5. 口径基线 ==")
        status_cnt: dict[str, int] = {}
        deleted = 0
        no_report_no = 0
        start_times: list[int] = []
        for item in all_items:
            f = item.get("fields", {}) or {}
            st = _txt(f.get("申请状态"))
            status_cnt[st or "<空>"] = status_cnt.get(st or "<空>", 0) + 1
            if st == "已删除":
                deleted += 1
            if not _txt(f.get("申请编号")):
                no_report_no += 1
            ts = f.get("作业开始时间")
            if isinstance(ts, (int, float)):
                start_times.append(int(ts))
        print(f"    申请状态分布={status_cnt}")
        print(f"    已删除行(直读须排除)={deleted}  申请编号空行(须兜底 BT-xx)={no_report_no}")
        if start_times:
            from datetime import UTC, datetime

            lo = datetime.fromtimestamp(min(start_times) / 1000, tz=UTC)
            hi = datetime.fromtimestamp(max(start_times) / 1000, tz=UTC)
            print(f"    作业开始时间范围(UTC)={lo.isoformat()} ~ {hi.isoformat()}"
                  f"  空值行={fetched - len(start_times)}")

        print("\n== 6. 汇总 ==")
        print(f"  行数={fetched}（含已删除 {deleted}）全量拉取={elapsed:.2f}s"
              f" 字段={len(items)} 缺失={sorted(absent) or '无'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
