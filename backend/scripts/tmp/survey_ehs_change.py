"""ehs_change EHS 变更只读探针（直读改造前置盘点，批次三）。

只读，零写入。输出：
  1. 连接配置（ehs_change approval/acceptance 两表，共用 app_token）；
  2. list_fields 全字段盘点：与 feishu/ehs_change_bitable.py 两个 mapper
     读取的全部中文字段核对，多余列单列（含类型，公式列 type=2 标记）；
  3. 两表行数量级与全量拉取耗时（Q6 阈值 3000）+ created_time 覆盖
     （排序键候选，hazard_id 先例）；
  4. 关键字段原始值形态抽样（search 口径：Url 申请编号/人员/日期/AI结论单选/
     AI报告富文本——后续 reader 形态适配依据）；
  5. 口径基线：申请状态分布 vs _APPROVAL_STATUS_MAP、变更级别 vs _GRADE_MAP、
     AI 9+1 列非空行数（ai_review_status 直读可组装面）；
  6. PG 镜像基线（本域风险最高——重双向域判定）：
     source × feishu_table_id × fid 分布（API 创建行=直读结构性丢失面）、
     status 分布（状态机态 in_progress/commissioned/closed 是否出现在
     bitable 行=字段级丢失面）、actual_start/actual_completion 非空计数
     （状态机使用证据）、ai_review_status 分布。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_ehs_change.py

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
from app.modules.safety.feishu.ehs_change_bitable import (  # noqa: E402
    _APPROVAL_STATUS_MAP,
    _DURATION_MAP,
    _GRADE_MAP,
    _TYPE_MAP,
)

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50
Q6_THRESHOLD = 3000

_AI_DIM_LABELS = ("申请变更原因", "变更计划内容", "预计效果", "变更风险评估及建议措施")

_APPROVAL_FIELDS = [
    "申请状态", "变更发起人", "当前处理人", "申请编号", "变更申请编号",
    "变更名称", "变更分类", "变更级别", "变更时效", "变更申请部门",
    "申请变更原因", "预计效果", "预计实施日期", "需更新的文件资料",
    "变更状态", "变更计划内容", "变更风险评估及建议措施",
    "是否可以体现", "GMP变更编号", "审批节点", "SourceID", "AI预审意见",
]
_ACCEPTANCE_FIELDS = [
    "申请状态", "发起人", "当前处理人", "申请编号", "变更编号", "变更名称",
    "变更级别", "发起人部门", "验收意见（可另附验收报告）", "审批流程",
    "审批节点", "关联审批", "SourceID", "验收日期",
]


def expected_fields() -> dict[str, set[str]]:
    approval = set(_APPROVAL_FIELDS)
    for label in _AI_DIM_LABELS:
        approval.add(f"{label}-AI审核结论")
        approval.add(f"{label}-AI审核报告")
    return {"approval": approval, "acceptance": set(_ACCEPTANCE_FIELDS)}


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
    # page_token 必须放 URL query（放 body 被飞书忽略，恒返第一页）
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


def _shape_of(v: Any) -> str:
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return "list<dict>"
        if v and isinstance(v[0], str):
            return "list<str>"
        return "list"
    return type(v).__name__


async def main() -> int:
    conns = {v.kind: v for v in store.get_connections("ehs_change")}
    if not conns:
        print("[x] ehs_change 连接未配置，中止")
        return 2
    app_token = next((c.app_token for c in conns.values() if c.app_token), "")
    if not app_token:
        print("[x] ehs_change app_token 为空，中止")
        return 2
    print("== 1. 连接配置 ==")
    print(f"  app_token={app_token}")
    for kind in ("approval", "acceptance"):
        c = conns.get(kind)
        print(f"  {kind}: table_id={c.table_id if c else '<未配置>'} enabled={c.enabled if c else '-'}"
              f" status={c.status if c else '-'}")

    token = await get_safety_tenant_token()
    tables_data: dict[str, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=30) as http:
        names = await _get_json(http, token, f"{BASE_URL}/{app_token}/tables")
        tnames = {i.get("table_id", ""): i.get("name", "")
                  for i in (names.get("items", []) or [])}

        for kind in ("approval", "acceptance"):
            conn = conns.get(kind)
            if conn is None or not conn.table_id:
                print(f"\n[x] {kind} 未配置 table_id，跳过该表")
                continue
            table_id = conn.table_id
            print(f"\n===== 表 {kind} ({tnames.get(table_id, '?')} / {table_id}) =====")
            # ── 2. 字段盘点 ──
            print("== 2. 字段盘点 ==")
            fields = await _get_json(
                http, token, f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
            items = list(fields.get("items", []) or [])
            present: dict[str, int] = {}
            type_map: dict[str, Any] = {}
            for f in items:
                present[f.get("field_name", "")] = f.get("type", 0)
                type_map[f.get("field_name", "")] = f
            print(f"  共 {len(items)} 字段")
            expected = expected_fields()[kind]
            absent = [f for f in sorted(expected) if f not in present]
            if absent:
                print(f"  [!!] mapper 期望但表缺失: {absent}")
            else:
                print(f"  [OK] mapper 期望 {len(expected)} 字段全部在表")
            extra = [f for f in present if f not in expected]
            print(f"  mapper 未涉及的多余列: {extra or '无'}")
            formula_cols = [f for f, t in present.items() if t == 2]
            print(f"  公式列（type=2）: {formula_cols or '无'}"
                  f"（若映射涉及其值，须 search/get_record 形态对照）")
            print("  -- 枚举字段选项（type 3 单选 / 4 多选）--")
            for fname, ftype in sorted(present.items()):
                if ftype not in (3, 4):
                    continue
                prop = (type_map[fname].get("property") or {})
                opts = prop.get("options")
                if isinstance(opts, list) and opts:
                    labels = [str(o.get("name", "")) for o in opts]
                    print(f"    - {fname} ({'单选' if ftype == 3 else '多选'}): {labels}")

            # ── 3. 行数量级 ──
            print("== 3. 行数与耗时 ==")
            t0 = time.perf_counter()
            total, fetched, pages = 0, 0, 0
            all_items: list[dict[str, Any]] = []
            page_token: str | None = None
            for _ in range(MAX_PAGES):
                data = await _search_page(http, token, app_token, table_id, page_token)
                pages += 1
                if isinstance(data.get("total"), int) and page_token is None:
                    total = data["total"]
                chunk = list(data.get("items", []) or [])
                all_items.extend(chunk)
                fetched += len(chunk)
                if not data.get("has_more") or not data.get("page_token"):
                    break
                page_token = data.get("page_token")
            elapsed = time.perf_counter() - t0
            verdict = ("全量（<=3000 行）" if fetched <= Q6_THRESHOLD
                       else ">3000 行，需复核量级")
            print(f"  行数: total={total} fetched={fetched} pages={pages}"
                  f" fetch={elapsed:.2f}s  [{verdict}]"
                  + ("" if total == fetched else "  [!!] total!=fetched"))
            has_ct = sum(1 for it in all_items if it.get("created_time"))
            print(f"  created_time 非空行: {has_ct}/{len(all_items)}"
                  f"（automatic_fields 直读排序键候选）")
            tables_data[kind] = {"items": all_items, "present": present}

        # ── 4. 形态抽样（approval 表优先）──
        print("\n== 4. 形态抽样（search 口径）==")
        sample_fields = [
            ("approval", "申请编号"), ("approval", "变更发起人"),
            ("approval", "申请状态"), ("approval", "变更级别"),
            ("approval", "变更分类"), ("approval", "变更时效"),
            ("approval", "预计实施日期"), ("approval", "变更申请编号"),
            ("approval", "申请变更原因-AI审核结论"),
            ("approval", "申请变更原因-AI审核报告"),
            ("approval", "AI预审意见"),
            ("acceptance", "申请编号"), ("acceptance", "发起人"),
            ("acceptance", "验收日期"), ("acceptance", "审批流程"),
            ("acceptance", "关联审批"),
        ]
        for kind, fname in sample_fields:
            td = tables_data.get(kind)
            if not td:
                continue
            if fname not in td["present"]:
                print(f"    [{kind}] {fname}: <表无此列>")
                continue
            shapes: dict[str, int] = {}
            sample: Any = None
            for item in td["items"]:
                v = (item.get("fields", {}) or {}).get(fname)
                if v is None or v == "" or v == []:
                    continue
                k = _shape_of(v)
                shapes[k] = shapes.get(k, 0) + 1
                if sample is None:
                    sample = v
            if not shapes:
                print(f"    [{kind}] {fname}: <全表空>")
            else:
                top = ", ".join(f"{k} x{n}" for k, n in
                                sorted(shapes.items(), key=lambda x: -x[1]))
                print(f"    [{kind}] {fname}: {top}  例: {repr(sample)[:90]}")

        # ── 5. 口径基线 ──
        print("\n== 5. 口径基线 ==")
        for kind in ("approval", "acceptance"):
            td = tables_data.get(kind)
            if not td:
                continue
            status_dist: dict[str, int] = {}
            for it in td["items"]:
                s = _txt((it.get("fields", {}) or {}).get("申请状态")).strip()
                status_dist[s or "<空>"] = status_dist.get(s or "<空>", 0) + 1
            print(f"  [{kind}] 申请状态分布: "
                  f"{dict(sorted(status_dist.items(), key=lambda x: -x[1]))}")
            known = set(_APPROVAL_STATUS_MAP) | {""}
            unknown = {k: v for k, v in status_dist.items() if k not in known}
            if unknown:
                print(f"  [!!] [{kind}] _APPROVAL_STATUS_MAP 未覆盖: {unknown}")
            else:
                print(f"  [OK] [{kind}] 申请状态全部被 _APPROVAL_STATUS_MAP 覆盖")
        appr = tables_data.get("approval", {}).get("items", [])
        if appr:
            grade_dist: dict[str, int] = {}
            for it in appr:
                g = _txt((it.get("fields", {}) or {}).get("变更级别")).strip()
                grade_dist[g or "<空>"] = grade_dist.get(g or "<空>", 0) + 1
            print(f"  [approval] 变更级别分布: {grade_dist}")
            unknown_g = {k: v for k, v in grade_dist.items()
                         if k not in set(_GRADE_MAP) | {""}}
            if unknown_g:
                print(f"  [!!] _GRADE_MAP 未覆盖（将原样透传）: {unknown_g}")
            ai_rows = 0
            pre_rows = 0
            for it in appr:
                flds = it.get("fields", {}) or {}
                hit = any(
                    _txt(flds.get(f"{label}-AI审核结论")).strip()
                    or _txt(flds.get(f"{label}-AI审核报告")).strip()
                    for label in _AI_DIM_LABELS
                )
                if hit:
                    ai_rows += 1
                if _txt(flds.get("AI预审意见")).strip():
                    pre_rows += 1
            print(f"  [approval] AI 结论/报告任一非空行: {ai_rows}/{len(appr)}"
                  f"（直读 ai_review_status=completed 可组装面）")
            print(f"  [approval] AI预审意见非空行: {pre_rows}/{len(appr)}")

    # ── 6. PG 镜像基线 ──
    print("\n== 6. PG 镜像基线（source 分布——本域风险最高）==")
    from sqlalchemy import func, select

    from app.core.database import async_session_factory
    from app.modules.safety.models import EhsChange

    async with async_session_factory() as session:
        n_all = await session.scalar(
            select(func.count()).select_from(EhsChange))
        n_live = await session.scalar(
            select(func.count()).select_from(EhsChange)
            .where(EhsChange.is_deleted == False))  # noqa: E712
        print(f"  ehs_changes: 总行={n_all} 软删={(n_all or 0) - (n_live or 0)} 活行={n_live}")
        rows = await session.execute(
            select(EhsChange.source, EhsChange.feishu_table_id,
                   func.count(),
                   func.count(EhsChange.feishu_record_id),
                   func.count(EhsChange.actual_start),
                   func.count(EhsChange.actual_completion),
                   func.count(EhsChange.ai_review_result))
            .where(EhsChange.is_deleted == False)  # noqa: E712
            .group_by(EhsChange.source, EhsChange.feishu_table_id))
        print("  source × table × [行数, 有fid, actual_start非空, actual_completion非空, ai_result非空]:")
        for r in rows.all():
            print(f"    source={r[0]!r:12} table={r[1]!r:14} 行={r[2]:4}"
                  f" fid={r[3]:4} a_start={r[4]:3} a_comp={r[5]:3} ai_res={r[6]:3}")
        st = await session.execute(
            select(EhsChange.source, EhsChange.status, func.count())
            .where(EhsChange.is_deleted == False)  # noqa: E712
            .group_by(EhsChange.source, EhsChange.status))
        print("  source × status 分布:")
        for r in st.all():
            print(f"    {r[0]!r:12} {r[1]:16} x{r[2]}")
        sm_states = {"in_progress", "commissioned", "closed", "draft", "submitted"}
        sm_rows = await session.execute(
            select(func.count()).select_from(EhsChange)
            .where(EhsChange.is_deleted == False,  # noqa: E712
                   EhsChange.source == "bitable",
                   EhsChange.status.in_(sm_states)))
        n_sm = sm_rows.scalar() or 0
        print(f"  [字段级丢失面] bitable 行上出现状态机态"
              f"（draft/submitted/in_progress/commissioned/closed）: {n_sm}"
              f"（>0 = API 状态机曾驱动 Bitable 行，直读丢 status/actual_*）")
        ai_st = await session.execute(
            select(EhsChange.ai_review_status, func.count())
            .where(EhsChange.is_deleted == False)  # noqa: E712
            .group_by(EhsChange.ai_review_status))
        print(f"  ai_review_status 分布: {dict(ai_st.all())}")

    # ── 7. 汇总 ──
    print("\n== 7. 汇总 ==")
    bt = {k: len(v.get("items", [])) for k, v in tables_data.items()}
    print(f"  Bitable 行数: {bt}")
    print(f"  PG 活行={n_live}（source×fid 明细见第 6 节）")
    print("  判定提示: 无 fid 活行=直读结构性丢失面；bitable 行状态机态=字段级丢失面")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
