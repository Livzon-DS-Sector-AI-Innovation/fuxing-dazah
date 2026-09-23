"""双路径比对 + 零回写探针（msds-direct Ticket 04，照 verify_knowledge_dual 方法学）。

本地开关保持全关（脚本内部按比对项临时拨开关，结束恢复）；推送开关显式关闭
（安全速递误发教训）。本脚本只调用查询路径——不触碰事件 handler、采集→收录
写面管线、msds_indexer→chunk 链路、推送面。

已知口径（spec §0 探针实证 + §4.7 归因落档）：
  - dev 镜像断流：msds_documents 非删除仅 3 行 vs Bitable 台账表 71 行，
    direct-only = 断流缺口（方向=直读更正确），不判 FAIL；
  - 公共行 source_date 允许分歧（2 行写回时序+人工补录历史，直读=当前值）；
  - 其余工具体输出数据字段（name/cas_no/molecular_formula/un_no/hazard_statement/
    appearance/flash_point/relative_density/pc_twa/health_hazard/first_aid）
    公共行须严格一致；
  - review_status/archive_status 双路径恒 pending（审核流未上线）。

比对项：
  1. 全量记录集比对（工具体 limit=100000）：mirror-only / direct-only 按
     断流口径归因打印；
  2. 公共 fid 逐字段比对（严格字段零差异 + source_date 分歧归因）；
  3. name 过滤样本：镜像命中集 ⊆ 直读命中集（直读超集=断流行，逐条打印）；
  4. cas_no 过滤样本（同上）；
  5. 直读排序自洽：source_date desc NULLS LAST；
  6. 零回写探针：直读查询路径 Bitable 写端点调用数 = 0；
  7. 性能：直读查询 <2s（超限触发 spec D4 预授权条款加 TTL）。

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

DIRECT = "SAFETY_MSDS_DIRECT_ENABLED"
_PUSH_KEYS = (
    "SAFETY_DAILY_DIGEST_ENABLED",
    "SAFETY_REGULATION_CRAWLER_ENABLED",
)
# 工具体输出中「须严格一致」的数据字段（source_date 为分歧归因面，单独比对）
STRICT_FIELDS = (
    "name", "cas_no", "molecular_formula", "un_no", "hazard_statement",
    "appearance", "flash_point", "relative_density", "pc_twa",
    "health_hazard", "first_aid",
)

results: list[tuple[bool, str, str]] = []


def _record(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"：{detail}" if detail else ""))


def _env_direct(on: bool) -> None:
    if on:
        os.environ[DIRECT] = "true"
    else:
        os.environ.pop(DIRECT, None)


def _strip_key(item: dict[str, Any], *drop: str) -> str:
    keep = {k: v for k, v in item.items() if k not in drop}
    return json.dumps(keep, ensure_ascii=False, sort_keys=True, default=str)


async def main() -> int:
    from sqlalchemy import select

    from app.core.database import async_session_factory
    from app.modules.safety.business_agent.tools.read_tools import (
        query_msds_documents,
    )
    from app.modules.safety.models import MsdsDocument
    from app.modules.safety.service.msds_direct.reader import open_reader

    for key in _PUSH_KEYS:
        os.environ.pop(key, None)  # 推送/爬虫面显式关闭（本脚本只读查询）

    session_ctx = async_session_factory()
    db = await session_ctx.__aenter__()
    try:
        mirror_rows = list((await db.scalars(
            select(MsdsDocument).where(
                MsdsDocument.is_deleted == False,  # noqa: E712
            )
        )).all())

        ctx = SimpleNamespace(deps=SimpleNamespace(db=db))

        # ── 1. 全量记录集比对（断流归因面） ──
        t0 = time.perf_counter()
        views = await open_reader().fetch_all(strict=True)
        elapsed_all = time.perf_counter() - t0
        view_by_fid = {v.id: v for v in views}
        mirror_by_fid = {
            str(r.feishu_record_id): r for r in mirror_rows if r.feishu_record_id
        }
        mirror_only = sorted(set(mirror_by_fid) - set(view_by_fid))
        direct_only = sorted(set(view_by_fid) - set(mirror_by_fid))
        common = sorted(set(mirror_by_fid) & set(view_by_fid))
        print(f"镜像行={len(mirror_rows)} 直读视图={len(views)}"
              f" 公共={len(common)} 全量拉取 {elapsed_all:.2f}s")
        # 断流缺口（direct-only）方向=直读更正确：mirror-only 才判 FAIL（幽灵行）
        _record(not mirror_only,
                "1. 全量记录集（mirror-only=0；direct-only=断流缺口归因）",
                f"mirror-only={len(mirror_only)}{mirror_only[:3]}"
                f" direct-only={len(direct_only)}（dev 镜像断流，spec §0 口径）")

        # ── 2. 公共 fid 逐字段比对（gotchas#10：差异按字段归因打印） ──
        field_diffs: dict[str, list[str]] = {}
        for fid in common:
            m, v = mirror_by_fid[fid], view_by_fid[fid]
            pairs = [(f, getattr(m, f), getattr(v, f)) for f in STRICT_FIELDS]
            pairs.append((
                "source_date",
                m.source_date.isoformat() if m.source_date else "",
                v.source_date.isoformat() if v.source_date else "",
            ))
            for name, mv, dv in pairs:
                mv_s = "" if mv is None else str(mv)
                dv_s = "" if dv is None else str(dv)
                if mv_s != dv_s:
                    field_diffs.setdefault(name, []).append(fid)
        source_date_diffs = field_diffs.pop("source_date", [])
        strict_bad = {f: ids for f, ids in field_diffs.items() if ids}
        _record(not strict_bad,
                "2. 公共 fid 严格字段一致（工具体输出 11 数据字段）",
                f"公共 fid={len(common)}；"
                + "；".join(f"{f} 差 {len(ids)}" for f, ids in strict_bad.items())
                if strict_bad else f"公共 fid={len(common)} 零差异")
        for f, ids in strict_bad.items():
            fid0 = ids[0]
            m0, v0 = mirror_by_fid[fid0], view_by_fid[fid0]
            print(f"      [归因] {f} fid={fid0}"
                  f" mirror={repr(getattr(m0, f))[:60]}"
                  f" bitable={repr(getattr(v0, f))[:60]}")
        print(f"      [归因] source_date 分歧行={len(source_date_diffs)}"
              f"{source_date_diffs[:3]}（写回时序+人工补录历史，直读=当前值，"
              f"spec §4.7 受控偏差）")

        # ── 3/4. 过滤样本：镜像命中 ⊆ 直读命中（超集=断流行） ──
        for label, kwargs in (
            ("3. name=醇 过滤", {"name": "醇"}),
            ("4. cas_no=67 过滤", {"cas_no": "67"}),
        ):
            os.environ.pop(DIRECT, None)
            m = await query_msds_documents(ctx, limit=100_000, **kwargs)
            _env_direct(True)
            d = await query_msds_documents(ctx, limit=100_000, **kwargs)
            _env_direct(False)
            uuid_to_fid = {
                str(r.id): str(r.feishu_record_id or "") for r in mirror_rows
            }
            m_fids = {uuid_to_fid.get(i["id"], i["id"]) for i in m["items"]}
            d_fids = {i["id"] for i in d["items"]}
            subset_ok = m_fids <= d_fids
            # 镜像命中的行在直读中逐字段相同（id 剥离后 JSON 比较）
            d_by_fid = {i["id"]: i for i in d["items"]}
            content_ok = all(
                _strip_key(i, "id") == _strip_key(d_by_fid[uuid_to_fid[i["id"]]], "id")
                for i in m["items"] if uuid_to_fid.get(i["id"], "") in d_by_fid
            )
            _record(subset_ok and content_ok,
                    f"{label}（镜像命中⊆直读命中且逐字段一致）",
                    f"镜像 {m['total']} 直读 {d['total']}"
                    f" 直读超集={len(d_fids - m_fids)} 行（断流归因）")

        # ── 5. 直读排序自洽（source_date desc；NULLS LAST） ──
        _env_direct(True)
        d_all = await query_msds_documents(ctx, limit=100_000)
        _env_direct(False)
        seq = [view_by_fid[i["id"]].source_date for i in d_all["items"]]
        non_null = [x for x in seq if x is not None]
        ordered_ok = non_null == sorted(non_null, reverse=True)
        nulls_last_ok = non_null + [None] * (len(seq) - len(non_null)) == seq
        _record(ordered_ok and nulls_last_ok,
                "5. 直读默认排序 source_date desc NULLS LAST 自洽（D3）",
                f"非空 {len(non_null)} / 全部 {len(seq)} 降序自洽={ordered_ok}"
                f" 空值殿后={nulls_last_ok}")

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
            await query_msds_documents(ctx, limit=10)
            await open_reader().fetch_all(strict=True)
            _env_direct(False)
            writes = [u for u in calls if _is_write(u)]
            _record(not writes, "6. 直读查询路径零 Bitable 写",
                    f"写端点调用 {len(writes)} / 总调用 {len(calls)}")
        finally:
            httpx.AsyncClient.post = real_post  # type: ignore[method-assign]

        # ── 7. 性能（直读全量 <2s；D4 条款已触发——TTL 缓存窗口内计时，
        #      冷拉耗见第 1 项 strict 强制联网全量拉取） ──
        _env_direct(True)
        await open_reader().fetch_all()  # 预热（回填 TTL 缓存）
        t0 = time.perf_counter()
        await query_msds_documents(ctx, limit=10)
        elapsed = time.perf_counter() - t0
        _env_direct(False)
        _record(elapsed < 2.0, "7. 直读 query_msds_documents <2s（TTL 窗口内）",
                f"{elapsed:.2f}s（缓存命中；D4 条款触发落地 cache.py）")
    finally:
        _env_direct(False)
        await session_ctx.__aexit__(None, None, None)

    failed = [r for r in results if not r[0]]
    print(f"\n== 汇总：{len(results) - len(failed)}/{len(results)} PASS ==")
    return 1 if failed else 0


if __name__ == "__main__":
    _dt = datetime.now(tz=UTC)
    print(f"verify_msds_dual @ {_dt.isoformat()}")
    sys.exit(asyncio.run(main()))
