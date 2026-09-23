"""双路径比对 + 零回写探针（oh-direct Ticket 04，照 verify_msds_dual 方法学）。

本地开关保持全关（脚本内部按比对项临时拨开关，结束恢复）；推送开关显式关闭
（安全速递误发教训）。本脚本只调用查询路径——不触碰事件 handler、AI 工作流
钩子、回写面、推送面。**运行前置：先跑 backfill_oh_mirror.py 回填本地镜像。**

两级口径（spec §0.1 终版切面）：
  - **验收级（hazard_factors，本域实际切换工具）**：硬 PASS/FAIL——记录集
    （source=bitable 镜像面）、公共 fid 逐字段、过滤/quirk/排序语义、零回写、性能；
  - **盘点级（positions，维持镜像工具）**：报告不判 FAIL——镜像表双源
    （440 bitable + 470 manual 历史迁移行）+ 唯一索引卡更新病灶归因。

已知口径（spec §0.4 预归因）：
  - (dept,pos)/factor_name 部分唯一索引收敛：直读重复行 direct-only 归因通过；
  - positions bitable 面存在事件更新被手动行卡键的历史分歧（≈96 行，更新失败
    保留旧值，方向=直读更正确）——盘点级打印，不判 FAIL；
  - job_title 死列：两侧恒空（归一后相等）；
  - 排序：直读自洽性校验（PG collation 与 Python 码点序差异属 spec D3 受控
    偏差，不做跨路径排序相等断言）。

比对项：
  1a.[验收] factors 记录集（mirror(source=bitable)-only=0；direct-only ∈ 重复名组）
  1b.[盘点] positions 记录集（mirror(source=bitable)-only=0；direct-only ∈
     重复组；手动行数打印）
  2a.[验收] factors 公共 fid 严格字段（factor_name 差异 ≤ 重复名组行数且 fid 命中）
  2b.[盘点] positions 公共 fid 严格字段差异打印归因
  3.[验收] keyword 过滤样本（factors，quirk 语义）：镜像命中 ⊆ 直读命中且逐字段一致
  4.[验收] 直读排序自洽（factors name asc）
  5.[验收] 零回写探针：直读查询路径 Bitable 写端点调用数 = 0
  6.[验收] 性能：factors 直读查询 <2s（TTL 窗口内；D4 预授权条款已落地 cache.py）

退出码：0 验收级全 PASS；1 有验收级 FAIL（盘点级不计）。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, ".")

DIRECT = "SAFETY_OH_DIRECT_ENABLED"
_PUSH_KEYS = (
    "SAFETY_DAILY_DIGEST_ENABLED",
    "SAFETY_REGULATION_CRAWLER_ENABLED",
)
STRICT_POSITION_FIELDS = (
    "department", "position", "job_title",
    "hazard_factors", "hazard_factors_status",
)
STRICT_FACTOR_FIELDS = ("factor_name", "ppe_respiratory")

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
    """NULL/空归一 + 列表稳定序列化（gotchas#10 比对前归一口径）。"""
    if v is None:
        return ""
    if isinstance(v, list):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
    return str(v)


def _strip_key(item: dict[str, Any], *drop: str) -> str:
    keep = {k: v for k, v in item.items() if k not in drop}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True, default=str)


async def _fetch_tool_factors(ctx: Any, **kw: Any) -> dict[str, Any]:
    from app.modules.safety.business_agent.tools.read_tools import (
        query_oh_hazard_factors,
    )
    return await query_oh_hazard_factors(ctx, **kw)  # type: ignore[arg-type]


async def _fetch_tool_positions(ctx: Any, **kw: Any) -> dict[str, Any]:
    from app.modules.safety.business_agent.tools.read_tools import (
        query_oh_positions,
    )
    return await query_oh_positions(ctx, **kw)  # type: ignore[arg-type]


def _dup_fids_by_name(views: list[Any], attr: str) -> set[str]:
    counter = Counter(getattr(v, attr) for v in views)
    return {v.id for v in views if counter[getattr(v, attr)] > 1}


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.models import OhHazardFactor, OhPosition
    from app.modules.safety.service.oh_direct.reader import open_reader

    for key in _PUSH_KEYS:
        os.environ.pop(key, None)  # 推送/爬虫面显式关闭（本脚本只读查询）

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        ctx = SimpleNamespace(deps=SimpleNamespace(db=db))

        # 镜像面只取 source=bitable 行（manual 行是 PG 独有人群，spec §0.1）
        mirror_fac = list((await db.scalars(
            select(OhHazardFactor).where(
                OhHazardFactor.is_deleted == False,  # noqa: E712
                OhHazardFactor.source == "bitable",
            )
        )).all())
        mirror_pos_all = list((await db.scalars(
            select(OhPosition).where(OhPosition.is_deleted == False),  # noqa: E712
        )).all())
        mirror_pos = [r for r in mirror_pos_all if r.source == "bitable"]
        manual_pos = [r for r in mirror_pos_all if r.source != "bitable"]

        t0 = time.perf_counter()
        pos_views = await open_reader().fetch_positions(strict=True)
        fac_views = await open_reader().fetch_factors(strict=True)
        elapsed_all = time.perf_counter() - t0
        print(f"直读两表全量拉取 {elapsed_all:.2f}s；"
              f"positions 镜像手动行={len(manual_pos)}"
              f"（PG 独有，直读不含——维持镜像的承重证据）")

        # ── 1a.[验收] factors 记录集 ──
        fac_by_fid = {v.id: v for v in fac_views}
        mfac_by_fid = {
            str(r.feishu_record_id): r for r in mirror_fac if r.feishu_record_id
        }
        fac_mirror_only = sorted(set(mfac_by_fid) - set(fac_by_fid))
        fac_direct_only = sorted(set(fac_by_fid) - set(mfac_by_fid))
        fac_dup = _dup_fids_by_name(fac_views, "factor_name")
        fac_unexplained = [f for f in fac_direct_only if f not in fac_dup]
        _record(not fac_mirror_only and not fac_unexplained,
                "1a.[验收] hazard_factors 记录集（mirror-only=0；direct-only "
                "∈ factor_name 重复组）",
                f"镜像 {len(mfac_by_fid)} 直读 {len(fac_by_fid)}"
                f" mirror-only={fac_mirror_only[:3]}"
                f" direct-only={fac_direct_only}"
                f" 未归因={fac_unexplained[:3]}")

        # ── 1b.[盘点] positions 记录集 ──
        pos_by_fid = {v.id: v for v in pos_views}
        mpos_by_fid = {
            str(r.feishu_record_id): r for r in mirror_pos if r.feishu_record_id
        }
        pos_mirror_only = sorted(set(mpos_by_fid) - set(pos_by_fid))
        pos_direct_only = sorted(set(pos_by_fid) - set(mpos_by_fid))
        pair_counter = Counter((v.department, v.position) for v in pos_views)
        pos_dup = {
            v.id for v in pos_views if pair_counter[(v.department, v.position)] > 1
        }
        pos_unexplained = [f for f in pos_direct_only if f not in pos_dup]
        _report(
            "1b.[盘点] positions 记录集（bitable 面）",
            f"镜像 {len(mpos_by_fid)} 直读 {len(pos_by_fid)}"
            f" mirror-only={len(pos_mirror_only)}{pos_mirror_only[:3]}"
            f" direct-only={len(pos_direct_only)}（重复组归因 {len(pos_direct_only) - len(pos_unexplained)}"
            f" 未归因 {len(pos_unexplained)}{pos_unexplained[:3]}）"
            f" 手动行={len(manual_pos)}")

        # ── 2a.[验收] factors 公共 fid 严格字段 ──
        fac_common = sorted(set(mfac_by_fid) & set(fac_by_fid))
        fac_field_diffs: dict[str, list[str]] = {}
        for fid in fac_common:
            m, v = mfac_by_fid[fid], fac_by_fid[fid]
            for f in STRICT_FACTOR_FIELDS:
                if _norm(getattr(m, f)) != _norm(getattr(v, f)):
                    fac_field_diffs.setdefault(f, []).append(fid)
        # factor_name 差异容差=重复名组行数（唯一索引卡更新历史，spec §0.4）
        name_diffs = fac_field_diffs.get("factor_name", [])
        name_diff_ok = all(fid in fac_dup for fid in name_diffs)
        other_diffs = {f: ids for f, ids in fac_field_diffs.items()
                       if f != "factor_name" and ids}
        _record(not other_diffs and (not name_diffs or name_diff_ok),
                "2a.[验收] hazard_factors 公共 fid 严格字段一致"
                "（factor_name 差异全部 ∈ 重复名组）",
                f"公共 fid={len(fac_common)}"
                + (f"；factor_name 差 {len(name_diffs)}{name_diffs[:3]}"
                   if name_diffs else "；零差异")
                + "；".join(f"；{f} 差 {len(ids)}" for f, ids in other_diffs.items()))
        for f, ids in fac_field_diffs.items():
            fid0 = ids[0]
            m0, v0 = mfac_by_fid[fid0], fac_by_fid[fid0]
            print(f"      [归因] {f} fid={fid0}"
                  f" mirror={repr(getattr(m0, f))[:60]}"
                  f" bitable={repr(getattr(v0, f))[:60]}")

        # ── 2b.[盘点] positions 公共 fid 严格字段差异打印 ──
        pos_common = sorted(set(mpos_by_fid) & set(pos_by_fid))
        pos_field_diffs: dict[str, list[str]] = {}
        for fid in pos_common:
            m, v = mpos_by_fid[fid], pos_by_fid[fid]
            for f in STRICT_POSITION_FIELDS:
                if _norm(getattr(m, f)) != _norm(getattr(v, f)):
                    pos_field_diffs.setdefault(f, []).append(fid)
        diff_total = sum(len(ids) for ids in pos_field_diffs.values())
        _report(
            "2b.[盘点] positions 公共 fid 严格字段差异"
            "（事件更新被手动行卡键历史，方向=直读更正确）",
            f"公共 fid={len(pos_common)} 差异行次={diff_total}"
            + "；".join(f" {f}={len(ids)}" for f, ids in pos_field_diffs.items()))
        for f, ids in list(pos_field_diffs.items())[:3]:
            fid0 = ids[0]
            m0, v0 = mpos_by_fid[fid0], pos_by_fid[fid0]
            print(f"      [归因] {f} fid={fid0}"
                  f" mirror={repr(getattr(m0, f))[:60]}"
                  f" bitable={repr(getattr(v0, f))[:60]}")

        # ── 3.[验收] keyword 过滤样本（factors，quirk 语义） ──
        os.environ.pop(DIRECT, None)
        m3 = await _fetch_tool_factors(ctx, keyword="甲", limit=1000)
        _env_direct(True)
        d3 = await _fetch_tool_factors(ctx, keyword="甲", limit=1000)
        _env_direct(False)
        uuid_to_fid_f = {
            str(r.id): str(r.feishu_record_id or "") for r in mirror_fac
        }
        m3_fids = {uuid_to_fid_f.get(i["id"], i["id"]) for i in m3["items"]}
        d3_fids = {i["id"] for i in d3["items"]}
        d3_by_fid = {i["id"]: i for i in d3["items"]}
        # 内容一致性按 2a 归因豁免（唯一索引卡更新行的 name 新旧值差异同源）
        attribution_fids = {fid for ids in fac_field_diffs.values() for fid in ids}
        content_bad: list[str] = []
        for i in m3["items"]:
            fid = uuid_to_fid_f.get(i["id"], "")
            if fid in d3_by_fid and fid not in attribution_fids:
                if _strip_key(i, "id") != _strip_key(d3_by_fid[fid], "id"):
                    content_bad.append(fid)
        _record(m3_fids <= d3_fids and not content_bad,
                "3.[验收] keyword=甲 过滤（镜像命中⊆直读命中；逐字段一致，"
                "2a 归因行豁免）",
                f"镜像 {m3['total']} 直读 {d3['total']}"
                f" 直读超集={sorted(d3_fids - m3_fids)}（重复名组归因）"
                f" 未归因内容差={content_bad[:3]}")

        # ── 4.[验收] 直读排序自洽 ──
        _env_direct(True)
        d_fall = await _fetch_tool_factors(ctx, limit=1000)
        _env_direct(False)
        fseq = [i["factor_name"] or "" for i in d_fall["items"]]
        _record(fseq == sorted(fseq),
                "4.[验收] hazard_factors 直读排序 factor_name asc 自洽",
                f"{len(fseq)} 行升序自洽={fseq == sorted(fseq)}")

        # ── 5.[验收] 零回写探针 ──
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
            await _fetch_tool_factors(ctx, keyword="噪")
            await _fetch_tool_positions(ctx, limit=10)  # legacy 路径也不得有写
            await open_reader().fetch_factors(strict=True)
            await open_reader().fetch_positions(strict=True)
            _env_direct(False)
            writes = [u for u in calls if _is_write(u)]
            _record(not writes, "5.[验收] 直读查询路径零 Bitable 写",
                    f"写端点调用 {len(writes)} / 总调用 {len(calls)}")
        finally:
            httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

        # ── 6.[验收] 性能（TTL 窗口内 <2s；冷拉耗见直读全量拉取计时） ──
        _env_direct(True)
        await open_reader().fetch_factors()  # 预热
        t1 = time.perf_counter()
        await _fetch_tool_factors(ctx, keyword="甲")
        elapsed_f = time.perf_counter() - t1
        t2 = time.perf_counter()
        await _fetch_tool_factors(ctx)
        elapsed_all_tool = time.perf_counter() - t2
        _env_direct(False)
        _record(elapsed_f < 2.0 and elapsed_all_tool < 2.0,
                "6.[验收] query_oh_hazard_factors 直读 <2s（TTL 窗口内）",
                f"keyword {elapsed_f:.2f}s / 全量 {elapsed_all_tool:.2f}s"
                f"（D4 条款落地 cache.py TTL 60s）")
    finally:
        _env_direct(False)
        await session_ctx.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS"
          f"（盘点级项不计入）==")
    return 1 if failed else 0


if __name__ == "__main__":
    _dt = datetime.now(tz=UTC)
    print(f"verify_oh_dual @ {_dt.isoformat()}")
    sys.exit(asyncio.run(main()))
