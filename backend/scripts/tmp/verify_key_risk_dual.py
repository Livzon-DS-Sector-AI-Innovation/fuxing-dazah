"""双路径比对 + 零回写探针（key_risk_op-direct Ticket 05，照 verify_chemical_dual 方法学）。

前置：先跑 backfill_key_risk_mirror.py 回填本地镜像；本地开关保持全关（本脚本内部
按比对项临时拨开关，结束恢复）。

比对项（DoD，纯只读域裁剪）：
  1. 台账全量：镜像 ORM vs 直读视图按 feishu_record_id join + 剥 id/审计时间内容 multiset；
  2. 列表过滤组合（无/department/apply_status/日期窗/keyword）：service 双路径全量比对
     + 分页 total（两路径排序键一致但 tie 组内序可异，比对用 multiset）；
  3. Agent 语义查询：read_tools 双路径（真 ctx 假 db 会话）items/total 比对；
  4. get_stats 四 KPI 逐字段；
  5. 详情：同一条记录 UUID（legacy）vs recXXX（direct）字段一致；
  6. 导出行集：喂给渲染的 items 比对（渲染共用代码零改动）；
  7. 零回写探针：直读查询路径 Bitable 写端点调用数 = 0；
  8. API 性能：缓存命中后 get_reports <2s（首拉 ~4.9s 为已落档例外）。

退出码：0 全 PASS；1 有 FAIL。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

DIRECT = "SAFETY_KEY_RISK_OP_DIRECT_ENABLED"
EVENT = "SAFETY_KEY_RISK_OP_EVENT_SYNC_ENABLED"

results: list[tuple[bool, str, str]] = []


def _record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"：{detail}" if detail else ""))


def _env_direct(on: bool) -> None:
    if on:
        os.environ[DIRECT] = "true"
    else:
        os.environ.pop(DIRECT, None)


def _canon(v: Any) -> str:
    if v is None:
        return "<null>"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
    if isinstance(v, datetime_like()):
        return v.isoformat()
    return str(v)


def datetime_like() -> tuple[type, ...]:
    from datetime import datetime

    return (datetime,)


def _row_key(row: Any) -> tuple:
    return (
        row.report_no, _canon(row.approval_no_url), row.apply_status,
        row.approval_node, row.approval_flow, row.current_handler,
        row.initiator_name, row.initiator_department,
        _canon(row.submitted_at), _canon(row.completed_at),
        row.department, row.area, row.operation_content,
        _canon(row.start_time), _canon(row.end_time), row.duration_hours,
        row.notes, row.personal_protection, row.preparation_measures,
        row.operation_precautions, row.emergency_measures, row.guardian,
        row.site_guardian, row.dept_safety_officer,
        _canon(row.operations), _canon(row.phase_before),
        _canon(row.phase_ongoing), _canon(row.phase_after), row.source_id,
    )


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
    from app.modules.safety.models import KeyRiskOperationReport
    from app.modules.safety.service.key_risk_operation_report import (
        KeyRiskOperationReportService,
    )

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        mirror_rows = list((await db.scalars(
            select(KeyRiskOperationReport).where(
                KeyRiskOperationReport.is_deleted == False,  # noqa: E712
                KeyRiskOperationReport.source == "bitable",
            )
        )).all())
        svc = KeyRiskOperationReportService(db)

        _env_direct(True)
        views = await svc_open_all()
        _env_direct(False)
        print(f"镜像行={len(mirror_rows)} 直读视图={len(views)}")

        # ── 1. 台账全量 join + 内容 multiset ──
        mirror_by_fid = {r.feishu_record_id: r for r in mirror_rows if r.feishu_record_id}
        view_by_fid = {v.feishu_record_id: v for v in views if v.feishu_record_id}
        only_mirror = sorted(set(mirror_by_fid) - set(view_by_fid))
        only_view = sorted(set(view_by_fid) - set(mirror_by_fid))
        _record(not only_mirror and not only_view, "1a. feishu_record_id 集合一致",
                f"仅镜像={only_mirror[:3]} 仅直读={only_view[:3]}")
        common = sorted(set(mirror_by_fid) & set(view_by_fid))
        om, ov = _diff_multiset(
            _multiset([_row_key(mirror_by_fid[i]) for i in common]),
            _multiset([_row_key(view_by_fid[i]) for i in common]))
        _record(not om and not ov, "1b. 共同行内容 multiset 一致",
                f"公共行={len(common)} 差异 仅镜像={len(om)} 仅直读={len(ov)}")
        for k in om[:2]:
            print(f"      仅镜像: {k}")
        for k in ov[:2]:
            print(f"      仅直读: {k}")

        # ── 2. 列表过滤组合（service 双路径） ──
        cases: list[tuple[str, dict[str, Any]]] = [
            ("无过滤", {}),
            ("department", {"department": "提炼六部"}),
            ("apply_status", {"apply_status": "已通过"}),
            ("keyword", {"keyword": "检修"}),
        ]
        for label, kw in cases:
            _env_direct(False)
            m_items, m_total = await svc.get_reports(0, 100_000, **kw)
            _env_direct(True)
            d_items, d_total = await svc.get_reports(0, 100_000, **kw)
            _env_direct(False)
            om2, ov2 = _diff_multiset(
                _multiset([_row_key(r) for r in m_items]),
                _multiset([_row_key(v) for v in d_items]))
            _record(not om2 and not ov2 and m_total == d_total,
                    f"2. 列表 {label}",
                    f"total {m_total} vs {d_total}，内容差异 仅镜像={len(om2)}"
                    f" 仅直读={len(ov2)}")

        # 日期窗（近 30 天，边界安全窗口；两路径日界语义不同——API 路径均为北京日界）
        from datetime import date, timedelta

        today = date.today()
        _env_direct(False)
        m_items, m_total = await svc.get_reports(
            0, 100_000, date_from=today - timedelta(days=30), date_to=today)
        _env_direct(True)
        d_items, d_total = await svc.get_reports(
            0, 100_000, date_from=today - timedelta(days=30), date_to=today)
        _env_direct(False)
        om3, ov3 = _diff_multiset(
            _multiset([_row_key(r) for r in m_items]),
            _multiset([_row_key(v) for v in d_items]))
        _record(not om3 and not ov3 and m_total == d_total,
                "2b. 列表 日期窗(近30天)",
                f"total {m_total} vs {d_total}，差异 仅镜像={len(om3)} 仅直读={len(ov3)}")

        # ── 3. Agent 语义查询（真工具函数，ctx.db 注入会话） ──
        from app.modules.safety.business_agent.tools.read_tools import (
            query_key_risk_ops,
        )

        ctx = SimpleNamespace(deps=SimpleNamespace(db=db))
        _env_direct(False)
        agent_m = await query_key_risk_ops(ctx, department=None, date_from=None,
                                           date_to=None, apply_status=None,
                                           keyword=None, page=1, page_size=20)
        _env_direct(True)
        agent_d = await query_key_risk_ops(ctx, department=None, date_from=None,
                                           date_to=None, apply_status=None,
                                           keyword=None, page=1, page_size=20)
        _env_direct(False)
        keys_m = _multiset([json.dumps(i, ensure_ascii=False, sort_keys=True, default=str)
                            for i in agent_m["items"]])
        keys_d = _multiset([json.dumps(i, ensure_ascii=False, sort_keys=True, default=str)
                            for i in agent_d["items"]])
        om4, ov4 = _diff_multiset(keys_m, keys_d)
        _record(agent_m["total"] == agent_d["total"] and not om4 and not ov4,
                "3. Agent 查询（首页 20 条，行序归一）",
                f"total {agent_m['total']} vs {agent_d['total']}，"
                f"差异 仅镜像={len(om4)} 仅直读={len(ov4)}")

        # ── 4. stats ──
        _env_direct(False)
        stats_m = await svc.get_stats()
        _env_direct(True)
        stats_d = await svc.get_stats()
        _env_direct(False)
        _record(stats_m == stats_d, "4. get_stats 四 KPI", f"{stats_m} vs {stats_d}")

        # ── 5. 详情 id 双态 ──
        sample = mirror_by_fid.get(views[0].feishu_record_id) if views else None
        if sample is not None:
            _env_direct(False)
            by_uuid = await svc.get_report(sample.id)
            _env_direct(True)
            # 清缓存强拉（strict 语义经由 reader；此处直接 open_reader 强制）

            direct_view = await svc.get_report(views[0].feishu_record_id)
            _env_direct(False)
            _record(
                by_uuid is not None and direct_view is not None
                and _row_key(by_uuid) == _row_key(direct_view),
                "5. 详情 id 双态（UUID vs recXXX）",
                f"record_id={views[0].feishu_record_id}")
        else:
            _record(False, "5. 详情 id 双态", "无公共样本")

        # ── 6. 导出行集（渲染共用代码零改动，比对喂渲染的 items） ──
        _env_direct(False)
        m_items, _ = await svc.get_reports(0, 100_000)
        _env_direct(True)
        d_items, _ = await svc.get_reports(0, 100_000)
        _env_direct(False)
        om5, ov5 = _diff_multiset(
            _multiset([_row_key(r) for r in m_items]),
            _multiset([_row_key(v) for v in d_items]))
        _record(not om5 and not ov5, "6. 导出行集一致", f"行数 {len(m_items)} vs {len(d_items)}")

        # ── 7. 零回写探针 ──
        import httpx

        calls: list[str] = []
        real_post = httpx.AsyncClient.post

        async def _spy_post(self: Any, url: str, **kw: Any) -> Any:
            calls.append(str(url))
            return await real_post(self, url, **kw)

        httpx.AsyncClient.post = _spy_post  # type: ignore[method-assign]
        try:
            def _is_write(url: str) -> bool:
                u = str(url).split("?", 1)[0]
                return (u.endswith("/records") or "/records/batch_update" in u
                        or "/records/batch_create" in u or u.endswith("/fields"))

            calls.clear()
            _env_direct(True)
            await svc.get_reports(0, 20)
            await svc.get_stats()
            await svc.get_report(views[0].feishu_record_id)
            await svc.export_excel()
            _env_direct(False)
            writes = [u for u in calls if _is_write(u)]
            _record(not writes, "7. 直读查询/导出路径零 Bitable 写",
                    f"写端点调用 {len(writes)} / 总调用 {len(calls)}")
        finally:
            httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

        # ── 8. API 性能（缓存命中 <2s；首拉例外已落档） ──
        _env_direct(True)
        await svc.get_reports(0, 20)  # 预热缓存
        t0 = time.perf_counter()
        await svc.get_reports(0, 20)
        elapsed = time.perf_counter() - t0
        _env_direct(False)
        _record(elapsed < 2.0, "8. 缓存命中 get_reports <2s", f"{elapsed:.2f}s")
    finally:
        _env_direct(False)
        os.environ.pop(EVENT, None)
        await session_ctx.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS ==")
    return 1 if failed else 0


async def svc_open_all() -> list[Any]:
    """直读全量（strict 强制拉取，绕过缓存）。"""
    from app.modules.safety.service.key_risk_op_direct.reader import open_reader

    return await open_reader().fetch_all(strict=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
