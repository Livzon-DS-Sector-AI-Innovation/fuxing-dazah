"""contractor_admission 相关方准入表只读探针（直读改造前置盘点，批次二-2）。

只读，零写入。输出：
  1. admission 单连接配置与 wiki->base 解析；
  2. list_fields 全字段盘点：map_fields 实际读取的 22 个字段 + AI 回写 3 列
     （AI审核结论/AI审核报告/AI不符合项，§4.5 证实）+ 4 个公式字段；
     枚举字段（相关方类型/提交状态/培训状态）与 AI 回写列的选项值盘点；
  3. 全量行数（首页 total 免翻页）+ 全量拉取耗时（Q6 量级确认，阈值 3000）；
  4. 关键字段原始值形态抽样（附件含 url?/Person/Select/ms 日期/公式创建日期）；
  5. 口径基线：AI审核结论已回填行数、协议附件挂载行数（=自动审核触发面）、
     相关方类型空行（三选一 fallback 路径）、AI不符合项值域 vs 插件 4 类标准值、
     提交状态/培训状态分布（脏选项检查）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_contractor_admission.py

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

# map_fields 实际读取的字段全集（feishu/contractor_admission_bitable.py）
MAPPED_FIELDS = [
    "作业单位名称", "相关方类型", "承包商负责人", "承包商负责人联系电话",
    "对接人员", "入厂日期", "开始日期", "结束日期", "材料失效日期",
    "实际提交日期", "实际完成日期", "提交状态", "培训状态", "备注",
    "承包商安全管理协议", "合作类安全管理协议", "劳务派遣安全管理协议",
    "企业营业执照", "现场作业保险凭证", "承包商考核细则",
    "员工证明盖章文件", "现场负责人盖章文件",
]
# AI 回写 3 列（service._writeback_review）
WRITEBACK_FIELDS = ["AI审核结论", "AI审核报告", "AI不符合项"]
# 公式字段（map_fields 不映射）
FORMULA_FIELDS = ["补交截止日期", "是否延期", "材料完整度", "创建日期"]
SELECT_OPTIONS_FIELDS = ["相关方类型", "提交状态", "培训状态",
                         "AI审核结论", "AI不符合项"]
# 插件 _CATEGORY_PREFIX_MAP 的 4 类标准值（写回 AI不符合项 的合法值域）
PLUGIN_DEFECT_VALUES = [
    "安全管理协议-A基础信息类", "安全管理协议-B有效期类",
    "安全管理协议-C签章类", "安全管理协议-D骑缝章类",
]
# 结论三标准值
PLUGIN_CONCLUSION_VALUES = ["审核通过", "需补充完善", "审核不通过"]


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
    conn = store.get_connection("contractor_admission", "admission")
    if conn is None or conn.status == "disabled":
        print("[x] contractor_admission/admission 连接未配置或已停用，中止")
        return 2

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. 连接与 wiki->base 解析 ==")
        canonical = await resolve_canonical_app_token(http, token, conn.app_token)
        mark = "wiki->base" if canonical != conn.app_token else "direct(base token)"
        print(f"  admission: app_token={conn.app_token} -> {canonical} [{mark}]"
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
        field_types: dict[str, int] = {}
        for f in items:
            fname, ftype = f.get("field_name", ""), f.get("type", "")
            present.add(fname)
            field_types[fname] = int(ftype) if ftype else 0
            extra = ""
            prop = f.get("property") or {}
            opts = prop.get("options")
            if isinstance(opts, list) and fname in SELECT_OPTIONS_FIELDS:
                labels = [str(o.get("name", "")) for o in opts]
                extra = f"  options={labels}"
            print(f"    - {fname} (type={ftype}){extra}")

        absent = [f for f in MAPPED_FIELDS + WRITEBACK_FIELDS if f not in present]
        if absent:
            print(f"  [!!] map_fields/回写期望但表缺失: {absent}")
        else:
            print(f"  [OK] 映射期望 {len(MAPPED_FIELDS)} + 回写 {len(WRITEBACK_FIELDS)}"
                  f" 字段全部在表")
        formula_present = [f for f in FORMULA_FIELDS if f in present]
        print(f"  公式字段在表: {formula_present}（缺: "
              f"{[f for f in FORMULA_FIELDS if f not in present]}）")

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
        for fname in ("相关方类型", "对接人员", "入厂日期", "提交状态",
                      "承包商安全管理协议", "企业营业执照", "创建日期",
                      "AI审核结论", "AI不符合项"):
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
                print(f"    {fname}: {top}  例: {repr(sample)[:80]}")

        print("\n== 5. 口径基线 ==")
        # 枚举分布与空行
        for fname in ("相关方类型", "提交状态", "培训状态", "AI审核结论"):
            dist: dict[str, int] = {}
            for item in all_items:
                v = _txt((item.get("fields", {}) or {}).get(fname))
                dist[v or "<空>"] = dist.get(v or "<空>", 0) + 1
            print(f"    {fname} 分布={dist}")
        # 协议挂载面（自动审核触发面）：三协议字段任一非空
        agreement_attached = 0
        party_empty = 0
        for item in all_items:
            f = item.get("fields", {}) or {}
            has_agreement = any(
                f.get(n) for n in ("承包商安全管理协议", "合作类安全管理协议",
                                   "劳务派遣安全管理协议")
            )
            if has_agreement:
                agreement_attached += 1
            if not _txt(f.get("相关方类型")):
                party_empty += 1
        print(f"    协议附件挂载行（=自动审核触发面）={agreement_attached}")
        print(f"    相关方类型空行（走 fallback 三选一）={party_empty}")
        # AI不符合项 值域 vs 插件标准值（list 值逐项收集）
        defect_values: dict[str, int] = {}
        for item in all_items:
            v = (item.get("fields", {}) or {}).get("AI不符合项")
            vals = v if isinstance(v, list) else ([v] if v else [])
            for x in vals:
                s = _txt(x)
                defect_values[s] = defect_values.get(s, 0) + 1
        nonstandard = sorted(set(defect_values) - set(PLUGIN_DEFECT_VALUES))
        print(f"    AI不符合项 值域={defect_values}")
        print(f"    非插件 4 类标准值的选项/取值={nonstandard or '无'}")
        # 回写报告列长度样本（回写列类型=文本）
        report_filled = sum(
            1 for item in all_items
            if _txt((item.get("fields", {}) or {}).get("AI审核报告"))
        )
        print(f"    AI审核报告 非空行={report_filled}")

        print("\n== 6. 汇总 ==")
        print(f"  行数={fetched} 全量拉取={elapsed:.2f}s 字段={len(items)}"
              f" 缺失={absent or '无'} 协议挂载={agreement_attached}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
