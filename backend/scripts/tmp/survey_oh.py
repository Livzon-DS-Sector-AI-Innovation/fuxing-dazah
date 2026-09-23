"""oh 职业健康只读探针（直读改造前置盘点，批次四-1）。

只读，零写入。输出：
  1. position/hazard_factor 两连接配置（同 Base 单文档 6 表之一）；
  2. 两表 list_fields 全字段盘点：position 期望 4 列（部门/岗位/职务/危害因素）、
     hazard_factor 期望 2 列（危害因素名称/呼吸防护用品）（oh_bitable_handler
     map_position_fields / map_hazard_factor_fields）；枚举/单选字段选项值核对
     （position 危害因素多选 options 与 42 项标准字典比对）；handler 未映射的
     多余列；
  3. 两表行数量级与全量拉取耗时（Q6 量级确认，阈值 3000）；
  4. 关键字段原始值形态抽样（search 口径：富文本段 / 多选 list）；
  5. 口径基线：跳行规则证据（position 部门/岗位均空行数；hazard_factor 名称
     空行数）、factor_name 重复行数（镜像部分唯一索引 vs 直读天然含重复）、
     危害因素多选 options 与 42 项标准清单差集；
  6. PG 镜像行数基线（oh_* 五镜像表 + oh_followups 平台独占表）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_oh.py

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

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50
Q6_THRESHOLD = 3000

# position 表 handler 期望字段（oh_bitable_handler.map_position_fields）
POSITION_EXPECTED = ["部门", "岗位", "职务", "危害因素"]
# hazard_factor 表 handler 期望字段（map_hazard_factor_fields）
FACTOR_EXPECTED = ["危害因素名称", "呼吸防护用品"]


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
                        expected: list[str]) -> list[dict[str, Any]]:
    print(f"\n== {label}: 字段盘点 ==")
    names = await _get_json(http, token, f"{BASE_URL}/{app_token}/tables")
    tname = next((i.get("name", "") for i in (names.get("items", []) or [])
                  if i.get("table_id") == table_id), "<表名未找到>")
    fields = await _get_json(http, token,
                             f"{BASE_URL}/{app_token}/tables/{table_id}/fields")
    items = list(fields.get("items", []) or [])
    print(f"  {tname}: {len(items)} fields")
    present: set[str] = set()
    multi_options: dict[str, list[str]] = {}
    for f in items:
        fname, ftype = f.get("field_name", ""), f.get("type", "")
        present.add(fname)
        extra = ""
        prop = f.get("property") or {}
        opts = prop.get("options")
        if isinstance(opts, list) and opts:
            labels = [str(o.get("name", "")) for o in opts]
            extra = f"  options({len(labels)})={labels[:8]}"
            if ftype == 4:  # 4=多选
                multi_options[fname] = labels
        if ftype in (2, 5):  # 数字/公式也标注
            extra += f" [type={ftype}]"
        print(f"    - {fname}{extra}")

    absent = [f for f in expected if f not in present]
    if absent:
        print(f"  [!!] 期望但表缺失: {absent}")
    else:
        print(f"  [OK] 期望 {len(expected)} 字段全部在表")
    extra_fields = [f for f in present if f not in expected]
    print(f"  handler 未映射的多余列: {extra_fields or '无'}")

    total, fetched, pages, elapsed, all_items = await _fetch_all(
        http, token, app_token, table_id)
    verdict = ("全量（<=3000 行，Q6=A 成立）" if fetched <= Q6_THRESHOLD
               else ">3000 行，需复核 Q6")
    print(f"  行数: total={total} fetched={fetched} pages={pages} fetch={elapsed:.2f}s"
          f"  [{verdict}]" + ("" if total == fetched else "  [!!] total!=fetched"))
    if multi_options:
        for fname, labels in multi_options.items():
            print(f"  多选字段 {fname}: {len(labels)} 个选项")
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


def _position_baseline(items: list[dict[str, Any]]) -> None:
    skip = sum(
        1 for it in items
        if not _txt((it.get("fields", {}) or {}).get("部门")).strip()
        and not _txt((it.get("fields", {}) or {}).get("岗位")).strip()
    )
    filled = sum(1 for it in items if _multi((it.get("fields", {}) or {}).get("危害因素")))
    print(f"    跳行规则（部门岗位均空）: {skip} 行（handler 跳过不进镜像）")
    print(f"    危害因素非空行={filled} / 全部 {len(items)} 行"
          f"（直读 status 派生 filled/empty 的输入面）")
    dup: dict[tuple[str, str], int] = {}
    for it in items:
        key = (_txt((it.get("fields", {}) or {}).get("部门")).strip(),
               _txt((it.get("fields", {}) or {}).get("岗位")).strip())
        dup[key] = dup.get(key, 0) + 1
    dup_pairs = {k: v for k, v in dup.items() if v > 1 and (k[0] or k[1])}
    print(f"    部门+岗位重复行组: {len(dup_pairs)}"
          f"（镜像部分唯一索引 uq_oh_positions_dept_pos 证据，直读天然含重复）")
    if dup_pairs:
        top = sorted(dup_pairs.items(), key=lambda x: -x[1])[:5]
        print(f"      重复最多: {top}")


def _factor_baseline(items: list[dict[str, Any]],
                     standard: tuple[str, ...]) -> None:
    empty = sum(
        1 for it in items
        if not _txt((it.get("fields", {}) or {}).get("危害因素名称")).strip()
    )
    print(f"    跳行规则（名称空）: {empty} 行（handler 跳过不进镜像）")
    names: dict[str, int] = {}
    for it in items:
        nm = _txt((it.get("fields", {}) or {}).get("危害因素名称")).strip()
        if nm:
            names[nm] = names.get(nm, 0) + 1
    dup = {k: v for k, v in names.items() if v > 1}
    print(f"    名称非空={sum(names.values())} 唯一={len(names)} 重复名行组={len(dup)}"
          f"（镜像部分唯一索引 uq_oh_hazard_factors_name 证据，直读天然含重复）")
    if dup:
        print(f"      重复: {sorted(dup.items(), key=lambda x: -x[1])[:5]}")
    table_set = set(names)
    std_set = set(standard)
    print(f"    表内名称 vs 42 项标准字典: 表独有={sorted(table_set - std_set)[:10]}"
          f" 标准字典未上表数={len(std_set - table_set)}")
    ppe = sum(
        1 for it in items
        if _txt((it.get("fields", {}) or {}).get("呼吸防护用品")).strip()
    )
    print(f"    呼吸防护用品非空行={ppe}")


def _nonempty(items: list[dict[str, Any]], fname: str) -> int:
    return sum(1 for it in items
               if (it.get("fields", {}) or {}).get(fname) not in (None, "", []))


async def _pg_counts() -> None:
    from sqlalchemy import func, select

    from app.core.database import async_session_factory
    from app.modules.safety.models import (
        OhExamApplication,
        OhFollowup,
        OhHazardFactor,
        OhHealthExam,
        OhPerson,
        OhPosition,
    )

    async with async_session_factory() as session:
        print("\n== 6. PG 镜像行数基线 ==")
        for label, model in (
            ("oh_persons（人员汇总）", OhPerson),
            ("oh_health_exams（体检记录）", OhHealthExam),
            ("oh_positions（岗位）", OhPosition),
            ("oh_hazard_factors（危害因素 PPE）", OhHazardFactor),
            ("oh_exam_applications（转岗离岗申请）", OhExamApplication),
            ("oh_followups（异常随访=平台独占，无 Bitable 源）", OhFollowup),
        ):
            n = await session.scalar(
                select(func.count()).select_from(model)
                .where(model.is_deleted == False)  # noqa: E712
            )
            print(f"  {label}: 非删除 {n}")


async def main() -> int:
    conns: list[tuple[str, Any]] = []
    for kind in ("position", "hazard_factor"):
        conn = store.get_connection("oh", kind)
        if conn is None or conn.status == "disabled":
            print(f"[x] oh/{kind} 连接未配置或已停用，中止")
            return 2
        conns.append((kind, conn))

    token = await get_safety_tenant_token()
    async with httpx.AsyncClient(timeout=30) as http:
        print("== 1. 连接配置 ==")
        same_base = conns[1][1].app_token == conns[0][1].app_token
        for kind, conn in conns:
            print(f"  {kind}: app_token={conn.app_token}"
                  f" table_id={conn.table_id}")
        print(f"  同 Base（单文档 6 表）: {same_base}")
        app_token = conns[0][1].app_token

        from app.modules.safety.service.oh_hazard_factor import (
            OH_HAZARD_FACTORS_STANDARD,
        )

        results: dict[str, list[dict[str, Any]]] = {}
        results["position"] = await _survey_table(
            http, token, app_token, conns[0][1].table_id,
            "2. 岗位信息表（position）", POSITION_EXPECTED)
        results["hazard_factor"] = await _survey_table(
            http, token, app_token, conns[1][1].table_id,
            "3. 危害因素 PPE 表（hazard_factor）", FACTOR_EXPECTED)

        print("\n== 4. 形态抽样 ==")
        print("  [position]")
        _sample_shapes(results["position"], ["部门", "岗位", "职务", "危害因素"])
        print("  [hazard_factor]")
        _sample_shapes(results["hazard_factor"], ["危害因素名称", "呼吸防护用品"])

        print("\n== 5. 口径基线 ==")
        print("  [position]")
        _position_baseline(results["position"])
        print("  [hazard_factor]")
        _factor_baseline(results["hazard_factor"], OH_HAZARD_FACTORS_STANDARD)

        await _pg_counts()

        print("\n== 7. 汇总 ==")
        print(f"  岗位表={len(results['position'])} 行"
              f" 危害因素表={len(results['hazard_factor'])} 行"
              f" 同 Base={same_base}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
