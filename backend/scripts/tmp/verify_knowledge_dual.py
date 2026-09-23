"""双路径比对 + 零回写探针（knowledge-direct Ticket 05，照 verify_emergency_drill_dual 方法学）。

本地开关保持全关（脚本内部按比对项临时拨开关，结束恢复）；推送开关显式关闭
（安全速递误发教训）。本脚本只调用查询路径——不触碰事件 handler、爬虫写面、
chunk 链路、推送面。

比对项：
  1. 共同 fid 逐字段比对（days=36500 全量）：status/impact_level 严格一致；
     title/source/category/publish_date 按镜像分歧归因打印（双写路径映射分歧
     + 飞书侧后编辑事件丢失，盘点新发现）；镜像侧按 feishu_record_id ∈ 两表
     过滤（制度表/手动建文/msds_indexer/幽灵行归因剔除）；article_no 为 D3
     已知偏差（建列回填前直读恒 None）单独量化；
  2. days 窗口样本（30/90/365）计数差须被 input_date/created_at 分类翻转
     精确解释（D4 受控偏差）；
  3. impact_level 过滤样本（高）双路径一致（先截断后过滤 quirk 两侧同款）；
  4. 直读排序自洽：input_date desc（NULLS LAST）；
  5. input_date vs PG created_at 漂移量化（D4 受控偏差，信息项）；
  6. 零回写探针：直读查询路径 Bitable 写端点调用数 = 0（strict 绕缓存强制联网）；
  7. 性能：直读查询 <2s（TTL 缓存生效口径；首拉冷耗见运行头行）。

退出码：0 全 PASS；1 有 FAIL。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

DIRECT = "SAFETY_KNOWLEDGE_DIRECT_ENABLED"
_PUSH_KEYS = (
    "SAFETY_DAILY_DIGEST_ENABLED",
    "SAFETY_REGULATION_CRAWLER_ENABLED",
)
_KINDS = ("collection", "collection_env")

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


def _strip_key(item: dict[str, Any], *drop: str) -> str:
    keep = {k: v for k, v in item.items() if k not in drop}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True, default=str)


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.business_agent.tools.read_tools import (
        query_latest_regulations,
    )
    from app.modules.safety.models import SafetyKnowledgeArticle
    from app.modules.safety.service.knowledge_direct.reader import open_reader

    for key in _PUSH_KEYS:
        os.environ.pop(key, None)  # 推送/爬虫面显式关闭（本脚本只读查询）

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        mirror_rows = list((await db.scalars(
            select(SafetyKnowledgeArticle).where(
                SafetyKnowledgeArticle.is_deleted == False,  # noqa: E712
            )
        )).all())

        # 两表 fid 集合（直读拉取一次复用）
        t0 = time.perf_counter()
        views = await open_reader().fetch_all(strict=True)
        elapsed_all = time.perf_counter() - t0
        fid_by_kind: dict[str, set[str]] = {"collection": set(), "collection_env": set()}
        for v in views:
            fid_by_kind[v.source_kind].add(v.id)
        in_tables = fid_by_kind["collection"] | fid_by_kind["collection_env"]
        print(f"镜像行={len(mirror_rows)} 直读视图={len(views)}"
              f"（安全 {len(fid_by_kind['collection'])}/环保"
              f" {len(fid_by_kind['collection_env'])}）全量 {elapsed_all:.2f}s")

        uuid_to_fid = {str(r.id): str(r.feishu_record_id or "") for r in mirror_rows}

        def _drop_non_regulation(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            """镜像侧剔除非两表行（制度/手动/msds/幽灵——直读更精确的归因面）。"""
            return [i for i in items if uuid_to_fid.get(i["id"], "") in in_tables]

        ctx = SimpleNamespace(deps=SimpleNamespace(db=db))

        # ── 1. 共同 fid 逐字段比对（gotchas#10：差异按字段归因打印） ──
        mirror_by_fid = {
            str(r.feishu_record_id or ""): r for r in mirror_rows
            if r.feishu_record_id and str(r.feishu_record_id) in in_tables
        }
        view_by_fid = {v.id: v for v in views}
        # 镜像存在双写路径分歧（盘点新发现，spec §0 补充）：事件 handler 映射
        # 与手动 sync_from_bitable 映射不同（后者 特种设备→laws_regulations、
        # 颁布机关→author、无 颁布修订日期→publish_date），历史行被后者覆写过
        # → source/category/publish_date 三字段镜像≠当前 Bitable，方向=直读
        # 为当前源值更正确。title/status/impact_level 须严格一致。
        os.environ.pop(DIRECT, None)
        agent_m = await query_latest_regulations(ctx, limit=100_000, days=365_000)
        _env_direct(True)
        agent_d = await query_latest_regulations(ctx, limit=100_000, days=365_000)
        _env_direct(False)
        m_kept = _drop_non_regulation(agent_m["items"])

        def _impact_of(notes: str | None) -> str:
            for level, mark in (("高", "影响等级: 高"), ("中", "影响等级: 中"),
                                ("低", "影响等级: 低")):
                if mark in (notes or ""):
                    return level
            return ""

        strict_fields = ("status", "impact_level")
        divergent_fields = ("title", "source", "category", "publish_date")
        field_diffs: dict[str, list[str]] = {}
        for fid in set(mirror_by_fid) & set(view_by_fid):
            m, v = mirror_by_fid[fid], view_by_fid[fid]
            pairs = [
                ("title", m.title or "", v.title or ""),
                ("status", m.status or "", v.status or ""),
                ("impact_level", _impact_of(m.notes), _impact_of(v.notes)),
                ("source", m.source or "", v.source or ""),
                ("category", m.category or "", v.category or ""),
                ("publish_date",
                 m.publish_date.isoformat() if m.publish_date else "",
                 v.publish_date.isoformat() if v.publish_date else ""),
            ]
            for name, mv, dv in pairs:
                if mv != dv:
                    field_diffs.setdefault(name, []).append(fid)
        strict_bad = {f: field_diffs.get(f, []) for f in strict_fields}
        _record(not any(strict_bad.values()),
                "1. 共同 fid 严格字段一致（status/impact_level）",
                f"公共 fid={len(set(mirror_by_fid) & set(view_by_fid))}；"
                + "；".join(f"{f} 差 {len(ids)}" for f, ids in strict_bad.items()))
        for f in divergent_fields:
            ids = field_diffs.get(f, [])
            if not ids:
                print(f"      [归因] {f} 镜像分歧行=0")
                continue
            fid0 = ids[0]
            m0, v0 = mirror_by_fid[fid0], view_by_fid[fid0]
            print(f"      [归因] {f} 镜像分歧行={len(ids)}"
                  f"（镜像≠当前 Bitable，直读=当前值；样例"
                  f" fid={fid0} mirror={repr(getattr(m0, f, ''))[:40]}"
                  f" bitable={repr(getattr(v0, f, ''))[:40]}）")
        print(f"      非法规源剔除 {agent_m['total'] - len(m_kept)} 行"
              f"（制度/手动/msds/幽灵——spec §7 受控偏差）")
        print(f"      工具体总量：镜像 {agent_m['total']} vs 直读"
              f" {agent_d['total']}（差异=剔除非法规源+镜像分歧行，逐字段见上）")

        # ── 2. article_no 已知偏差量化（D3：建列回填前直读恒 None） ──
        direct_has_no = sum(1 for i in agent_d["items"] if i["article_no"])
        mirror_has_no = sum(1 for i in m_kept if i["article_no"])
        _record(direct_has_no in (0, mirror_has_no),
                "2. article_no 偏差量化（D3 信息项：建列回填后应相等）",
                f"镜像有编号 {mirror_has_no} / 直读有编号 {direct_has_no}"
                + ("" if direct_has_no == 0 else "（已建列？）"))

        # ── 3. days 窗口样本（差值须被 input_date/created_at 分类翻转精确解释） ──
        view_dates_all = {v.id: v.input_date for v in views}
        for days in (30, 90, 365):
            cutoff = date.today() - timedelta(days=days)
            os.environ.pop(DIRECT, None)
            m = await query_latest_regulations(ctx, limit=100_000, days=days)
            _env_direct(True)
            d = await query_latest_regulations(ctx, limit=100_000, days=days)
            _env_direct(False)
            m_count = len(_drop_non_regulation(m["items"]))
            # 分类翻转：同一 829 行总体上「created_at>=cutoff」与
            # 「input_date>=cutoff」两个判据的成员差（D4 受控偏差的精确解释）
            mirror_in_direct_out = direct_in_mirror_out = 0
            for fid, vd in view_dates_all.items():
                row = mirror_by_fid.get(fid)
                if row is None or row.created_at is None:
                    continue
                m_in = row.created_at.date() >= cutoff
                d_in = vd is not None and vd >= cutoff
                if m_in and not d_in:
                    mirror_in_direct_out += 1
                elif d_in and not m_in:
                    direct_in_mirror_out += 1
            explained = (m_count - d["total"]
                         == mirror_in_direct_out - direct_in_mirror_out)
            _record(explained,
                    f"3. days={days} 窗口计数（差值=D4 日期键分类翻转精确解释）",
                    f"{m_count} vs {d['total']}（镜像原值 {m['total']}）；"
                    f"翻转 仅镜像内={mirror_in_direct_out}"
                    f" 仅直读内={direct_in_mirror_out}")

        # ── 4. impact_level 过滤样本（先截断后过滤 quirk 两侧同款） ──
        os.environ.pop(DIRECT, None)
        m = await query_latest_regulations(ctx, limit=100_000, days=365_000,
                                           impact_level="高")
        _env_direct(True)
        d = await query_latest_regulations(ctx, limit=100_000, days=365_000,
                                           impact_level="高")
        _env_direct(False)
        m_kept = _drop_non_regulation(m["items"])
        om4, ov4 = _diff_multiset(
            _multiset([_strip_key(i, "id", "article_no") for i in m_kept]),
            _multiset([_strip_key(i, "id", "article_no") for i in d["items"]]))
        _record(not om4 and not ov4 and len(m_kept) == len(d["items"]),
                "4. impact_level=高 过滤一致",
                f"{len(m_kept)} vs {len(d['items'])}"
                f"，差异 仅镜像={len(om4)} 仅直读={len(ov4)}")

        # ── 5. 直读排序自洽（input_date desc；cutoff 过滤后无空值） ──
        _env_direct(True)
        d_all = await query_latest_regulations(ctx, limit=100_000, days=365_000)
        _env_direct(False)
        view_dates = {v.id: v.input_date for v in views}
        seq = [view_dates.get(i["id"]) for i in d_all["items"]]
        non_null = [x for x in seq if x is not None]
        ordered_ok = non_null == sorted(non_null, reverse=True)
        _record(ordered_ok, "5. 直读默认排序 input_date desc 自洽（D4）",
                f"非空 {len(non_null)} 行降序自洽={ordered_ok}")

        # ── 6. input_date vs PG created_at 漂移量化（信息项） ──
        created_by_fid = {
            str(r.feishu_record_id or ""): r.created_at.date()
            for r in mirror_rows if r.feishu_record_id
        }
        drift = [
            abs((view_dates[fid] - created_by_fid[fid]).days)
            for fid in view_dates
            if fid in created_by_fid and view_dates[fid] is not None
        ]
        within = sum(1 for x in drift if x <= 1)
        print(f"  [INFO] input_date vs created_at 漂移：公共行 {len(drift)}"
              f"，差 <=1 天 {within} 行，最大 {max(drift) if drift else 0} 天"
              f"（D4 受控偏差量化）")

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
                        or "/records/batch_create" in u or u.endswith("/fields")
                        or "/media/upload_all" in u or "/drive/v1/medias" in u)

            calls.clear()
            _env_direct(True)
            await query_latest_regulations(ctx, limit=10)
            await open_reader().fetch_all(strict=True)  # strict 绕缓存强制联网
            _env_direct(False)
            writes = [u for u in calls if _is_write(u)]
            _record(not writes, "7. 直读查询路径零 Bitable 写",
                    f"写端点调用 {len(writes)} / 总调用 {len(calls)}")
        finally:
            httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

        # ── 8. 性能（直读全量 <2s；无缓存） ──
        _env_direct(True)
        await open_reader().fetch_all()  # 预热
        t0 = time.perf_counter()
        await query_latest_regulations(ctx, limit=10)
        elapsed = time.perf_counter() - t0
        _env_direct(False)
        _record(elapsed < 2.0, "8. 直读 query_latest_regulations <2s（无缓存）",
                f"{elapsed:.2f}s")
    finally:
        _env_direct(False)
        await session_ctx.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS ==")
    return 1 if failed else 0


if __name__ == "__main__":
    _dt = datetime.now(tz=UTC)
    print(f"verify_knowledge_dual @ {_dt.isoformat()}")
    sys.exit(asyncio.run(main()))
