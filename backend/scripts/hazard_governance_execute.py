"""P2-4 T06 —— 隐患登记表治理清单执行器（GOVERNANCE 50→44 列收口）。

用户 2026-11-10 拍板「你全部执行」。分步子命令 + ``--confirm`` 门（破坏性
操作删列/改字段类型/改记录值必须显式确认）；全部动作先导出留档。

子命令：
- ``--export``：只读导出 6 个待删列的非空值 → CSV（evidence/governance/）
- ``--check-forms``：只读列出表单及其字段（判定「停用7列」可行性）
- ``--fix-dual-value``（--confirm）：双值记录级别改「较大隐患」（写前回读）
- ``--delete-columns``（--confirm）：删 6 列（5 个遗留 AI 审核列 + 重复标签（AI））
- ``--level-single-select``（--confirm）：隐患级别 多选→单选（field_type 必带；
  改前断言存量双值仅 0 条——先跑 fix-dual-value）
- ``--verify``：只读复核列数与目标列存活状态

用法（cwd=backend）::

    .venv/bin/python scripts/hazard_governance_execute.py --export
    .venv/bin/python scripts/hazard_governance_execute.py --delete-columns --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.getcwd())

from app.modules.safety.service.hazard_direct.field_authority import (  # noqa: E402
    F_LEVEL_MANUAL,
)

# ── 处置清单常量（docs/GOVERNANCE-隐患登记表字段处置清单-20261106.md）──
DELETE_COLUMNS = [
    "AI审核结论", "AI审核理由", "AI发现问题", "AI补充建议", "AI审核时间",
    "重复标签（AI）",
]
DISABLE_COLUMNS = [
    "检查人员状态", "安全办人员状态", "安全经理确认", "安全总监确认",
    "检查级别", "检查人员身份", "重点缺陷",
]
DUAL_VALUE_RECORD = "recv9WxR01nnpD"  # §二 裁决：改「较大隐患」
EVIDENCE_DIR = Path("../.scratch/hazard-p2-closeout/evidence/governance")

BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"


def _val(fields: dict[str, Any], name: str) -> Any:
    v = fields.get(name)
    if isinstance(v, list):
        return ",".join(str(x) for x in v)
    return v if v is not None else ""


async def _fields_map(client: Any) -> dict[str, dict[str, Any]]:
    return {f["field_name"]: f for f in await client.list_fields()}


async def _export(client: Any) -> None:
    """只读导出 6 待删列值（全表）。"""
    records = await client.list_all_records(strict=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    for col in DELETE_COLUMNS:
        path = EVIDENCE_DIR / f"export-{col}.csv"
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(["record_id", col])
            n = 0
            for r in records:
                v = _val(r.get("fields", {}), col)
                if v != "":
                    writer.writerow([r.get("record_id"), v])
                    n += 1
        print(f"导出 {col}: {n} 条非空 → {path}")
    # 双值记录现值一并留档
    for r in records:
        if r.get("record_id") == DUAL_VALUE_RECORD:
            print(f"双值记录现值: {_val(r.get('fields', {}), F_LEVEL_MANUAL)!r}")
    # 7 停用列的值分布（供停用决策）
    for col in DISABLE_COLUMNS:
        n = sum(1 for r in records if _val(r.get("fields", {}), col) != "")
        print(f"停用列现值: {col} 非空 {n} 条")


async def _check_forms(client: Any) -> None:
    """列出表单与表单字段（只读）——「停用=不出现在填写表单」的可行性判定。"""
    token = await client._token()
    import httpx

    async with httpx.AsyncClient(timeout=15) as http:
        resp = await http.get(
            f"{BITABLE_BASE}/apps/{client.app_token}/tables/{client.table_id}/forms",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
        items = (data.get("data") or {}).get("items") or []
        print(f"表单数: {len(items)}")
        for form in items:
            print(f"  form_id={form.get('form_id')} name={form.get('name')!r}")
            detail = await http.get(
                f"{BITABLE_BASE}/apps/{client.app_token}/tables/{client.table_id}"
                f"/forms/{form.get('form_id')}",
                headers={"Authorization": f"Bearer {token}"},
            )
            d = (detail.json().get("data") or {})
            names = [f.get("field_name") or f.get("title") for f in d.get("form_fields") or []]
            print(f"    字段: {names}")


async def _fix_dual_value(client: Any, confirm: bool) -> None:
    fields = await client.get_record(record_id=DUAL_VALUE_RECORD)
    if not isinstance(fields, dict):
        print("记录不存在或读取失败", file=sys.stderr)
        return
    current = _val(fields, F_LEVEL_MANUAL)
    print(f"现值: {current!r}")
    if current == "较大隐患":
        print("已是单值较大隐患，无需修改")
        return
    if not confirm:
        print("[dry-run] 将改为「较大隐患」（加 --confirm 执行）")
        return
    ok = await client.update_record(
        record_id=DUAL_VALUE_RECORD,
        # 多选列写值必须数组形态（改单选后本路径不再触发——先改值后改型）
        fields={F_LEVEL_MANUAL: ["较大隐患"]},
    )
    print("改值结果:", ok)


async def _delete_columns(client: Any, confirm: bool) -> None:
    fmap = await _fields_map(client)
    token = await client._token()
    import httpx

    for name in DELETE_COLUMNS:
        f = fmap.get(name)
        if f is None:
            print(f"跳过（不存在）: {name}")
            continue
        if not confirm:
            print(f"[dry-run] 将删除列: {name} (field_id={f['field_id']})")
            continue
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.delete(
                f"{BITABLE_BASE}/apps/{client.app_token}/tables/{client.table_id}"
                f"/fields/{f['field_id']}",
                headers={"Authorization": f"Bearer {token}"},
            )
            data = resp.json()
            print(f"删除 {name}: code={data.get('code')} msg={data.get('msg')}")


async def _level_single_select(client: Any, confirm: bool) -> None:
    fmap = await _fields_map(client)
    f = fmap.get(F_LEVEL_MANUAL)
    if f is None:
        print("隐患级别列不存在", file=sys.stderr)
        return
    if f.get("type") == 3:
        print("已是单选，无需修改")
        return
    options = [o.get("name") for o in (f.get("property") or {}).get("options") or []]
    print(f"现类型: {f.get('type')}（4=多选）选项: {options}")
    # 改前断言：存量无双值（多选列单值记录也返回数组——按长度>1判双值）
    records = await client.list_all_records(strict=True)
    dual = [
        r.get("record_id")
        for r in records
        if len((r.get("fields") or {}).get(F_LEVEL_MANUAL) or []) > 1
    ]
    if dual:
        print(f"存在多值记录，先执行 --fix-dual-value: {dual}", file=sys.stderr)
        return
    if not confirm:
        print("[dry-run] 将改为单选 type=3 选项不变（加 --confirm 执行）")
        return
    token = await client._token()
    import httpx

    # 飞书字段更新 body 键是 type/property（field_name 可选但带上保持显式）
    body = {
        "field_name": F_LEVEL_MANUAL,
        "type": 3,
        "property": {"options": [{"name": n} for n in options]},
    }
    async with httpx.AsyncClient(timeout=15) as http:
        # 飞书字段更新是 PUT（PATCH 走不到该路由 → 404 page not found）
        resp = await http.put(
            f"{BITABLE_BASE}/apps/{client.app_token}/tables/{client.table_id}"
            f"/fields/{f['field_id']}",
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        print(f"http={resp.status_code} body={resp.text[:200]}")
        data = resp.json() if resp.status_code == 200 else {}
        print(f"改单选: code={data.get('code')} msg={data.get('msg')}")


async def _verify(client: Any) -> None:
    fmap = await _fields_map(client)
    print(f"列数: {len(fmap)}")
    alive = [c for c in DELETE_COLUMNS if c in fmap]
    print(f"待删列残留: {alive or '无'}")
    lv = fmap.get(F_LEVEL_MANUAL, {})
    print(f"隐患级别类型: {lv.get('type')}（3=单选）")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--check-forms", action="store_true")
    parser.add_argument("--fix-dual-value", action="store_true")
    parser.add_argument("--delete-columns", action="store_true")
    parser.add_argument("--level-single-select", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--confirm", action="store_true", help="破坏性操作确认门")
    args = parser.parse_args()

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    client = SafetyBitableClient()
    if args.export:
        await _export(client)
    if args.check_forms:
        await _check_forms(client)
    if args.fix_dual_value:
        await _fix_dual_value(client, args.confirm)
    if args.delete_columns:
        await _delete_columns(client, args.confirm)
    if args.level_single_select:
        await _level_single_select(client, args.confirm)
    if args.verify:
        await _verify(client)
    if not any((args.export, args.check_forms, args.fix_dual_value,
                args.delete_columns, args.level_single_select, args.verify)):
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
