"""双路径比对 + 零回写探针（chemical_inventory-direct Ticket 08，照 verify_cert_dual.py 方法学）。

前置：先跑 backfill_chemical_mirror.py 回填本地镜像；本地开关保持全关（本脚本内部
按比对项临时拨开关，结束恢复）。

比对项（总计划 §7 DoD）：
  1. 台账全量：镜像 ORM vs 直读视图按 feishu_record_id join + 剥 id/时间戳内容 multiset；
  2. get_records 过滤组合：镜像 repo vs 直读 query（全量组合比对 + total 一致；
     limit 切片窗口在 tie-break 顺序不同的两路径间不可比，只验 total）；
  3. get_stats 逐字段；
  4. analyze_risk items multiset；
  5. 日报渲染：固定昨日快照夹具 + 双侧 updated_at 置 None（新鲜度两侧同源化）后逐字比对；
  6. 零回写探针：查询路径（列表/统计/analyze/全关模式 scan）Bitable 写端点调用数 = 0；
     WRITEBACK_RISK 开时写请求只含 {风险标记, 风险说明}；
  7. API 性能：直读 get_records（462 行）耗时 <2s。

推送安全：本脚本不调用任何推送函数（safety-digest 事故铁律）。
退出码：0 全 PASS；1 有 FAIL。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

DIRECT = "SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED"
EVENT = "SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED"
WB = "SAFETY_CHEMICAL_INVENTORY_WRITEBACK_RISK_ENABLED"

results: list[tuple[bool, str, str]] = []


def _record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"：{detail}" if detail else ""))


def _env_direct(on: bool, writeback: bool = False) -> None:
    if on:
        os.environ[DIRECT] = "true"
    else:
        os.environ.pop(DIRECT, None)
    if writeback:
        os.environ[WB] = "true"
    else:
        os.environ.pop(WB, None)


# ── 内容键（剥 id/时间戳：两路径时间戳天然漂移，id 以 feishu_record_id join；
#    Decimal 归一到最简字面量——镜像 Numeric(14,4) 与直读原始值的字符串形态不同） ──


def _dec(d: Any) -> str | None:
    if d is None:
        return None
    return format(Decimal(str(d)).normalize(), "f")


def _mirror_key(row: Any) -> tuple:
    return (
        row.department, row.storage_location, row.material_name, row.package_spec,
        _dec(row.quantity), row.unit, _dec(row.total_quantity_t),
        _dec(row.max_limit), row.max_limit_unit,
        tuple(sorted(row.hazard_classes or [])), row.category, row.remark,
        row.risk_flag, tuple(sorted(row.risk_note or [])),
    )


def _view_key(v: Any) -> tuple:
    return _mirror_key(SimpleNamespace(
        department=v.department, storage_location=v.storage_location,
        material_name=v.material_name, package_spec=v.package_spec,
        quantity=v.quantity, unit=v.unit, total_quantity_t=v.total_quantity_t,
        max_limit=v.max_limit, max_limit_unit=v.max_limit_unit,
        hazard_classes=v.hazard_classes, category=v.category, remark=v.remark,
        risk_flag=v.risk_flag, risk_note=v.risk_note,
    ))


def _multiset(items: list[Any]) -> dict[Any, int]:
    out: dict[Any, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def _diff_multiset(a: dict[Any, int], b: dict[Any, int]) -> tuple[list[Any], list[Any]]:
    only_a, only_b = [], []
    for k in sorted(set(a) | set(b), key=repr):
        if a.get(k, 0) > b.get(k, 0):
            only_a.extend([k] * (a[k] - b.get(k, 0)))
        if b.get(k, 0) > a.get(k, 0):
            only_b.extend([k] * (b[k] - a.get(k, 0)))
    return only_a, only_b


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.chemical_inventory.daily_report import (
        compute_daily_analysis,
        render_daily_report,
    )
    from app.modules.safety.models import ChemicalInventoryRecord
    from app.modules.safety.service.chemical_inventory import ChemicalInventoryService
    from app.modules.safety.service.chemical_inventory_direct.query import list_records
    from app.modules.safety.service.chemical_inventory_direct.reader import open_reader
    from app.modules.safety.service.chemical_inventory_direct.risk import (
        scan_inventory_views,
    )
    from app.modules.safety.service.chemical_inventory_direct.views import InventoryView

    # ── 取数（长会话承载 legacy repo 查询） ──
    session = async_session_factory()
    db = await session.__aenter__()
    mirror_rows = list((await db.scalars(
        select(ChemicalInventoryRecord).where(
            ChemicalInventoryRecord.is_deleted == False,  # noqa: E712
        )
    )).all())
    svc = ChemicalInventoryService(db)
    os.environ[DIRECT] = "true"
    views = await open_reader().fetch_all(strict=True)
    os.environ.pop(DIRECT, None)
    print(f"镜像行={len(mirror_rows)}（含手工补录无 feishu_id 行单独计）"
          f" 直读视图={len(views)}")

    # ── 1. 台账全量 join + 内容 multiset ──
    mirror_by_fid = {r.feishu_record_id: r for r in mirror_rows if r.feishu_record_id}
    view_by_fid = {v.feishu_record_id: v for v in views if v.feishu_record_id}
    no_fid = [r for r in mirror_rows if not r.feishu_record_id]
    only_mirror = sorted(set(mirror_by_fid) - set(view_by_fid))
    only_view = sorted(set(view_by_fid) - set(mirror_by_fid))
    _record(not only_mirror and not only_view, "1a. feishu_record_id 集合一致",
            f"仅镜像={only_mirror[:3]} 仅直读={only_view[:3]}"
            f" 无fid镜像行={len(no_fid)}")

    common = sorted(set(mirror_by_fid) & set(view_by_fid))
    mk = [_mirror_key(mirror_by_fid[i]) for i in common]
    vk = [_view_key(view_by_fid[i]) for i in common]
    only_m, only_v = _diff_multiset(_multiset(mk), _multiset(vk))
    _record(not only_m and not only_v, "1b. 共同行内容 multiset 一致",
            f"公共行={len(common)} 差异 仅镜像={len(only_m)} 仅直读={len(only_v)}")
    if only_m or only_v:
        for k in only_m[:3]:
            print(f"      仅镜像: {k}")
        for k in only_v[:3]:
            print(f"      仅直读: {k}")

    # ── 2. get_records 过滤组合 ──
    cases: list[tuple[str, dict[str, Any]]] = [
        ("无过滤", {}),
        ("department", {"department": "warehouse"}),
        ("material_name", {"material_name": "醇"}),
        ("组合", {"department": "qc", "material_name": "钠"}),
    ]
    for label, kw in cases:
        m_items, m_total = await svc.get_records(0, 10_000, **kw)
        _env_direct(True)
        d_items, d_total = await list_records(
            open_reader(), 0, 10_000, **kw)
        _env_direct(False)
        m_keys = _multiset([_mirror_key(r) for r in m_items])
        d_keys = _multiset([_view_key(v) for v in d_items])
        om, ov = _diff_multiset(m_keys, d_keys)
        _record(not om and not ov and m_total == d_total,
                f"2. get_records {label}",
                f"total {m_total} vs {d_total}，内容差异 仅镜像={len(om)} 仅直读={len(ov)}")
        # 分页窗口只验 total 一致（tie-break 顺序不可比，cert 教训）
        m_page, m_ptotal = await svc.get_records(0, 7, **kw)
        _env_direct(True)
        _, d_ptotal = await list_records(open_reader(), 0, 7, **kw)
        _env_direct(False)
        _record(m_ptotal == d_ptotal, f"2b. 分页 total {label}",
                f"{m_ptotal} vs {d_ptotal}")

    # ── 3. get_stats ──
    stats_m = await svc.get_stats()
    _env_direct(True)
    stats_d = await svc.get_stats()
    _env_direct(False)
    _record(stats_m == stats_d, "3. get_stats 逐字段", f"{stats_m} vs {stats_d}")

    # ── 4. analyze_risk ──
    ar_m = await svc.analyze_risk()
    _env_direct(True)
    ar_d = await svc.analyze_risk()
    _env_direct(False)
    om, ov = _diff_multiset(
        _multiset([repr(sorted(i.items())) for i in ar_m["items"]]),
        _multiset([repr(sorted(i.items())) for i in ar_d["items"]]),
    )
    _record(ar_m["alert_count"] == ar_d["alert_count"] and not om and not ov,
            "4. analyze_risk", f"alert {ar_m['alert_count']} vs {ar_d['alert_count']}")

    # ── 5. 日报渲染（固定昨日快照夹具 + 新鲜度同源化） ──
    prev = [
        SimpleNamespace(material_name="乙醇", total_quantity_t=7.0),
        SimpleNamespace(material_name="丙酮", total_quantity_t=3.0),
    ]
    for r in mirror_rows:
        r.updated_at = None
    for v in views:
        v.updated_at = None
    analysis_m = compute_daily_analysis(mirror_rows, prev)
    analysis_d = compute_daily_analysis(views, prev)
    render_m = render_daily_report(analysis_m)
    render_d = render_daily_report(analysis_d)
    _record(render_m == render_d, "5. 日报渲染逐字一致",
            "一致" if render_m == render_d else f"长度 {len(render_m)} vs {len(render_d)}")
    if render_m != render_d:
        lm, ld = render_m.splitlines(), render_d.splitlines()
        for i, (a, b) in enumerate(zip(lm, ld)):
            if a != b:
                print(f"      L{i}: 镜像={a!r} 直读={b!r}")

    # ── 6. 零回写探针（写端点哨兵；batch_update 一律拦截不走真网络） ──
    import httpx

    calls: list[str] = []
    bodies: list[Any] = []
    real_post = httpx.AsyncClient.post

    async def _spy_post(self: Any, url: str, **kw: Any) -> Any:
        u = str(url)
        calls.append(u)
        if "/records/batch_update" in u:
            # 写请求拦截：只记录 payload，不打到真表
            bodies.append(kw.get("json"))
            n = len((kw.get("json") or {}).get("records", []))
            return SimpleNamespace(json=lambda: {"code": 0, "data": {"records": [{}] * n}})
        return await real_post(self, url, **kw)

    httpx.AsyncClient.post = _spy_post  # type: ignore[method-assign]
    try:
        def _is_write(url: str) -> bool:
            u = str(url).split("?", 1)[0]
            return (u.endswith("/records") or "/records/batch_update" in u
                    or "/records/batch_create" in u or u.endswith("/fields"))

        # 6a. 查询路径零写
        calls.clear()
        _env_direct(True)
        await svc.get_records(0, 50)
        await svc.get_stats()
        await svc.analyze_risk()
        os.environ.pop(WB, None)  # WRITEBACK 关
        await svc.run_full_scan()
        _env_direct(False)
        writes = [u for u in calls if _is_write(u)]
        _record(not writes, "6a. 查询路径+关回写 scan 零 Bitable 写",
                f"写端点调用 {len(writes)} / 总调用 {len(calls)}")

        # 6b. WRITEBACK 开：scan 写请求只含风险两列（写被拦截，不触真表）
        from app.modules.safety.service.chemical_inventory_direct.contract import (
            WRITEBACK_FIELD_NAMES,
        )

        seeded = [InventoryView(
            id="recVerify", feishu_record_id="recVerify",
            department="warehouse", material_name="VERIFY-只写两列",
            total_quantity_t=None, max_limit=None,
            hazard_classes=[], risk_flag="normal", risk_note=["normal"],
        )]
        calls.clear()
        bodies.clear()
        _env_direct(True, writeback=True)
        try:
            await scan_inventory_views(seeded)
        finally:
            _env_direct(False)
        ok_payloads = True
        for body in bodies:
            for rec in body.get("records", []):
                if not set(rec.get("fields", {})) <= WRITEBACK_FIELD_NAMES:
                    ok_payloads = False
        wrote = any("/records/batch_update" in u for u in calls)
        _record(bool(wrote) and ok_payloads,
                "6b. WRITEBACK 开：写请求只含 {风险标记, 风险说明}（已拦截未触真表）",
                f"拦截 batch_update={sum(1 for u in calls if '/records/batch_update' in u)}"
                f" payload 键白名单={'PASS' if ok_payloads else 'FAIL'}")
    finally:
        httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

    # ── 7. API 性能（直读 get_records <2s）──
    _env_direct(True)
    t0 = time.perf_counter()
    await svc.get_records(0, 50)
    elapsed = time.perf_counter() - t0
    _env_direct(False)
    _record(elapsed < 2.0, "7. 直读 get_records <2s", f"{elapsed:.2f}s")

    os.environ.pop(DIRECT, None)
    os.environ.pop(EVENT, None)
    os.environ.pop(WB, None)
    await session.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS ==")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
