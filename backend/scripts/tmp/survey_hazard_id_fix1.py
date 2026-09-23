"""hazard_id 探针补丁轮（survey_hazard_id.py 修正复核）。

修正与增补：
  1. expected 集合 set.update(str) 拆字 bug 修正（字符串作单元素加入）；
  2. 「日期」列（type=5 DateTime，映射常量未涉及）覆盖面与形态——直读排序
     键候选；
  3. get_record vs search 的 D 值公式列形态对照（单条只读，镜像路径 vs 直读
     路径解析等价性证据）；
  4. 脚本6 三个（人工）列缺失复核（是否需提出建议/建议措施类型/优先级）；
  5. PG：d_inherent/inherent_risk_label/control_level 非空计数（镜像公式列
     解析成功证据）+ hazard_id_no 冲突组 + Bitable/PG fid 差集（幽灵行定位）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/survey_hazard_id_fix1.py
"""

from __future__ import annotations

import asyncio
import sys
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
    _SCRIPT8_FIELDS,
)

BASE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"
PAGE_SIZE = 500
MAX_PAGES = 50


def expected_fields() -> set[str]:
    names: set[str] = set(_BASE_FIELDS.values())
    for ai_name, manual_name in _AI_MANUAL_PAIRS.values():
        names.add(ai_name)
        names.add(manual_name)
    for ai_name, manual_name in _D_VALUE_PAIRS.values():
        names.add(ai_name)
        names.add(manual_name)
    names.update(_SCRIPT8_FIELDS.values())
    names.update({_FUJIAN_RISK_FIELD, _ATTACHMENT_FIELD, _NODE_FIELD})
    names.update({"提交人员（人工）", "提交人员", "审核人员（人工）", "审核人员"})
    names.update(f"脚本{i}（人工审核状态）" for i in range(1, 9))
    return names


async def _search_all(http: httpx.AsyncClient, token: str, app_token: str,
                      table_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    for _ in range(MAX_PAGES):
        params: dict[str, str] = {"field_name_type": "name"}
        if page_token:
            params["page_token"] = page_token
        resp = await http.post(
            f"{BASE_URL}/{app_token}/tables/{table_id}/records/search",
            headers={"Authorization": f"Bearer {token}"},
            params=params, json={"page_size": PAGE_SIZE},
        )
        d = resp.json()
        if not isinstance(d, dict) or d.get("code", 0) != 0:
            raise RuntimeError(f"search failed: {d.get('code')} {d.get('msg')}")
        data = d.get("data", {}) or {}
        items.extend(data.get("items", []) or [])
        if not data.get("has_more") or not data.get("page_token"):
            break
        page_token = data.get("page_token")
    return items


def _txt(v: Any) -> str:
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return str(v[0].get("text") or "")
    if isinstance(v, dict):
        return str(v.get("text") or "")
    return str(v) if v is not None else ""


async def main() -> int:
    conn = store.get_connection("hazard_id", "identification")
    if conn is None or conn.status == "disabled":
        print("[x] 连接未配置或停用")
        return 2
    app_token, table_id = conn.app_token, conn.table_id
    token = await get_safety_tenant_token()

    async with httpx.AsyncClient(timeout=30) as http:
        fields_resp = await http.get(
            f"{BASE_URL}/{app_token}/tables/{table_id}/fields",
            headers={"Authorization": f"Bearer {token}"},
        )
        fdata = (fields_resp.json().get("data", {}) or {})
        present: set[str] = {f.get("field_name", "")
                             for f in fdata.get("items", []) or []}
        expected = expected_fields()
        absent = sorted(f for f in expected if f not in present)
        print("== 1. expected 修正复核 ==")
        print(f"  expected={len(expected)} present={len(present)} 缺失={absent or '无'}")
        extra = sorted(f for f in present if f not in expected)
        print(f"  映射外多余列: {extra}")

        items = await _search_all(http, token, app_token, table_id)
        print(f"\n== 2. 行数 == {len(items)}")

        print("\n== 3. 日期列覆盖与形态（排序键候选）==")
        shapes: dict[str, int] = {}
        sample: Any = None
        for it in items:
            v = (it.get("fields", {}) or {}).get("日期")
            if v is None or v == "" or v == []:
                continue
            k = (type(v).__name__ if not isinstance(v, dict)
                 else f"dict<{type(v.get('value')).__name__}>")
            shapes[k] = shapes.get(k, 0) + 1
            if sample is None:
                sample = v
        print(f"  日期非空形态: {shapes or '<全表空>'}  例: {repr(sample)[:100]}")
        # 数值化覆盖（ms 值可解析比例）
        import datetime as dtm
        parseable = 0
        for it in items:
            v = (it.get("fields", {}) or {}).get("日期")
            raw = v.get("value") if isinstance(v, dict) else v
            if isinstance(raw, (int, float)) and raw > 0:
                parseable += 1
        print(f"  日期可解析(ms)行: {parseable}/{len(items)}")
        if sample is not None:
            raw = sample.get("value") if isinstance(sample, dict) else sample
            if isinstance(raw, (int, float)):
                print(f"  例值换算: {dtm.datetime.fromtimestamp(raw/1000, dtm.timezone(dtm.timedelta(hours=8)))}")

        print("\n== 4. get_record vs search D 值形态对照 ==")
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        probe_rec = next((str(it.get("record_id")) for it in items
                          if (it.get("fields", {}) or {}).get("风险值D（固有）（人工）")
                          is not None), "")
        if probe_rec:
            client = SafetyBitableClient(app_token=app_token, table_id=table_id)
            rec = await client.get_record(probe_rec)
            s_form = next(
                (it.get("fields", {}) or {}).get("风险值D（固有）（人工）")
                for it in items if str(it.get("record_id")) == probe_rec)
            g_form = (rec or {}).get("风险值D（固有）（人工）")
            print(f"  record={probe_rec}")
            print(f"  search 形态: {repr(s_form)[:120]}")
            print(f"  get_record 形态: {repr(g_form)[:120]}")
            from app.modules.safety.service.hazard_identification_bitable import (
                _float, _text,
            )
            print(f"  _float(search)={_float(s_form)}  _float(get_record)={_float(g_form)}")
            print(f"  _text(search)={repr(_text(s_form))[:60]}")
        else:
            print("  <无 D 值非空行>")

        # ── PG 复核 ──
        print("\n== 5. PG 公式列解析证据 + 幽灵行 diff ==")
        from sqlalchemy import func, select

        from app.core.database import async_session_factory
        from app.modules.safety.models import HazardIdentification

        async with async_session_factory() as session:
            for col, label in (
                (HazardIdentification.d_inherent, "d_inherent"),
                (HazardIdentification.inherent_risk_label, "inherent_risk_label"),
                (HazardIdentification.residual_risk_label, "residual_risk_label"),
                (HazardIdentification.post_risk_label, "post_risk_label"),
                (HazardIdentification.control_level, "control_level"),
            ):
                n = await session.scalar(
                    select(func.count()).select_from(HazardIdentification)
                    .where(HazardIdentification.is_deleted == False,  # noqa: E712
                           col.isnot(None)))
                print(f"  {label} 非空: {n}/595")
            nos = (await session.execute(
                select(HazardIdentification.hazard_id_no)
                .where(HazardIdentification.is_deleted == False)  # noqa: E712
            )).scalars().all()
            dup_no = {n for n in nos if nos.count(n) > 1}
            print(f"  hazard_id_no 重复值: {sorted(dup_no) or '无'}")
            pg_fids = set((await session.execute(
                select(HazardIdentification.feishu_record_id)
                .where(HazardIdentification.is_deleted == False,  # noqa: E712
                       HazardIdentification.feishu_record_id.isnot(None))
            )).scalars().all())
            bt_fids = {str(it.get("record_id")) for it in items}
            ghost = sorted(pg_fids - bt_fids)
            new_rows = sorted(bt_fids - pg_fids)
            print(f"  PG 有 Bitable 无（幽灵行）: {ghost}")
            print(f"  Bitable 有 PG 无（事件延迟新行）: {new_rows or '无'}")
            if ghost:
                g = (await session.execute(
                    select(HazardIdentification)
                    .where(HazardIdentification.feishu_record_id.in_(ghost))
                )).scalars().all()
                for r in g:
                    print(f"    幽灵行 {r.feishu_record_id}: no={r.hazard_id_no}"
                          f" dept={r.department} pos={r.position}"
                          f" status={r.overall_status} created={r.created_at}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
