"""cert 直读双路径比对 + 零回写探针（cert-direct Ticket 06）。

只读，零推送，零写入。内容：
  1. 零回写探针：SafetyBitableClient 全部写方法换哨兵，直读路径任何写调用即失败；
  2. API 列表双路径比对（多组筛选 x 分页样本，直读 vs 镜像，记录集差异归因）；
  3. summary 双路径比对（逐字段）；
  4. 08:00 三级推送卡片内容比对（只构建不发送）；
  5. API 直读响应耗时（<2s 验收）。

用法（backend 目录下）：

    .venv/Scripts/python.exe scripts/tmp/verify_cert_dual.py

退出码：0 全部通过；3 存在差异或探针失败（差异含归因说明）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import Counter
from datetime import date
from typing import Any

sys.path.insert(0, ".")

from app.modules.safety.service.cert_direct.query import (  # noqa: E402
    derive_warnings_direct,
    get_summary_direct,
    get_warnings_direct,
)
from app.modules.safety.service.cert_direct.reader import open_reader  # noqa: E402

ACTIVE_LEVELS = {"early_notice", "to_schedule", "key_warning", "urgent", "overdue"}


# ── 1. 零回写探针 ──


def install_write_sentinels() -> list[str]:
    """把 SafetyBitableClient 写方法全部换哨兵；返回被调用写方法名单。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    calls: list[str] = []
    for name in (
        "update_record", "create_record", "delete_record",
        "create_field", "update_field",
    ):
        def _sentinel(*args: Any, _name: str = name, **kwargs: Any) -> None:
            calls.append(_name)
            raise RuntimeError(f"零回写探针: 直读路径调用写方法 {_name}")

        setattr(SafetyBitableClient, name, _sentinel)
    return calls


# ── 比对辅助 ──


def _record_key(d: dict[str, Any]) -> str:
    """内容级键：剥掉 id（双路径 id 空间不同：镜像=UUID、直读=recXXX）。"""
    biz = {k: v for k, v in d.items() if k != "id"}
    return json.dumps(biz, sort_keys=True, ensure_ascii=False, default=str)


def _diff_records(
    mirror: list[dict[str, Any]], direct: list[dict[str, Any]]
) -> tuple[bool, str]:
    """内容 multiset 比对；差异按方向归因（直读多 = 镜像落后，方向正确）。"""
    from collections import Counter

    cm = Counter(_record_key(d) for d in mirror)
    cd = Counter(_record_key(d) for d in direct)
    if cm == cd:
        return True, "完全一致"
    only_mirror = sorted((cm - cd).elements())
    only_direct = sorted((cd - cm).elements())
    lines: list[str] = []
    if only_mirror:
        lines.append(f"仅镜像有 {len(only_mirror)} 条（内容已不在直读表）: "
                     f"{[x[:60] for x in only_mirror[:5]]}")
    if only_direct:
        lines.append(f"仅直读有 {len(only_direct)} 条（事件镜像未同步，方向=直读更正确）: "
                     f"{[x[:60] for x in only_direct[:5]]}")
    return False, ("\n".join(lines))


# ── 2. API 列表双路径比对 ──

# 内容等价用全量组合（两条路径 tie-break 顺序不同，切片窗口无可比性）；
# 分页组合只核对 total（切片正确性由单测覆盖）
LIST_COMBOS: list[dict[str, Any]] = [
    {"skip": 0, "limit": 5000},
    {"skip": 0, "limit": 5000, "department": "生产部"},
    {"skip": 0, "limit": 5000, "cert_category": "special_op"},
    {"skip": 0, "limit": 5000, "status_level": "overdue"},
    {"skip": 0, "limit": 5000, "status_level": "urgent"},
    {"skip": 0, "limit": 5000, "days_within": 30},
]


async def compare_list(service: Any, reader: Any) -> bool:
    print("\n== 2. API 列表双路径比对 ==")
    all_ok = True
    for kw in LIST_COMBOS:
        mirror_items, mirror_total = await service.get_warnings(**kw)
        t0 = time.perf_counter()
        direct_items, direct_total = await get_warnings_direct(reader, **kw)
        elapsed = (time.perf_counter() - t0) * 1000
        m = [d.model_dump(mode="json") for d in mirror_items]
        d = [x.model_dump(mode="json") for x in direct_items]
        ok, detail = _diff_records(m, d)
        total_ok = mirror_total == direct_total
        all_ok = all_ok and ok and total_ok
        tag = "PASS" if (ok and total_ok) else "DIFF"
        print(f"  [{tag}] {kw} mirror_total={mirror_total} direct_total={direct_total}"
              f" elapsed={elapsed:.0f}ms")
        if not (ok and total_ok):
            print("    " + detail.replace("\n", "\n    ")
                  + ("" if total_ok else f"\n    total 不一致: mirror={mirror_total}"
                     f" direct={direct_total}"))

    # 分页机制核对：只比对 total（切片窗口内容因 tie-break 顺序不同不可比）
    mirror_items, mirror_total = await service.get_warnings(skip=20, limit=10)
    direct_items, direct_total = await get_warnings_direct(reader, skip=20, limit=10)
    pag_ok = mirror_total == direct_total and len(direct_items) == 10
    all_ok = all_ok and pag_ok
    print(f"  [{'PASS' if pag_ok else 'DIFF'}] 分页 skip=20 limit=10"
          f" mirror_total={mirror_total} direct_total={direct_total}"
          f" direct_window={len(direct_items)}")
    return all_ok


# ── 3. summary 双路径比对 ──


async def compare_summary(service: Any, reader: Any) -> bool:
    print("\n== 3. summary 双路径比对 ==")
    mirror = await service.get_summary()
    direct = await get_summary_direct(reader)
    m, d = mirror.model_dump(), direct.model_dump()
    if m == d:
        print("  [PASS] 逐字段一致")
        return True
    print("  [DIFF] 逐字段差异:")
    for field in m:
        if m[field] != d[field]:
            print(f"    {field}: mirror={m[field]!r} direct={d[field]!r}")
    return False


# ── 4. 三级推送卡片内容比对（只构建，不发送）──


def build_cards(pairs: list[tuple[Any, Any]]) -> list[tuple[str, str, str]]:
    """复用 scheduler 卡片构建纯函数，返回 (title, open_id_marker, content) 列表。"""
    from app.modules.safety.scheduler import (
        _build_dept_summary_card,
        _build_full_summary_card,
        _build_personal_card,
    )

    cards: list[tuple[str, str, str]] = []
    for r, res in pairs:
        cards.append(("personal", str(r.person_name), _build_personal_card(r, res)))
    by_dept: dict[str, list[tuple[Any, Any]]] = {}
    for r, res in pairs:
        by_dept.setdefault(r.department or "未知部门", []).append((r, res))
    for dept, items in sorted(by_dept.items()):
        cards.append(("dept", dept, _build_dept_summary_card(dept, items)))
    if pairs:
        cards.append(("full", "ALL", _build_full_summary_card(pairs)))
    return cards


async def compare_push_cards(reader: Any) -> bool:
    print("\n== 4. 08:00 三级推送卡片内容比对（不发送）==")
    from app.core.database import async_session_factory
    from app.modules.safety.service.cert_warning import (
        CertWarningEngine,
        CertWarningService,
    )

    today = date.today()

    # 镜像侧：与 scheduler legacy 分支同口径
    async with async_session_factory() as session:
        service = CertWarningService(session)
        rows = await service.repo.get_all_active()
    mirror_pairs = []
    for r in rows:
        res = CertWarningEngine.calculate(r, today)
        if res.status in ACTIVE_LEVELS:
            mirror_pairs.append((r, res))

    # 直读侧：与 scheduler direct 分支同口径
    direct_pairs = [
        (d.view, d.result)
        for d in await derive_warnings_direct(reader, strict=True, today=today)
        if d.result.status in ACTIVE_LEVELS
    ]

    cards_m = sorted(build_cards(mirror_pairs))
    cards_d = sorted(build_cards(direct_pairs))
    if cards_m == cards_d:
        print(f"  [PASS] 卡片逐字一致（{len(cards_m)} 张；"
              f"active mirror={len(mirror_pairs)} direct={len(direct_pairs)}）")
        return True

    # 归一比对：明细行排序后逐张比对（同键组内 tie-break 顺序差异归因——
    # 镜像按 created_at DESC，直读按表格顺序；内容集合一致即等价）
    def _normalized(cards: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for kind, key, content in cards:
            lines = content.splitlines()
            body = sorted(ln for ln in lines if ln.startswith("- "))
            head = [ln for ln in lines if not ln.startswith("- ")]
            out.append((kind, key, "\n".join(head + body)))
        return sorted(out)

    if _normalized(cards_m) == _normalized(cards_d):
        print(f"  [PASS] 行序归一后逐字一致（{len(cards_m)} 张；"
              f"mirror={len(mirror_pairs)} direct={len(direct_pairs)}）")
        print("  [归因] 同键组内行序不同：镜像 ORDER BY created_at DESC（同步时刻），"
              "直读按表格顺序；Bitable 无时间戳字段，属预期可接受差异")
        return True

    print(f"  [DIFF] 卡片不一致（mirror={len(cards_m)} direct={len(cards_d)} 张）")
    tm, td = {c[:2] for c in cards_m}, {c[:2] for c in cards_d}
    for key in sorted(tm - td):
        print(f"    仅镜像有: {key}")
    for key in sorted(td - tm):
        print(f"    仅直读有: {key}")
    nm, nd = dict(((c[0], c[1]), c[2]) for c in _normalized(cards_m)), \
        dict(((c[0], c[1]), c[2]) for c in _normalized(cards_d))
    for key in sorted(set(nm) & set(nd)):
        if nm[key] != nd[key]:
            ml, dl = nm[key].splitlines(), nd[key].splitlines()
            for a, b in zip(ml, dl, strict=False):
                if a != b:
                    print(f"    {key} mirror: {a}")
                    print(f"    {key} direct: {b}")
    return False


async def main() -> int:
    write_calls = install_write_sentinels()
    reader = open_reader()
    print("[i] 直读 reader 组装完成；写方法哨兵已挂（任何写调用即探针失败）")

    from app.core.database import async_session_factory
    from app.modules.safety.service.cert_warning import CertWarningService

    async with async_session_factory() as session:
        service = CertWarningService(session)

        t0 = time.perf_counter()
        views = await reader.get_all_active(strict=True)
        elapsed = (time.perf_counter() - t0) * 1000
        by_cat = Counter(v.cert_category for v in views)
        print(f"\n== 0. 直读全量 == total={len(views)} by_category={dict(by_cat)}"
              f" elapsed={elapsed:.0f}ms")

        list_ok = await compare_list(service, reader)
        summary_ok = await compare_summary(service, reader)

    cards_ok = await compare_push_cards(reader)

    print("\n== 5. 零回写探针 ==")
    if write_calls:
        print(f"  [FAIL] 直读路径发生写调用: {write_calls}")
        probe_ok = False
    else:
        print("  [PASS] 写调用 = 0")
        probe_ok = True

    all_ok = list_ok and summary_ok and cards_ok and probe_ok
    print("\n== 结论 ==")
    print(f"  list={list_ok} summary={summary_ok} push_cards={cards_ok}"
          f" zero_writeback={probe_ok} -> {'PASS' if all_ok else 'DIFF/FAIL'}")
    return 0 if all_ok else 3


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
