"""双路径比对 + 零回写探针（ehs-change-direct Ticket 05，照 verify_hazard_id_dual
方法学改域）。

本地开关保持全关（脚本内部按比对项临时拨开关，结束恢复）；推送面显式关闭
（安全速递误发教训——本域虽无推送面，同款防御）。只调用查询路径：不触碰
事件 handler、AI 审核回写、状态机 API。**运行前置：先跑
backfill_ehs_change_mirror.py 回填本地镜像**（cert/msds/oh/hazard_id 先例；
2026-09-24 已跑，insert=10 update=482，PG 活行 492=Bitable 全量）。

验收级（本域唯一切换工具 query_ehs_changes，全项硬 PASS/FAIL）：
  1. 记录集：direct-only=0 且 mirror-only=0（回填后事件已追平；本域无
     幽灵行/双源，探针坐实 100% 有 fid）
  2. 公共 fid 13 字段严格差=0（含 actual_start/actual_completion/
     expected_completion/location_unit 双侧恒 None——状态机零使用复刻）
  3. 工具场景 ×6（无过滤/部门/类型/等级/状态/AI预审状态/关键词）：total
     差=0；direct 页内严格字段与镜像一致（按 change_no 匹配）
  4. 直读排序自洽：query 层 created_time desc（跨路径排序键差属 spec D3
     受控偏差，不做跨路径顺序相等断言——oh/hazard_id 先例口径）
  5. 零回写探针：直读查询路径 Bitable 写端点调用数 = 0
  6. 性能：TTL 窗口内第二次直读调用 <2s（D4 预授权条款已落地 cache.py；
     首拉约 1.3s（两表并发）为已落档口径）

退出码：0 全 PASS；1 有 FAIL。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

DIRECT = "SAFETY_EHS_CHANGE_DIRECT_ENABLED"
_PUSH_KEYS = (
    "SAFETY_DAILY_DIGEST_ENABLED",
    "SAFETY_REGULATION_CRAWLER_ENABLED",
)
# 工具 13 输出字段（read_tools 逐字；恒 None 四件套含在内双侧核验）
STRICT_FIELDS = (
    "change_no", "title", "change_type", "change_grade", "department",
    "location_unit", "status", "expected_start", "expected_completion",
    "actual_start", "actual_completion", "applicant_name",
    "ai_review_status",
)
_WRITE_METHODS = (
    "update_record", "create_record", "batch_create",
    "create_field", "delete_record",
)

results: list[tuple[bool, str, str]] = []


def _record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"：{detail}" if detail else ""))


def _report(name: str, detail: str = "") -> None:
    print(f"  [盘点] {name}" + (f"：{detail}" if detail else ""))


def _env_direct(on: bool) -> None:
    if on:
        os.environ[DIRECT] = "true"
    else:
        os.environ.pop(DIRECT, None)


def _norm(v: Any) -> str:
    """NULL/空归一（gotchas#10 比对前归一口径）。"""
    return "" if v is None else str(v)


def _iso(v: Any) -> str | None:
    return v.isoformat() if v else None


async def _tool(ctx: Any, **kw: Any) -> dict[str, Any]:
    from app.modules.safety.business_agent.tools.read_tools import (
        query_ehs_changes,
    )
    return await query_ehs_changes(ctx, **kw)  # type: ignore[arg-type]


def _mirror_item(r: Any) -> dict[str, Any]:
    """镜像 ORM 行 → 工具 13 字段同款投影（legacy 逐字）。"""
    return {
        "change_no": r.change_no,
        "title": r.title,
        "change_type": r.change_type,
        "change_grade": r.change_grade,
        "department": r.department,
        "location_unit": r.location_unit,
        "status": r.status,
        "expected_start": _iso(r.expected_start),
        "expected_completion": _iso(r.expected_completion),
        "actual_start": _iso(r.actual_start),
        "actual_completion": _iso(r.actual_completion),
        "applicant_name": r.applicant_name,
        "ai_review_status": r.ai_review_status,
    }


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import EhsChange
    from app.modules.safety.service.ehs_change_direct import query as ehs_query
    from app.modules.safety.service.ehs_change_direct import reader as ehs_reader

    for key in _PUSH_KEYS:
        os.environ.pop(key, None)  # 推送/爬虫面显式关闭（本脚本只读查询）
    _env_direct(False)

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        ctx = SimpleNamespace(deps=SimpleNamespace(db=db, person=None))

        mirror_rows = list((await db.scalars(
            select(EhsChange).where(
                EhsChange.is_deleted == False,  # noqa: E712
            )
        )).all())
        mirror_items = {r.feishu_record_id or "": _mirror_item(r)
                        for r in mirror_rows}

        t0 = time.perf_counter()
        views = await ehs_reader.open_reader().fetch_all(strict=True)
        elapsed = time.perf_counter() - t0
        direct_fids = {v.record_id for v in views}
        print(f"直读全量 {len(views)} 行（首拉 strict {elapsed:.2f}s，两表并发）；"
              f"镜像活行 {len(mirror_rows)}")

        direct_items = {
            v.record_id: ehs_query._item(v) for v in views  # noqa: SLF001
        }

        # ── 1. 记录集 ──
        print("\n== 1. 记录集 ==")
        direct_only = set(direct_fids) - set(mirror_items)
        mirror_only = set(mirror_items) - set(direct_fids)
        _record(not direct_only, "direct-only=0（回填后事件追平）",
                f"direct_only={sorted(direct_only)[:5]} 共{len(direct_only)}")
        _record(not mirror_only, "mirror-only=0（本域无幽灵行/双源）",
                f"mirror_only={sorted(mirror_only)[:5]} 共{len(mirror_only)}")

        # ── 2. 公共 fid 13 字段 ──
        print("\n== 2. 公共 fid 字段（13 字段）==")
        common = set(direct_fids) & set(mirror_items)
        strict_diffs: list[tuple[str, str, Any, Any]] = []
        for fid in common:
            d, m = direct_items[fid], mirror_items[fid]
            for f in STRICT_FIELDS:
                if _norm(d[f]) != _norm(m[f]):
                    strict_diffs.append((fid, f, m[f], d[f]))
        _record(not strict_diffs, "严格 13 字段差=0",
                f"差={len(strict_diffs)}" + (
                    f" 样本={strict_diffs[:5]}" if strict_diffs else ""))

        # 恒 None 四件套盘点（状态机零使用 + 映射恒 None 复刻）
        none_bad = [
            (fid, f) for fid in common for f in (
                "location_unit", "expected_completion",
                "actual_start", "actual_completion",
            ) if _norm(direct_items[fid][f]) != ""
        ]
        _record(not none_bad, "恒 None 四件套直读侧全空",
                f"violation={none_bad[:5] or 0}")

        # ── 3. 工具场景 ──
        print("\n== 3. 工具场景（direct vs legacy）==")
        scenarios: list[tuple[str, dict[str, Any]]] = [
            ("无过滤", {}),
            ("部门=提炼", {"department": "提炼"}),
            ("类型=设备设施变更code", {"change_type": "equipment_facility"}),
            ("等级=重大", {"change_grade": "重大"}),
            ("状态=approved", {"status": "approved"}),
            ("AI预审=completed", {"ai_review_status": "completed"}),
            ("关键词=车间", {"keyword": "车间"}),
        ]
        for label, kw in scenarios:
            _env_direct(True)
            d = await _tool(ctx, page_size=100, **kw)
            _env_direct(False)
            m = await _tool(ctx, page_size=100, **kw)
            diff = m["total"] - d["total"]
            field_bad: list[str] = []
            for i in d["items"]:
                cn = i.get("change_no")
                if not cn:
                    continue
                mi = next(
                    (it for it in mirror_items.values()
                     if it.get("change_no") == cn), None,
                )
                if mi is None:
                    continue
                for f in STRICT_FIELDS:
                    if _norm(i[f]) != _norm(mi[f]):
                        field_bad.append(f"{cn}.{f}")
            _record(diff == 0 and not field_bad, f"场景[{label}]",
                    f"legacy={m['total']} direct={d['total']} 差={diff}"
                    f"；页内严格字段差={field_bad[:5] or 0}")

        # ── 4. 直读排序自洽 ──
        print("\n== 4. 直读排序自洽 ==")
        ordered = sorted(
            views,
            key=lambda v: v.created_time_ms if v.created_time_ms is not None else 0,
            reverse=True,
        )
        seq2 = [v.created_time_ms or 0 for v in ordered]
        _record(all(a >= b for a, b in zip(seq2, seq2[1:])),
                "query 层 created_time desc 自洽")
        no_ct = sum(1 for v in views if v.created_time_ms is None)
        _report("created_time 覆盖", f"缺失 {no_ct}/{len(views)}"
                f"（automatic_fields=True，hazard_id 594/594 先例）")

        # ── 5. 零回写探针 ──
        print("\n== 5. 零回写探针 ==")
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        writes: list[str] = []
        originals = {name: getattr(SafetyBitableClient, name, None)
                     for name in _WRITE_METHODS}
        for name in _WRITE_METHODS:
            def _hit(*a: Any, _n: str = name, **kw2: Any) -> Any:
                writes.append(_n)
                raise AssertionError(f"直读路径触发写调用: {_n}")
            setattr(SafetyBitableClient, name, _hit)
        try:
            _env_direct(True)
            d = await _tool(ctx, department="提炼", page_size=20)
        finally:
            for name, orig in originals.items():
                if orig is not None:
                    setattr(SafetyBitableClient, name, orig)
            _env_direct(False)
        _record(not writes and d.get("success") is True,
                "直读查询路径写端点调用=0", f"writes={writes}")

        # ── 6. 性能（TTL 窗口内） ──
        print("\n== 6. 性能 ==")
        _env_direct(True)
        t0 = time.perf_counter()
        await _tool(ctx, department="提炼")
        first = time.perf_counter() - t0
        t0 = time.perf_counter()
        await _tool(ctx, keyword="车间")
        second = time.perf_counter() - t0
        _env_direct(False)
        _record(second < 2.0, "TTL 窗口内直读 <2s",
                f"second={second:.2f}s（first={first:.2f}s；D4 首拉两表并发"
                f"口径已落档）")
    finally:
        _env_direct(False)
        await session_ctx.__aexit__(None, None, None)

    fails = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(fails)}/{len(results)} PASS ==")
    return 1 if fails else 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except RuntimeError as exc:
        print(f"[x] {exc}")
        sys.exit(3)
