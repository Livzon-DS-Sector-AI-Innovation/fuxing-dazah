"""双路径比对 + 零回写探针（contractor-admission-direct Ticket 08，照 verify_key_risk_dual 方法学）。

前置：先跑 backfill_contractor_mirror.py 回填本地镜像（本地镜像 AI 审核字段为空——
upsert 不带 ai_*，AI 派生态断言只对直读侧做完整性校验，不与本地镜像比）；
本地开关保持全关（本脚本内部按比对项临时拨开关，结束恢复）。

安全：触发器 fire_and_forget 全程替换为记录器——本地镜像为空时 98 个协议挂载行
会被视为「新记录」，不替换会向生产触发真实 AI 审核。

比对项：
  1. 台账全量：镜像 ORM vs 直读视图按 feishu_record_id join + mapped_diff_key
     内容 multiset（附件只比 file_token；created_at 为受控偏差不入键——镜像
     insert 时刻 vs Bitable 创建日期）；
  2. 列表过滤组合（service 双路径）：无/相关方类型/提交状态/AI态(none|completed)/
     ai_conclusion/keyword；ai_review_status=processing|failed 直读恒空（口径断言）；
  3. stats：total + by_related_party_type + by_submit_status 逐字段；
     by_ai_review_status 打印对照（镜像含 processing/failed/None，直读只含
     none/completed——spec §4.2 已拍板口径）；
  4. 详情 id 双态：resolve_detail(recXXX) vs resolve_detail(UUID) 内容一致 +
     legacy UUID vs 直读 recXXX 业务字段一致；
  5. Agent 查询：read_tools 双路径 items/total 比对（首页 20，行序归一）；
  6. 零回写探针：直读查询路径 Bitable 写端点调用数 = 0；
  7. API 性能：直读 get_list <2s（109 行单页）。

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

DIRECT = "SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED"
EVENT = "SAFETY_CONTRACTOR_ADMISSION_EVENT_SYNC_ENABLED"

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


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import ContractorAdmission
    from app.modules.safety.service.contractor_admission import (
        ContractorAdmissionService,
    )
    from app.modules.safety.service.contractor_admission_direct import trigger
    from app.modules.safety.service.contractor_admission_direct.contract import (
        CONCLUSION_VALUES,
        DEFECT_CATEGORY_VALUES,
    )
    from app.modules.safety.service.contractor_admission_direct.reader import (
        open_reader,
    )
    from app.modules.safety.service.contractor_admission_direct.views import (
        mapped_diff_key,
        mapped_field_keys,
    )

    # ── 安全阀：触发器只记录不执行（防误触生产 AI 审核） ──
    fired: list[str] = []
    trigger.fire_and_forget = lambda candidates: (  # type: ignore[method-assign]
        fired.extend(rid for rid, _ in candidates) or 0
    )

    keys = mapped_field_keys()

    def _row_key(obj: Any) -> tuple:
        return mapped_diff_key({k: getattr(obj, k) for k in keys})

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        mirror_rows = list((await db.scalars(
            select(ContractorAdmission).where(
                ContractorAdmission.is_deleted == False,  # noqa: E712
                ContractorAdmission.source == "bitable",
            )
        )).all())
        svc = ContractorAdmissionService(db)

        _env_direct(True)
        views = await open_reader().fetch_all(strict=True)
        _env_direct(False)
        print(f"镜像行={len(mirror_rows)} 直读视图={len(views)} 触发器记录={len(fired)}(不执行)")

        # ── 1. 台账全量 join + 内容 multiset（业务字段；created_at 受控偏差不入键） ──
        mirror_by_fid = {r.feishu_record_id: r for r in mirror_rows if r.feishu_record_id}
        view_by_fid = {v.id: v for v in views}
        only_mirror = sorted(set(mirror_by_fid) - set(view_by_fid))
        only_view = sorted(set(view_by_fid) - set(mirror_by_fid))
        _record(not only_mirror and not only_view, "1a. feishu_record_id 集合一致",
                f"仅镜像={only_mirror[:3]} 仅直读={only_view[:3]}")
        common = sorted(set(mirror_by_fid) & set(view_by_fid))
        om, ov = _diff_multiset(
            _multiset([_row_key(mirror_by_fid[i]) for i in common]),
            _multiset([_row_key(view_by_fid[i]) for i in common]))
        _record(not om and not ov, "1b. 共同行业务字段 multiset 一致",
                f"公共行={len(common)} 差异 仅镜像={len(om)} 仅直读={len(ov)}")
        for k in om[:2]:
            print(f"      仅镜像: {k}")
        for k in ov[:2]:
            print(f"      仅直读: {k}")

        # ── 2. 列表过滤组合（service 双路径） ──
        cases: list[tuple[str, dict[str, Any]]] = [
            ("无过滤", {}),
            ("related_party_type", {"related_party_type": "承包商"}),
            ("submit_status", {"submit_status": "已完成"}),
            ("ai_review_status=none", {"ai_review_status": "none"}),
            ("ai_review_status=completed", {"ai_review_status": "completed"}),
            ("keyword", {"keyword": "公司"}),
        ]
        for label, kw in cases:
            _env_direct(False)
            m_items, m_total = await svc.get_list(dict(kw), page=1, page_size=100_000)
            _env_direct(True)
            d_items, d_total = await svc.get_list(dict(kw), page=1, page_size=100_000)
            _env_direct(False)
            om2, ov2 = _diff_multiset(
                _multiset([_row_key(r) for r in m_items]),
                _multiset([_row_key(v) for v in d_items]))
            _record(not om2 and not ov2 and m_total == d_total,
                    f"2. 列表 {label}",
                    f"total {m_total} vs {d_total}，内容差异 仅镜像={len(om2)}"
                    f" 仅直读={len(ov2)}")

        # 派生态不可表达口径：processing/failed 直读恒空
        _env_direct(True)
        p_items, _ = await svc.get_list({"ai_review_status": "processing"},
                                        page=1, page_size=100)
        f_items, _ = await svc.get_list({"ai_review_status": "failed"},
                                        page=1, page_size=100)
        _env_direct(False)
        _record(not p_items and not f_items,
                "2b. ai_review_status=processing|failed 直读恒空（spec §4.2）",
                f"processing={len(p_items)} failed={len(f_items)}")

        # ai_conclusion 过滤（派生 overall_conclusion）
        _env_direct(True)
        c_items, c_total = await svc.get_list({"ai_conclusion": "需补充完善"},
                                              page=1, page_size=100_000)
        _env_direct(False)
        expect_c = sum(
            1 for v in views
            if (v.ai_review_result or {}).get("overall_conclusion") == "需补充完善"
        )
        _record(c_total == expect_c, "2c. ai_conclusion 过滤与派生态一致",
                f"total={c_total} 派生口径={expect_c}")

        # 排序样本（审查 MINOR-1：DoD §7 排序抽组）
        # - 日期列：键序列严格相等（collation-free，tie 不敏感，NULLS 口径体现在两端）
        # - 文本列：PG collation 与 Python 码点序对中文固有不同序（诊断脚本实证，
        #   两边各自自洽——query.py 已落档边界），只断言 集合一致 + 直读序列码点自洽
        def _canon_val(v: Any) -> str:
            return "<null>" if v is None else str(v)

        _env_direct(False)
        m_items, m_total = await svc.get_list(
            {"sort_by": "entry_date", "sort_order": "asc"}, page=1, page_size=100_000)
        _env_direct(True)
        d_items, d_total = await svc.get_list(
            {"sort_by": "entry_date", "sort_order": "asc"}, page=1, page_size=100_000)
        _env_direct(False)
        om2, ov2 = _diff_multiset(
            _multiset([_row_key(r) for r in m_items]),
            _multiset([_row_key(v) for v in d_items]))
        m_seq = [_canon_val(r.entry_date) for r in m_items]
        d_seq = [_canon_val(v.entry_date) for v in d_items]
        _record(not om2 and not ov2 and m_total == d_total and m_seq == d_seq,
                "2d. 列表 entry_date asc（NULLS LAST，键序列严格相等）",
                f"total {m_total} vs {d_total}，键序列一致={m_seq == d_seq}")

        _env_direct(False)
        m_items, m_total = await svc.get_list(
            {"sort_by": "company_name", "sort_order": "desc"}, page=1, page_size=100_000)
        _env_direct(True)
        d_items, d_total = await svc.get_list(
            {"sort_by": "company_name", "sort_order": "desc"}, page=1, page_size=100_000)
        _env_direct(False)
        om2, ov2 = _diff_multiset(
            _multiset([_row_key(r) for r in m_items]),
            _multiset([_row_key(v) for v in d_items]))
        d_names = [v.company_name for v in d_items if v.company_name is not None]
        _record(not om2 and not ov2 and m_total == d_total
                and d_names == sorted(d_names, reverse=True),
                "2d. 列表 company_name desc（文本列 collation 边界：集合一致+直读自洽）",
                f"total {m_total} vs {d_total}，内容差异 仅镜像={len(om2)}"
                f" 仅直读={len(ov2)}，直读码点降序自洽="
                f"{d_names == sorted(d_names, reverse=True)}")

        # ── 3. stats ──
        _env_direct(False)
        stats_m = await svc.get_stats()
        _env_direct(True)
        stats_d = await svc.get_stats()
        _env_direct(False)
        same_except_ai = (
            stats_m.get("total") == stats_d.get("total")
            and stats_m.get("by_related_party_type") == stats_d.get("by_related_party_type")
            and stats_m.get("by_submit_status") == stats_d.get("by_submit_status")
        )
        _record(same_except_ai,
                "3. stats total/by_party/by_submit 逐字段一致",
                f"by_ai_review_status 镜像={stats_m.get('by_ai_review_status')}"
                f" 直读={stats_d.get('by_ai_review_status')}"
                f"（processing/failed 不可表达，spec §4.2）")

        # ── 4. 详情 id 双态 ──
        sample_view = views[0]
        _env_direct(True)
        by_rec = await svc.resolve_detail(sample_view.id)
        _env_direct(False)
        sample_row = mirror_by_fid.get(sample_view.id)
        by_uuid_direct = None
        if sample_row is not None:
            _env_direct(True)
            by_uuid_direct = await svc.resolve_detail(str(sample_row.id))
            _env_direct(False)
        if sample_row is not None and by_rec is not None:
            _record(
                by_uuid_direct is not None
                and _row_key(by_uuid_direct) == _row_key(by_rec),
                "4a. 详情 id 双态（recXXX vs UUID→直读视图）",
                f"record_id={sample_view.id}")
            _record(
                _row_key(sample_row) == _row_key(by_rec),
                "4b. 详情 legacy UUID（镜像）vs 直读 recXXX 业务字段一致",
                "")
        else:
            _record(False, "4. 详情 id 双态", "无公共样本")

        # ── 5. Agent 查询（真工具函数，ctx.db 注入会话） ──
        from app.modules.safety.business_agent.tools.read_tools import (
            query_contractor_admissions,
        )

        def _strip_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            # id 双态（镜像 UUID vs 直读 recXXX，spec §4.5 拍板）不入比对
            return [{k: v for k, v in i.items() if k != "id"} for i in items]

        ctx = SimpleNamespace(deps=SimpleNamespace(db=db))
        # 20 条窗口只验证分页行为（两路径默认排序键天然不同：镜像 insert 时刻 vs
        # Bitable 创建日期，首页窗口本就不是同一批行）；内容比对用全量页 multiset
        _env_direct(False)
        agent_m_page = await query_contractor_admissions(
            ctx, related_party_type=None, submit_status=None,
            ai_review_status=None, keyword=None, page=1, page_size=20)
        agent_m = await query_contractor_admissions(
            ctx, related_party_type=None, submit_status=None,
            ai_review_status=None, keyword=None, page=1, page_size=500)
        _env_direct(True)
        agent_d_page = await query_contractor_admissions(
            ctx, related_party_type=None, submit_status=None,
            ai_review_status=None, keyword=None, page=1, page_size=20)
        agent_d = await query_contractor_admissions(
            ctx, related_party_type=None, submit_status=None,
            ai_review_status=None, keyword=None, page=1, page_size=500)
        _env_direct(False)
        _record(len(agent_m_page["items"]) == 20 and len(agent_d_page["items"]) == 20
                and agent_m_page["total"] == agent_d_page["total"],
                "5a. Agent 分页窗口（20 条 + total 一致）",
                f"total {agent_m['total']} vs {agent_d['total']}")
        keys_m = _multiset([json.dumps(i, ensure_ascii=False, sort_keys=True, default=str)
                            for i in _strip_id(agent_m["items"])])
        keys_d = _multiset([json.dumps(i, ensure_ascii=False, sort_keys=True, default=str)
                            for i in _strip_id(agent_d["items"])])
        om4, ov4 = _diff_multiset(keys_m, keys_d)
        _record(not om4 and not ov4,
                "5b. Agent 查询全量内容（行序归一，id 双态不入键）",
                f"items {len(agent_m['items'])} vs {len(agent_d['items'])}，"
                f"差异 仅镜像={len(om4)} 仅直读={len(ov4)}")
        for k in om4[:2]:
            print(f"      仅镜像: {k}")
        for k in ov4[:2]:
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
                        or "/records/batch_create" in u or u.endswith("/fields"))

            calls.clear()
            fired.clear()
            _env_direct(True)
            await svc.get_list({}, page=1, page_size=20)
            await svc.get_stats()
            await svc.resolve_detail(sample_view.id)
            _env_direct(False)
            writes = [u for u in calls if _is_write(u)]
            _record(not writes, "6. 直读查询路径零 Bitable 写",
                    f"写端点调用 {len(writes)} / 总调用 {len(calls)}；"
                    f"触发器记录={len(fired)}(未执行)")
        finally:
            httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

        # ── 7. AI 派生态完整性（直读侧；本地镜像 ai_* 恒空不比） ──
        completed = [v for v in views if v.ai_review_status == "completed"]
        none_cnt = sum(1 for v in views if v.ai_review_status == "none")
        ok_ai = all(
            (v.ai_review_result or {}).get("overall_conclusion") in CONCLUSION_VALUES
            and all(d in DEFECT_CATEGORY_VALUES
                    for d in (v.ai_review_result or {}).get("defect_categories", []))
            and (v.ai_review_result or {}).get("agreement") is None
            and (v.ai_review_result or {}).get("regulations") == []
            and v.ai_error_message is None
            for v in completed
        ) and all(v.ai_review_result is None for v in views
                  if v.ai_review_status == "none")
        _record(ok_ai and completed and none_cnt + len(completed) == len(views),
                "7. AI 派生态完整（completed 值域/none 空/两态互斥）",
                f"completed={len(completed)} none={none_cnt}（探针基线 16，生产漂移属正常）")

        # ── 8. API 性能（直读全量 <2s；无缓存——D3） ──
        _env_direct(True)
        await svc.get_list({}, page=1, page_size=1)  # 预热（连接/解析）
        t0 = time.perf_counter()
        await svc.get_list({}, page=1, page_size=20)
        elapsed = time.perf_counter() - t0
        _env_direct(False)
        _record(elapsed < 2.0, "8. 直读 get_list <2s（无缓存，D3）", f"{elapsed:.2f}s")
    finally:
        _env_direct(False)
        os.environ.pop(EVENT, None)
        await session_ctx.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS ==")
    return 1 if failed else 0


if __name__ == "__main__":
    _dt = datetime.now(tz=UTC)
    print(f"verify_contractor_dual @ {_dt.isoformat()}")
    sys.exit(asyncio.run(main()))
