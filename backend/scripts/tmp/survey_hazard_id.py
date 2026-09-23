"""hazard_id 危险源辨识只读探针（直读改造前置盘点，批次四-2）。

只读，零写入。输出：
  1. 连接配置（hazard_id/identification 单表）；
  2. list_fields 全字段盘点：与 service/hazard_identification_bitable.py 映射
     常量（_BASE_FIELDS/_AI_MANUAL_PAIRS 双侧/_D_VALUE_PAIRS 双侧/_SCRIPT8_FIELDS/
     人员/节点/附件/福建/审核状态列）核对，多余列单列；
  3. 行数量级与全量拉取耗时（Q6 阈值 3000）+ search 响应是否带 created_time
     元数据（直读排序键候选）；
  4. 关键字段原始值形态抽样（search 口径：富文本段 / 多选 list / 公式数值）；
  5. 口径基线：节点标签分布 vs _NODE_LABEL_TO_ENUM、审核状态分布 vs
     _REVIEW_STATUS_MAP、D 值可推导行数、提交人员姓名分布（identity 派生部门
     可行性）、危险类型（人工/AI）多选值域；
  6. PG 镜像基线（oh 新判例——切面前必查 source 分布）：
     hazard_identifications 总行/软删、feishu_record_id NULL vs NOT NULL
     （平台创建流双源风险）、feishu_url 非空数、overall_status 分布、
     department 非空数、hazard_id_no 冲突组。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_hazard_id.py

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
from app.modules.safety.service.hazard_identification_bitable import (  # noqa: E402
    _AI_MANUAL_PAIRS,
    _ATTACHMENT_FIELD,
    _BASE_FIELDS,
    _D_VALUE_PAIRS,
    _FUJIAN_RISK_FIELD,
    _NODE_FIELD,
    _NODE_LABEL_TO_ENUM,
    _REVIEW_STATUS_MAP,
    _SCRIPT8_FIELDS,
)

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50
Q6_THRESHOLD = 3000


def expected_fields() -> list[str]:
    """映射常量涉及的全部 Bitable 字段名（双侧）。"""
    names: set[str] = set()
    names.update(_BASE_FIELDS.values())
    for ai_name, manual_name in _AI_MANUAL_PAIRS.values():
        names.add(ai_name)
        names.add(manual_name)
    for ai_name, manual_name in _D_VALUE_PAIRS.values():
        names.add(ai_name)
        names.add(manual_name)
    names.update(_SCRIPT8_FIELDS.values())
    names.update(_FUJIAN_RISK_FIELD)
    names.update(_ATTACHMENT_FIELD)
    names.update(_NODE_FIELD)
    # 人员列（map 第 5 段 _lookup 候选）
    names.update({"提交人员（人工）", "提交人员", "审核人员（人工）", "审核人员"})
    # 8 个脚本人工审核状态列（handler _review_fingerprint）
    names.update(f"脚本{i}（人工审核状态）" for i in range(1, 9))
    return sorted(names)


def _txt(v: Any) -> str:
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return str(v[0].get("text") or "")
    if isinstance(v, dict):
        return str(v.get("text") or "")
    return str(v) if v is not None else ""


def _multi(v: Any) -> list[str]:
    if isinstance(v, dict):
        v = v.get("value")
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for item in v:
        if isinstance(item, dict):
            t = str(item.get("text", "") or "").strip()
        else:
            t = str(item).strip()
        if t:
            out.append(t)
    return out


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


def _shape_of(v: Any) -> str:
    if isinstance(v, list):
        if v and isinstance(v[0], dict):
            return "list<dict>"
        if v and isinstance(v[0], str):
            return "list<str>"
        return "list"
    return type(v).__name__


async def main() -> int:
    conn = store.get_connection("hazard_id", "identification")
    if conn is None or conn.status == "disabled":
        print("[x] hazard_id/identification 连接未配置或已停用，中止")
        return 2
    app_token, table_id = conn.app_token, conn.table_id
    print("== 1. 连接配置 ==")
    print(f"  identification: app_token={app_token} table_id={table_id}"
          f" enabled={conn.enabled}")

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        # ── 2. 字段盘点 ──
        print("\n== 2. 字段盘点 ==")
        names = await _get_json(http, token, f"{BASE_URL}/{app_token}/tables")
        tname = next((i.get("name", "") for i in (names.get("items", []) or [])
                      if i.get("table_id") == table_id), "<表名未找到>")
        fields = await _get_json(
            http, token, f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
        items = list(fields.get("items", []) or [])
        present: dict[str, int] = {}
        type_map: dict[str, Any] = {}
        for f in items:
            fname = f.get("field_name", "")
            present[fname] = f.get("type", 0)
            type_map[fname] = f
        print(f"  {tname}: {len(items)} fields")
        expected = expected_fields()
        absent = [f for f in expected if f not in present]
        if absent:
            print(f"  [!!] 映射常量期望但表缺失: {absent}")
        else:
            print(f"  [OK] 映射常量期望 {len(expected)} 字段全部在表")
        extra = [f for f in present if f not in set(expected)]
        print(f"  映射常量未涉及的多余列: {extra or '无'}")
        for fname in extra:
            f = type_map[fname]
            prop = f.get("property") or {}
            opts = prop.get("options")
            o = ""
            if isinstance(opts, list) and opts:
                o = f"  options={[str(x.get('name', '')) for x in opts][:10]}"
            print(f"    - {fname} [type={f.get('type')}]{o}")
        # 枚举字段选项打印（单选/多选）
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
        print("\n== 3. 行数与耗时 ==")
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
        verdict = ("全量（<=3000 行，Q6=A 成立）" if fetched <= Q6_THRESHOLD
                   else ">3000 行，需复核 Q6")
        print(f"  行数: total={total} fetched={fetched} pages={pages}"
              f" fetch={elapsed:.2f}s  [{verdict}]"
              + ("" if total == fetched else "  [!!] total!=fetched"))
        if all_items:
            meta_keys = sorted(k for k in all_items[0] if k != "fields")
            print(f"  行元数据键（排序键候选）: {meta_keys}")
            has_ct = sum(1 for it in all_items if it.get("created_time"))
            print(f"  created_time 非空行: {has_ct}/{len(all_items)}")

        # ── 4. 形态抽样 ──
        print("\n== 4. 形态抽样（search 口径）==")
        for fname in ("岗位（人工）", "具体作业活动（人工）", "危险类型（人工）",
                      "风险值D（固有）（人工）", "可能性L（固有）（人工）",
                      "提交人员（人工）", "提交人员", _ATTACHMENT_FIELD, _NODE_FIELD,
                      "固有风险等级（福建AI）"):
            if fname not in present:
                print(f"    {fname}: <表无此列>")
                continue
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
                top = ", ".join(f"{k} x{n}" for k, n in
                                sorted(shapes.items(), key=lambda x: -x[1]))
                print(f"    {fname}: {top}  例: {repr(sample)[:80]}")

        # ── 5. 口径基线 ──
        print("\n== 5. 口径基线 ==")
        node_dist: dict[str, int] = {}
        for it in all_items:
            node = _txt((it.get("fields", {}) or {}).get(_NODE_FIELD)).strip()
            node_dist[node or "<空>"] = node_dist.get(node or "<空>", 0) + 1
        print(f"  节点标签分布: {dict(sorted(node_dist.items(), key=lambda x: -x[1]))}")
        unknown = {k: v for k, v in node_dist.items()
                   if k not in _NODE_LABEL_TO_ENUM and k != "<空>"}
        if unknown:
            print(f"  [!!] _NODE_LABEL_TO_ENUM 未覆盖的节点标签: {unknown}")
        else:
            print("  [OK] 节点标签全部被 _NODE_LABEL_TO_ENUM 覆盖（或为空）")

        review_vals: dict[str, int] = {}
        for i in range(1, 9):
            for it in all_items:
                v = _txt((it.get("fields", {}) or {}).get(
                    f"脚本{i}（人工审核状态）")).strip()
                review_vals[v or "<空>"] = review_vals.get(v or "<空>", 0) + 1
        print(f"  审核状态值域（8 列合并）: {review_vals}")
        bad_review = {k: v for k, v in review_vals.items()
                      if k not in _REVIEW_STATUS_MAP and k != "<空>"}
        if bad_review:
            print(f"  [!!] _REVIEW_STATUS_MAP 未覆盖: {bad_review}")

        submitter_dist: dict[str, int] = {}
        for it in all_items:
            nm = ""
            raw = ((it.get("fields", {}) or {}).get("提交人员（人工）")
                   if "提交人员（人工）" in (it.get("fields", {}) or {})
                   else (it.get("fields", {}) or {}).get("提交人员"))
            if isinstance(raw, list):
                for p in raw:
                    if isinstance(p, dict) and (p.get("name") or "").strip():
                        nm = (p.get("name") or "").strip()
                        break
            elif isinstance(raw, dict):
                nm = (raw.get("name") or "").strip()
            elif raw:
                nm = str(raw).strip()
            submitter_dist[nm or "<空>"] = submitter_dist.get(nm or "<空>", 0) + 1
        print(f"  提交人员姓名分布: {dict(sorted(submitter_dist.items(), key=lambda x: -x[1])[:15])}")

        ht_values: dict[str, int] = {}
        for it in all_items:
            for v in _multi((it.get("fields", {}) or {}).get("危险类型（人工）")):
                ht_values[v] = ht_values.get(v, 0) + 1
        print(f"  危险类型（人工）实际值域: {dict(sorted(ht_values.items(), key=lambda x: -x[1]))}")

        d_rows = sum(1 for it in all_items
                     if _txt((it.get("fields", {}) or {}).get(
                         "风险值D（固有）（人工）"))
                     or _txt((it.get("fields", {}) or {}).get("风险值D（固有）（AI）")))
        print(f"  固有 D 值（AI/人工任一）非空行: {d_rows}/{len(all_items)}"
              f"（等级/管控层级可推导面）")

        # ── 6. PG 镜像基线 ──
        print("\n== 6. PG 镜像基线（source 分布）==")
        from sqlalchemy import func, select

        from app.core.database import async_session_factory
        from app.modules.safety.models import HazardIdentification

        async with async_session_factory() as session:
            n_all = await session.scalar(
                select(func.count()).select_from(HazardIdentification))
            n_live = await session.scalar(
                select(func.count()).select_from(HazardIdentification)
                .where(HazardIdentification.is_deleted == False))  # noqa: E712
            n_fid = await session.scalar(
                select(func.count()).select_from(HazardIdentification)
                .where(HazardIdentification.is_deleted == False,  # noqa: E712
                       HazardIdentification.feishu_record_id.isnot(None)))
            n_nofid = (n_live or 0) - (n_fid or 0)
            n_url = await session.scalar(
                select(func.count()).select_from(HazardIdentification)
                .where(HazardIdentification.is_deleted == False,  # noqa: E712
                       HazardIdentification.feishu_record_id.isnot(None),
                       HazardIdentification.feishu_url.isnot(None)))
            n_dept = await session.scalar(
                select(func.count()).select_from(HazardIdentification)
                .where(HazardIdentification.is_deleted == False,  # noqa: E712
                       HazardIdentification.department.isnot(None)))
            print(f"  hazard_identifications: 总行={n_all} 软删={(n_all or 0) - (n_live or 0)} 活行={n_live}")
            print(f"  [双源判定] 活行有 fid={n_fid} / 无 fid={n_nofid}"
                  f"（无 fid=平台创建流独占行，直读结构性丢失面）")
            print(f"  有 fid 行 feishu_url 非空: {n_url}（源码核实无写入方，预期 0）")
            print(f"  department 非空（有 fid 活行中）: 待 SQL 细算")
            n_dept_fid = await session.scalar(
                select(func.count()).select_from(HazardIdentification)
                .where(HazardIdentification.is_deleted == False,  # noqa: E712
                       HazardIdentification.feishu_record_id.isnot(None),
                       HazardIdentification.department.isnot(None)))
            print(f"    -> {n_dept_fid}/{n_fid}")
            os_rows = await session.execute(
                select(HazardIdentification.overall_status, func.count())
                .where(HazardIdentification.is_deleted == False)  # noqa: E712
                .group_by(HazardIdentification.overall_status))
            print(f"  overall_status 分布: {dict(os_rows.all())}")
            # hazard_id_no 派生冲突探测（HI-{fid[-12:]} 截断冲突）
            no_rows = await session.execute(
                select(func.substring(HazardIdentification.hazard_id_no, 1, 3),
                       func.count())
                .where(HazardIdentification.is_deleted == False)  # noqa: E712
                .group_by(func.substring(HazardIdentification.hazard_id_no, 1, 3)))
            print(f"  hazard_id_no 前缀分布: {dict(no_rows.all())}")

        # ── 7. 汇总 ──
        print("\n== 7. 汇总 ==")
        print(f"  Bitable 行={len(all_items)}  PG 活行有 fid={n_fid} 无 fid={n_nofid}"
              f"  差值（事件延迟/软删/双源）=Bitable-{(n_fid or 0)}={len(all_items) - (n_fid or 0)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
