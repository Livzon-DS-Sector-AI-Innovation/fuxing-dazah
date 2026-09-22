"""双路径比对 + 零回写探针（emergency-drill-direct Ticket 06，照 verify_contractor_dual 方法学）。

前置：先跑 backfill_emergency_drill_mirror.py 回填本地镜像；
本地开关保持全关（本脚本内部按比对项临时拨开关，结束恢复）。
本脚本只调用查询路径——不触碰事件 handler、评估/方案生成、推送面
（本域无推送任务；惯例仍全程零写断言兜底）。

比对项：
  1. 主表全量：镜像 ORM vs 直读视图按 feishu_record_id join + 业务字段 multiset
     （附件=存储路径推算，两侧应逐字相等——D4 强校验；created_at/updated_at/
     eval_source_record_file_token 为受控偏差不入键：镜像 insert/update 时刻与
     平台去重 token，Bitable 无此三值，spec §0）；
  2. 列表过滤组合（service 双路径）：无/department/drill_type/status/keyword/
     stage=plan|execution|review；默认排序差异为 D3 受控偏差——按 multiset 比对，
     另断言直读序列 plan_time_ref desc NULLS LAST 自洽；
  3. stats：total/executed/completed/pending/by_type/by_department 逐字段；
  4. 详情 id 双态：resolve_record(recXXX)（直读）vs resolve_record(UUID)（镜像行）
     业务字段一致；
  5. Agent 查询：query_drill_plans / query_drill_records 双路径 items/total 比对
     （id 双态不入键）；
  6. 零回写探针：直读查询路径 Bitable 写端点（records 写/media/fields）调用数 = 0；
  7. API 性能：直读 list_records <2s（112 行单页，无缓存）。

退出码：0 全 PASS；1 有 FAIL。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

DIRECT = "SAFETY_EMERGENCY_DRILL_DIRECT_ENABLED"

results: list[tuple[bool, str, str]] = []


def _record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"：{detail}" if detail else ""))


def _env_direct(on: bool) -> None:
    if on:
        os.environ[DIRECT] = "true"
    else:
        os.environ.pop(DIRECT, None)


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


def _norm_val(v: Any) -> Any:
    """路径分隔符归一（Windows 本地模式 store_bytes 反斜杠 vs 直读正斜杠）。"""
    if isinstance(v, str):
        return v.replace("\\", "/")
    if isinstance(v, list):
        return [_norm_val(x) for x in v]
    return v


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import EmergencyDrillRecord
    from app.modules.safety.service.emergency_drill import EmergencyDrillService
    from app.modules.safety.service.emergency_drill_direct.reader import open_reader
    from app.modules.safety.service.emergency_drill_direct.views import (
        mapped_field_keys,
    )

    keys = mapped_field_keys()

    def _row_key(obj: Any) -> tuple:
        return tuple(
            (k, repr(_norm_val(getattr(obj, k, None)))) for k in keys
        )

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        mirror_rows = list((await db.scalars(
            select(EmergencyDrillRecord).where(
                EmergencyDrillRecord.is_deleted == False,  # noqa: E712
                EmergencyDrillRecord.feishu_record_id.isnot(None),
            )
        )).all())
        svc = EmergencyDrillService(db)

        _env_direct(True)
        views = await open_reader().fetch_all(strict=True)
        _env_direct(False)
        print(f"镜像行={len(mirror_rows)} 直读视图={len(views)}")

        # ── 1. 主表全量 join + 业务字段 multiset ──
        mirror_by_fid = {r.feishu_record_id: r for r in mirror_rows}
        view_by_fid = {v.id: v for v in views}
        only_mirror = sorted(set(mirror_by_fid) - set(view_by_fid))
        only_view = sorted(set(view_by_fid) - set(mirror_by_fid))
        # gotchas#10 归因：仅镜像 = Bitable 已无对应行的幽灵行（删除事件丢失/
        # 历史遗留，字段近乎全空、rec id 形态异常），方向为直读更正确
        # （Bitable 为源，生产开 DIRECT 后页面将不再显示这批行——HANDOFF 落档）；
        # 仅直读非空才是真漂移（回填漏行）。
        ghost_ids = set(only_mirror)
        _record(not only_view, "1a. feishu_record_id 集合一致（幽灵行归因）",
                f"镜像幽灵行={len(ghost_ids)}（直读为准，不参与后续比对）"
                f" 仅直读={only_view[:3] or '无'}")
        if ghost_ids:
            ghost_rows = [mirror_by_fid[i] for i in only_mirror[:3]]
            for g in ghost_rows:
                print(f"      幽灵样例: fid={g.feishu_record_id}"
                      f" content={(g.drill_content or '')[:20]}"
                      f" created_at={g.created_at}")

        common = sorted(set(mirror_by_fid) & set(view_by_fid))
        om, ov = _diff_multiset(
            _multiset([_row_key(mirror_by_fid[i]) for i in common]),
            _multiset([_row_key(view_by_fid[i]) for i in common]))
        _record(not om and not ov, "1b. 共同行业务字段 multiset 一致（附件路径强校验）",
                f"公共行={len(common)} 差异 仅镜像={len(om)} 仅直读={len(ov)}")
        for k in om[:3]:
            print(f"      仅镜像: {k}")
        for k in ov[:3]:
            print(f"      仅直读: {k}")

        # ── 2. 列表过滤组合（service 双路径；排序差异 D3 受控→multiset 比对；
        #      镜像侧剔除幽灵行后比 total 与内容） ──
        cases: list[tuple[str, dict[str, Any]]] = [
            ("无过滤", {}),
            ("department", {"department": "设备动力部"}),
            ("drill_type", {"drill_type": "应急疏散演练"}),
            ("status=已完成", {"status": "已完成"}),
            ("keyword", {"keyword": "疏散"}),
            ("stage=plan", {"stage": "plan"}),
            ("stage=execution", {"stage": "execution"}),
            ("stage=review", {"stage": "review"}),
            ("组合", {"stage": "execution", "drill_type": "现场岗位处置"}),
        ]
        for label, kw in cases:
            _env_direct(False)
            m_items, m_total = await svc.list_records(0, 100_000, **kw)
            _env_direct(True)
            d_items, d_total = await svc.list_records(0, 100_000, **kw)
            _env_direct(False)
            m_common = [r for r in m_items
                        if r.feishu_record_id not in ghost_ids]
            om2, ov2 = _diff_multiset(
                _multiset([_row_key(r) for r in m_common]),
                _multiset([_row_key(v) for v in d_items]))
            _record(not om2 and not ov2 and len(m_common) == d_total,
                    f"2. 列表 {label}",
                    f"total 镜像(剔幽灵) {len(m_common)} vs 直读 {d_total}"
                    f"（镜像原值 {m_total}），内容差异 仅镜像={len(om2)}"
                    f" 仅直读={len(ov2)}")

        # 直读默认排序自洽：plan_time_ref desc NULLS LAST（D3）
        _env_direct(True)
        d_items, _ = await svc.list_records(0, 100_000)
        _env_direct(False)
        seq = [v.plan_time_ref for v in d_items]
        non_null = [d for d in seq if d is not None]
        nulls_first_half = seq[len(seq) - seq.count(None):] if seq.count(None) else []
        ordered_ok = (
            non_null == sorted(non_null, reverse=True)
            and all(d is None for d in nulls_first_half)
        )
        _record(ordered_ok, "2b. 直读默认排序 plan_time_ref desc NULLS LAST 自洽（D3）",
                f"非空 {len(non_null)} 行降序自洽={non_null == sorted(non_null, reverse=True)}"
                f" 空值 {seq.count(None)} 行全在末尾")

        # ── 3. stats（镜像侧含幽灵行：KPI 按「剔幽灵后」口径；by_* 分组打印对照） ──
        _env_direct(False)
        stats_m = (await svc.get_stats()).model_dump()
        _env_direct(True)
        stats_d = (await svc.get_stats()).model_dump()
        _env_direct(False)
        ghost_exec = sum(1 for i in ghost_ids
                         if mirror_by_fid[i].execution_time is not None)
        ghost_done = sum(1 for i in ghost_ids
                         if mirror_by_fid[i].status == "已完成")
        adj = {
            "total": stats_m["total"] - len(ghost_ids),
            "executed": stats_m["executed"] - ghost_exec,
            "completed": stats_m["completed"] - ghost_done,
        }
        adj["pending"] = adj["total"] - adj["completed"]
        diff = [f"{k} {adj[k]} vs {stats_d[k]}"
                for k in ("total", "executed", "completed", "pending")
                if adj[k] != stats_d[k]]
        _record(not diff, "3. stats KPI 逐字段一致（镜像剔幽灵口径）",
                ("；".join(diff)) if diff else
                f"total/executed/completed/pending = {stats_d['total']}"
                f"/{stats_d['executed']}/{stats_d['completed']}"
                f"/{stats_d['pending']}（幽灵行 {len(ghost_ids)} 已扣减）")
        print(f"      by_type 直读={stats_d['by_type']}")
        print(f"      by_department 直读={stats_d['by_department']}")

        # ── 4. 详情 id 双态 ──
        sample = next((v for v in views if v.signin_file or v.drill_record_file),
                      views[0] if views else None)
        by_rec = None
        if sample is not None:
            _env_direct(True)
            by_rec = await svc.resolve_record(sample.id)
            _env_direct(False)
        sample_row = mirror_by_fid.get(sample.id) if sample else None
        by_uuid = None
        if sample_row is not None:
            by_uuid = await svc.resolve_record(str(sample_row.id))
        if sample is not None and by_rec is not None and sample_row is not None:
            _record(_row_key(by_uuid) == _row_key(by_rec),
                    "4a. 详情 id 双态（UUID→镜像行 vs recXXX→直读视图）",
                    f"record_id={sample.id}")
            _record(_row_key(sample_row) == _row_key(by_rec),
                    "4b. 详情镜像行 vs 直读视图业务字段一致", "")
        else:
            _record(False, "4. 详情 id 双态", "无公共样本")

        # ── 5. Agent 查询（真工具函数，ctx.db 注入会话） ──
        from app.modules.safety.business_agent.tools.read_tools import (
            query_drill_plans,
            query_drill_records,
        )

        def _strip_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            # id 双态（镜像 UUID vs 直读 recXXX）不入比对
            return [{k: v for k, v in i.items() if k != "id"} for i in items]

        uuid_to_fid = {str(r.id): r.feishu_record_id for r in mirror_rows}

        def _drop_ghosts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """镜像侧剔除幽灵行（item.id=UUID → fid 不在 Bitable）。"""
            return [i for i in items
                    if uuid_to_fid.get(i["id"], "") not in ghost_ids]

        ctx = SimpleNamespace(deps=SimpleNamespace(db=db))
        for tool_name, tool in (("query_drill_plans", query_drill_plans),
                                ("query_drill_records", query_drill_records)):
            _env_direct(False)
            agent_m = await tool(ctx, department=None, status=None,
                                 drill_type=None, keyword=None, limit=1000)
            _env_direct(True)
            agent_d = await tool(ctx, department=None, status=None,
                                 drill_type=None, keyword=None, limit=1000)
            _env_direct(False)
            m_kept = _drop_ghosts(agent_m["items"])
            keys_m = _multiset([json.dumps(i, ensure_ascii=False, sort_keys=True,
                                           default=str)
                                for i in _strip_id(m_kept)])
            keys_d = _multiset([json.dumps(i, ensure_ascii=False, sort_keys=True,
                                           default=str)
                                for i in _strip_id(agent_d["items"])])
            om3, ov3 = _diff_multiset(keys_m, keys_d)
            _record(not om3 and not ov3 and len(m_kept) == len(agent_d["items"]),
                    f"5. Agent {tool_name} 全量内容（行序归一，id 双态不入键，"
                    f"镜像剔幽灵）",
                    f"total 镜像(剔幽灵) {len(m_kept)} vs 直读 "
                    f"{len(agent_d['items'])}（镜像原值 {agent_m['total']}），"
                    f"差异 仅镜像={len(om3)} 仅直读={len(ov3)}")
            for k in om3[:2]:
                print(f"      仅镜像: {k}")
            for k in ov3[:2]:
                print(f"      仅直读: {k}")

        # ── 6. 零回写探针 ──
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
                        or "/records/batch_create" in u or u.endswith("/fields")
                        or "/media/upload_all" in u or "/drive/v1/medias" in u)

            calls.clear()
            _env_direct(True)
            await svc.list_records(0, 20)
            await svc.get_stats()
            if sample is not None:
                await svc.resolve_record(sample.id)
            _env_direct(False)
            writes = [u for u in calls if _is_write(u)]
            _record(not writes, "6. 直读查询路径零 Bitable 写",
                    f"写端点调用 {len(writes)} / 总调用 {len(calls)}")
        finally:
            httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

        # ── 7. API 性能（直读全量 <2s；无缓存） ──
        _env_direct(True)
        await svc.list_records(0, 1)  # 预热（连接/解析）
        t0 = time.perf_counter()
        await svc.list_records(0, 20)
        elapsed = time.perf_counter() - t0
        _env_direct(False)
        _record(elapsed < 2.0, "7. 直读 list_records <2s（无缓存）", f"{elapsed:.2f}s")
    finally:
        _env_direct(False)
        await session_ctx.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS ==")
    return 1 if failed else 0


if __name__ == "__main__":
    _dt = datetime.now(tz=UTC)
    print(f"verify_emergency_drill_dual @ {_dt.isoformat()}")
    sys.exit(asyncio.run(main()))
