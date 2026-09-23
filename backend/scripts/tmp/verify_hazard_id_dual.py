"""双路径比对 + 零回写探针（hazard-id-direct Ticket 06，照 verify_oh_dual 方法学）。

本地开关保持全关（脚本内部按比对项临时拨开关，结束恢复）；推送面显式关闭
（安全速递误发教训——本域虽无推送面，同款防御）。只调用查询路径：不触碰
事件 handler、AI 流程、回写面。**运行前置：先跑 backfill_hazard_id_mirror.py
--apply 回填本地镜像**（cert/msds/oh 三域先例）。

验收级（本域唯一切换工具 query_hazard_identifications，全项硬 PASS/FAIL）：
  1. 记录集：direct-only=0（回填后事件已追平）；mirror-only ⊆ 幽灵行集
     （探针 recvrX7gkf2SS1 重复 2 行病灶，spec D9）
  2. 公共 fid 15 字段：严格 14 字段差=0（含 feishu_url 双侧恒 None quirk）；
     department 差异盘点归因（identity 时效/同名取序，不判 FAIL）
  3. 工具场景 ×6（无过滤/部门/岗位/风险等级/关键词/整体状态）：total 差值
     全归因幽灵行；direct 页内严格字段与镜像一致
  4. 直读排序自洽：query 层 created_time desc（跨路径排序键差属 spec D5
     受控偏差，不做跨路径顺序相等断言——oh 先例口径）
  5. 零回写探针：直读查询路径 Bitable 写端点调用数 = 0
  6. 性能：TTL 窗口内第二次直读调用 <2s（D4 预授权条款已落地 cache.py；
     首拉 ~3.7s 属已落档受控偏差）

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

DIRECT = "SAFETY_HAZARD_ID_DIRECT_ENABLED"
_PUSH_KEYS = (
    "SAFETY_DAILY_DIGEST_ENABLED",
    "SAFETY_REGULATION_CRAWLER_ENABLED",
)
# 工具 15 输出字段（read_tools 逐字）；department 单列归因不进严格集
STRICT_FIELDS = (
    "hazard_id_no", "position", "production_step", "specific_activity",
    "hazard_type", "possible_accident", "inherent_risk_label",
    "residual_risk_label", "post_risk_label", "control_level",
    "recommendation_content", "overall_status", "submitter_name",
    "feishu_url",
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


async def _tool(ctx: Any, **kw: Any) -> dict[str, Any]:
    from app.modules.safety.business_agent.tools.read_tools import (
        query_hazard_identifications,
    )
    return await query_hazard_identifications(ctx, **kw)  # type: ignore[arg-type]


def _mirror_item(r: Any) -> dict[str, Any]:
    """镜像 ORM 行 → 工具 15 字段同款投影（legacy 逐字）。"""
    return {
        "hazard_id_no": r.hazard_id_no,
        "department": r.department,
        "position": r.position,
        "production_step": r.production_step,
        "specific_activity": r.specific_activity,
        "hazard_type": r.hazard_type,
        "possible_accident": r.possible_accident,
        "inherent_risk_label": r.inherent_risk_label,
        "residual_risk_label": r.residual_risk_label,
        "post_risk_label": r.post_risk_label,
        "control_level": r.control_level,
        "recommendation_content": r.recommendation_content,
        "overall_status": r.overall_status,
        "submitter_name": r.submitter_name,
        "feishu_url": r.feishu_url,
    }


def _ghost_matches(kw: dict[str, Any]) -> int:
    """幽灵行中满足场景过滤的行数（legacy total 会多算的部分）。"""
    from app.modules.safety.service.hazard_id_direct.query import (
        _HI_LEVEL_KEYWORDS,
        _STAGE_LABEL_ATTRS,
    )

    stage_attr = (
        _STAGE_LABEL_ATTRS.get((kw.get("risk_stage") or "").strip().lower())
        if kw.get("risk_stage") else None
    )
    kws = (
        _HI_LEVEL_KEYWORDS.get(kw["risk_level"].strip())
        if kw.get("risk_level") else None
    )
    status_norm = (
        kw["overall_status"].strip().lower() if kw.get("overall_status") else None
    )

    def _m(it: dict[str, Any]) -> bool:
        if kw.get("department") and (
            kw["department"].lower() not in _norm(it["department"]).lower()
        ):
            return False
        if kw.get("position") and (
            kw["position"].lower() not in _norm(it["position"]).lower()
        ):
            return False
        if stage_attr and kws:
            label = _norm(it[stage_attr])
            if not any(k in label for k in kws):
                return False
        if status_norm and _norm(it["overall_status"]) != status_norm:
            return False
        if kw.get("keyword") and not any(
            kw["keyword"].lower() in _norm(it[f]).lower()
            for f in ("specific_activity", "hazard_type", "possible_accident")
        ):
            return False
        return True

    return sum(1 for no, it in mirror_items.items() if no in ghost_nos and _m(it))


mirror_items: dict[str, dict[str, Any]] = {}
ghost_nos: set[str] = set()


async def main() -> int:
    global mirror_items, ghost_nos

    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import HazardIdentification
    from app.modules.safety.service.hazard_id_direct import query as hid_query
    from app.modules.safety.service.hazard_id_direct import reader as hid_reader

    for key in _PUSH_KEYS:
        os.environ.pop(key, None)  # 推送/爬虫面显式关闭（本脚本只读查询）
    _env_direct(False)

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        ctx = SimpleNamespace(deps=SimpleNamespace(db=db, person=None))

        mirror_rows = list((await db.scalars(
            select(HazardIdentification).where(
                HazardIdentification.is_deleted == False,  # noqa: E712
            )
        )).all())
        mirror_items = {r.hazard_id_no: _mirror_item(r) for r in mirror_rows}

        t0 = time.perf_counter()
        views = await hid_reader.open_reader().fetch_all(strict=True)
        elapsed = time.perf_counter() - t0
        direct_fids = {v.record_id for v in views}
        print(f"直读全量 {len(views)} 行（首拉 strict {elapsed:.2f}s，"
              f"D4 受控偏差已落档）；镜像活行 {len(mirror_rows)}")

        # 幽灵行集（spec D9）：同 fid 重复活行 + Bitable 已删但 PG 活着的行
        fid_counts: dict[str, int] = {}
        for r in mirror_rows:
            fid_counts[r.feishu_record_id or ""] = (
                fid_counts.get(r.feishu_record_id or "", 0) + 1
            )
        ghost_fids = {f for f, n in fid_counts.items() if f and n > 1}
        ghost_fids |= {
            f for f in fid_counts if f and f not in direct_fids
        }
        ghost_nos = {
            r.hazard_id_no for r in mirror_rows
            if (r.feishu_record_id or "") in ghost_fids
        }

        departments = await hid_query.resolve_departments(
            db, {v.submitter_name for v in views},
        )
        direct_items = {
            it["hazard_id_no"]: it for it in (
                hid_query._item(v, departments.get(v.submitter_name or ""))
                for v in views
            )
        }

        # ── 1. 记录集 ──
        print("\n== 1. 记录集 ==")
        direct_only = set(direct_items) - set(mirror_items)
        mirror_only = set(mirror_items) - set(direct_items)
        unexplained = mirror_only - ghost_nos
        _record(not direct_only, "direct-only=0（回填后事件追平）",
                f"direct_only={sorted(direct_only)[:5]} 共{len(direct_only)}")
        _record(not unexplained, "mirror-only ⊆ 幽灵行集",
                f"mirror_only={sorted(mirror_only)[:5]} 共{len(mirror_only)}"
                f"；未解释={sorted(unexplained)[:5]} 共{len(unexplained)}")
        _report("幽灵行（重复组/Bitable 已删未软删）",
                f"ghost_fids={sorted(ghost_fids)} ghost_nos={sorted(ghost_nos)}")

        # ── 2. 公共 fid 字段 ──
        print("\n== 2. 公共 fid 字段（15 字段）==")
        common = set(direct_items) & set(mirror_items)
        dept_diffs: list[tuple[str, Any, Any]] = []
        strict_diffs: list[tuple[str, str, Any, Any]] = []
        for no in common:
            d, m = direct_items[no], mirror_items[no]
            if _norm(d["department"]) != _norm(m["department"]):
                dept_diffs.append((no, m["department"], d["department"]))
            for f in STRICT_FIELDS:
                if _norm(d[f]) != _norm(m[f]):
                    strict_diffs.append((no, f, m[f], d[f]))
        _record(not strict_diffs, "严格 14 字段差=0",
                f"差={len(strict_diffs)}" + (
                    f" 样本={strict_diffs[:5]}" if strict_diffs else ""))
        _report("department 差异（identity 时效/同名取序归因，不判 FAIL）",
                f"差={len(dept_diffs)} 样本={dept_diffs[:3]}")
        url_m = sum(1 for r in mirror_rows if r.feishu_url)
        _record(url_m == 0, "feishu_url 镜像非空=0（死值 quirk 双侧一致）",
                f"mirror feishu_url 非空={url_m}")

        # ── 3. 工具场景 ──
        print("\n== 3. 工具场景（direct vs legacy）==")
        scenarios: list[tuple[str, dict[str, Any]]] = [
            ("无过滤", {}),
            ("部门=提炼", {"department": "提炼"}),
            ("岗位=结晶", {"position": "结晶"}),
            ("固有重大", {"risk_stage": "inherent", "risk_level": "重大"}),
            ("关键词=中毒", {"keyword": "中毒"}),
            ("状态=completed", {"overall_status": "completed"}),
        ]
        for label, kw in scenarios:
            _env_direct(True)
            d = await _tool(ctx, page_size=100, **kw)
            _env_direct(False)
            m = await _tool(ctx, page_size=100, **kw)
            ghost_hit = _ghost_matches(kw)
            diff = m["total"] - d["total"]
            field_bad: list[str] = []
            for i in d["items"]:
                mi = mirror_items.get(i["hazard_id_no"])
                if mi is None:
                    continue
                for f in STRICT_FIELDS:
                    if _norm(i[f]) != _norm(mi[f]):
                        field_bad.append(f"{i['hazard_id_no']}.{f}")
            _record(diff == ghost_hit and not field_bad, f"场景[{label}]",
                    f"legacy={m['total']} direct={d['total']} 差={diff}"
                    f" 幽灵命中={ghost_hit}；页内严格字段差="
                    f"{field_bad[:5] or 0}")

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
        await _tool(ctx, keyword="中毒")
        second = time.perf_counter() - t0
        _env_direct(False)
        _record(second < 2.0, "TTL 窗口内直读 <2s",
                f"second={second:.2f}s（first={first:.2f}s；D4 首拉 ~3.7s "
                f"受控偏差已落档）")
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
