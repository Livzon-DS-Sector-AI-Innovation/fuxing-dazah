"""ragplus-x 存量全量入库（法规两表 + MSDS）— 一期壳换芯 Ticket 04。

流程（--apply 才真正执行，默认 dry-run 只盘点）：
  1. bootstrap：应急 admin 登录（RAGPLUS_ADMIN_USER/PASSWORD 可覆盖）→
     幂等建三库（安全法规标准/MSDS/已废止）→ 按名去重创建 retrieval
     服务 token（dazah-safety-service）→ 全文写入 app_config
     SAFETY_RAGPLUS_API_TOKEN（不落代码/git）。
  2. 法规：Bitable 两表（collection 安全 + collection_env 环保，并入同一
     「安全法规标准」库）全量直读 → 有「法规原件」附件的行下载 PDF →
     上传 → 批量解析 → 4s 轮询至 DONE/FAIL → ragplus_doc_map 登记
     （biz_key=feishu_record_id；已有 active 映射跳过 = 幂等）。
  3. MSDS：PG msds_collection_records 存量（附件物化自 MinIO/本地）→
     唯一 PDF 入 MSDS 库（biz_key=collection_record_id）。
  4. 失败清单 + 对账表落档仓库 .scratch/ragplus-switch-p1/。

用法（backend 目录下）：

    PYTHONPATH=. uv run python scripts/tmp/ragplus_bulk_ingest.py            # dry-run
    PYTHONPATH=. uv run python scripts/tmp/ragplus_bulk_ingest.py --apply    # 真跑
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, ".")

from sqlalchemy import select  # noqa: E402

from app.modules.safety.knowledge.ragplus_client import (  # noqa: E402
    RagplusAdminClient,
)
from app.modules.safety.knowledge.ragplus_sync import (  # noqa: E402
    KB_ARCHIVE,
    KB_MSDS,
    KB_REGULATION,
    TOKEN_NAME,
    build_admin_client,
    upsert_ragplus_map,
)

_KIND_LABELS = {"collection": "安全法规标准表", "collection_env": "环保法规标准表"}
# repo 根的落档目录（脚本从 backend/ 运行）
# backend/scripts/tmp/x.py → parents[3] = 仓库根
SCRATCH_DIR = Path(__file__).resolve().parents[3] / ".scratch" / "ragplus-switch-p1"


class Report:
    """对账计数 + 失败清单（dry-run/apply 共用）。"""

    def __init__(self) -> None:
        self.counts: dict[str, dict[str, int]] = {
            "regulation": self._zero(),
            "msds": self._zero(),
        }
        self.failures: list[dict[str, Any]] = []

    @staticmethod
    def _zero() -> dict[str, int]:
        return {
            "total": 0,
            "with_attachment": 0,
            "skipped_active": 0,
            "skipped_no_attachment": 0,
            "uploaded": 0,
            "parsed_ok": 0,
            "parse_failed": 0,
            "upload_failed": 0,
            "download_failed": 0,
        }

    def fail(
        self, domain: str, biz_key: str, title: str, stage: str, error: str
    ) -> None:
        self.failures.append(
            {
                "domain": domain,
                "biz_key": biz_key,
                "title": title,
                "stage": stage,
                "error": str(error)[:500],
            }
        )

    def dump(self) -> None:
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        lines = [
            "# ragplus 存量入库对账表",
            "",
            f"- 时间：{datetime.now(UTC).isoformat(timespec='seconds')}",
            f"- ragplus 库：{KB_REGULATION} / {KB_MSDS} / {KB_ARCHIVE}",
            "",
            "| 域 | 总行 | 有附件 | 跳过(已active) | 无附件跳过 | 上传成功 | 解析成功 | 解析失败 | 上传失败 | 下载失败 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for domain, c in self.counts.items():
            lines.append(
                f"| {domain} | {c['total']} | {c['with_attachment']} | {c['skipped_active']} "
                f"| {c['skipped_no_attachment']} | {c['uploaded']} | {c['parsed_ok']} "
                f"| {c['parse_failed']} | {c['upload_failed']} | {c['download_failed']} |"
            )
        lines += [
            "",
            f"- 失败明细：{len(self.failures)} 条（ingest_failures_{stamp}.json）",
        ]
        (SCRATCH_DIR / "ingest_对账表.md").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        (SCRATCH_DIR / f"ingest_failures_{stamp}.json").write_text(
            json.dumps(self.failures, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"对账表已落档：{SCRATCH_DIR}/ingest_对账表.md")


# ═══════════════════════════════════════════════════════════════
# Bootstrap
# ═══════════════════════════════════════════════════════════════


def _admin_from_config() -> RagplusAdminClient:
    return build_admin_client()


async def bootstrap(
    admin: RagplusAdminClient, apply: bool
) -> dict[str, dict[str, Any]]:
    """登录 + 幂等建三库 + 确保 retrieval token 写入 app_config。"""
    print(f"== bootstrap（{'APPLY' if apply else 'DRY-RUN'}）==")
    await admin.login()
    print("  应急 admin 登录 ✓")

    kb_specs = (
        (KB_REGULATION, "dazah 安全模块：法规标准与规程（安全+环保）"),
        (KB_MSDS, "dazah 安全模块：MSDS 供应商资料"),
        (KB_ARCHIVE, "dazah 安全模块：已废止/被替代法规归档（检索名单外）"),
    )

    if not apply:
        existing = {kb.get("name"): kb for kb in await admin.list_kbs()}
        kbs: dict[str, dict[str, Any]] = {}
        for name, desc in kb_specs:
            kb = existing.get(name)
            print(f"  库「{name}」：{'已存在 ✓' if kb else '待创建'}")
            kbs[name] = kb or {"name": name, "description": desc}
        return kbs

    kbs = {}
    for name, desc in kb_specs:
        kbs[name] = await admin.ensure_kb(name, desc)
        print(f"  库「{name}」就绪（kb_id={kbs[name].get('id')}）")

    token = await _ensure_service_token(admin)
    if token is None:
        print("  服务 token：已就绪（app_config 已配置）✓")
    else:
        print(f"  服务 token：已创建并写入 app_config（前缀 {token[:14]}…）")
    return kbs


async def _ensure_service_token(admin: RagplusAdminClient) -> str | None:
    """确保 retrieval token 存在且已写入 app_config。

    返回新创建的 token 全文；已就绪返回 None。同名 token 存在但
    app_config 未配置（全文不可恢复）时自动轮转：吊销旧 + 建新。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.app_config.store import store

    current = store.get_str("SAFETY_RAGPLUS_API_TOKEN")
    token = await admin.ensure_token(TOKEN_NAME)
    if token is None and not current:
        for row in await admin.list_tokens():
            if row.get("name") == TOKEN_NAME and row.get("id"):
                await admin.revoke_token(int(row["id"]))
                print(
                    f"  轮转：吊销旧 token #{row['id']}（app_config 未配置，全文不可恢复）"
                )
        token = await admin.create_token(TOKEN_NAME)
    if token is None:
        return None

    async with async_session_factory() as session:
        await store.set_value(
            session,
            "SAFETY_RAGPLUS_API_TOKEN",
            token,
            note="ragplus_bulk_ingest bootstrap 自动写入",
        )
        await session.commit()
    store.invalidate()
    return token


# ═══════════════════════════════════════════════════════════════
# 映射表
# ═══════════════════════════════════════════════════════════════


async def _load_existing_maps(domain: str) -> dict[str, Any]:
    """预载域内全部映射行（biz_key → row），避免逐条开 session。"""
    from app.core.database import async_session_factory
    from app.modules.safety.models import RagplusDocMap

    async with async_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(RagplusDocMap).where(
                        RagplusDocMap.domain == domain,
                        RagplusDocMap.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {str(r.biz_key): r for r in rows}


async def _upsert_maps(entries: list[dict[str, Any]]) -> None:
    """批量登记映射（复用 ragplus_sync.upsert_ragplus_map，单事务提交）。"""
    from app.core.database import async_session_factory

    async with async_session_factory() as session:
        for e in entries:
            await upsert_ragplus_map(session, **e)
        await session.commit()


# ═══════════════════════════════════════════════════════════════
# 上传-解析-登记（法规/MSDS 共用编排）
# ═══════════════════════════════════════════════════════════════

# 单次解析调用的批量上限：811 个一次性 parallel 曾触发引擎 code=100
# IndexError（RAGFlow 大列表批量解析缺陷），25/批稳定
_PARSE_BATCH = 25


async def _upload_parse_and_register(
    admin: RagplusAdminClient,
    *,
    domain: str,
    dataset_name: str,
    kb: dict[str, Any],
    pending: list[dict[str, Any]],
    report: Report,
) -> None:
    """上传（或复用已传文档）→ 分批解析 → 轮询 → 映射登记。

    pending 项两种形态：
    - 含 blob：全新上传（下载→上传→解析→登记）
    - 含 kb_doc_id 无 blob：解析重试（上次上传成功但解析失败/超时的映射行，
      不重复下载上传，只补解析——幂等重跑不产生重复文档）
    """
    counts = report.counts[domain]
    kb_id = kb.get("id")
    dataset_id = kb.get("dataset_id") or ""

    # ── 解析重试项：按 ragplus 当前状态分诊（DONE 直接登记，RUNNING 只等）──
    retry = [p for p in pending if not p.get("blob") and p.get("kb_doc_id")]
    if retry:
        statuses: dict[int, dict[str, Any]] = {}
        try:
            for d in await admin.list_documents(kb_id):
                if d.get("id") is not None:
                    statuses[int(d["id"])] = d
        except Exception:
            statuses = {}
        for p in retry:
            d = statuses.get(int(p["kb_doc_id"]))
            current = str((d or {}).get("status") or "UNKNOWN")
            p["_engine_doc_id"] = (d or {}).get("engine_doc_id")
            if current == "DONE":
                p["_already_done"] = True
            elif current in ("RUNNING", "PARSING"):
                p["_already_running"] = True
            # UNSTART/FAIL/CANCEL/UNKNOWN → 重新分批解析

    # ── 全新上传 ──
    items: list[dict[str, Any]] = []
    fresh = [p for p in pending if p.get("blob")]
    for i, item in enumerate(fresh, 1):
        try:
            doc = await admin.upload_document(
                kb_id,
                item["file_name"],
                item["blob"],
                item.get("content_type") or "application/octet-stream",
            )
        except Exception as exc:
            counts["upload_failed"] += 1
            report.fail(domain, item["biz_key"], item["title"], "upload", exc)
            continue
        items.append({**item, "kb_doc_id": doc["id"]})
        if i % 20 == 0 or i == len(fresh):
            print(f"  [{domain}] 上传进度 {i}/{len(fresh)}")
    if items:
        counts["uploaded"] += len(items)

    # 已是 DONE 的重试项直接登记；其余（新传 + 待重析 + RUNNING）统一编排
    done_retry = [p for p in retry if p.get("_already_done")]
    to_parse: list[dict[str, Any]] = items + [
        p for p in retry if not p.get("_already_done")
    ]

    # ── 分批解析（每批独立容错）──
    parse_ids = [p["kb_doc_id"] for p in to_parse if not p.get("_already_running")]
    parse_errors: dict[int, str] = {}
    for start in range(0, len(parse_ids), _PARSE_BATCH):
        batch = parse_ids[start : start + _PARSE_BATCH]
        try:
            await admin.parse_documents(kb_id, batch, mode="parallel")
        except Exception as exc:
            for doc_id in batch:
                parse_errors[doc_id] = f"启动解析失败：{str(exc)[:200]}"
            print(f"  [{domain}] 解析批次失败（{len(batch)} 个）：{str(exc)[:120]}")
    if parse_ids:
        print(
            f"  [{domain}] 分批解析已启动：{len(parse_ids)} 个文档（{_PARSE_BATCH}/批）"
        )

    # ── 统一轮询（新传 + 重析 + 引擎侧仍在 RUNNING 的）──
    wait_ids = [p["kb_doc_id"] for p in to_parse]
    results: dict[int, dict[str, Any]] = {}
    if wait_ids:
        try:
            results = await admin.wait_documents_ready(
                kb_id, wait_ids, poll=4, deadline=1800
            )
        except Exception as exc:
            results = {
                doc_id: {"status": "POLL_ERROR", "fail_reason": str(exc)}
                for doc_id in wait_ids
            }
    for doc_id, reason in parse_errors.items():
        results.setdefault(doc_id, {"status": "PARSE_ERROR", "fail_reason": reason})

    # engine_doc_id 回填（list_documents 携带，映射表检索/对账用）
    engine_ids: dict[int, str] = {}
    try:
        for doc in await admin.list_documents(kb_id):
            if doc.get("id") and doc.get("engine_doc_id"):
                engine_ids[int(doc["id"])] = str(doc["engine_doc_id"])
    except Exception:
        pass

    # ── 映射登记 ──
    entries: list[dict[str, Any]] = []
    for u in to_parse + done_retry:
        doc_id = u["kb_doc_id"]
        r = (
            {"status": "DONE"}
            if u.get("_already_done")
            else results.get(doc_id)
            or {"status": "UNKNOWN", "fail_reason": "无解析结果"}
        )
        ok = r["status"] == "DONE"
        if ok:
            counts["parsed_ok"] += 1
        else:
            counts["parse_failed"] += 1
            report.fail(
                domain,
                u["biz_key"],
                u["title"],
                f"parse:{r['status']}",
                r.get("fail_reason") or "",
            )
        entries.append(
            {
                "domain": domain,
                "biz_key": u["biz_key"],
                "dataset_name": dataset_name,
                "kb_doc_id": doc_id,
                "engine_doc_id": u.get("_engine_doc_id") or engine_ids.get(doc_id),
                "dataset_id": dataset_id,
                "title": u["title"],
                "file_name": u["file_name"],
                "status": "active" if ok else "failed",
                "last_error": None
                if ok
                else str(r.get("fail_reason") or r["status"])[:500],
            }
        )
    await _upsert_maps(entries)
    print(
        f"  [{domain}] 解析完成：成功 {counts['parsed_ok']} / 失败 {counts['parse_failed']}"
    )


# ═══════════════════════════════════════════════════════════════
# 法规两表
# ═══════════════════════════════════════════════════════════════


async def ingest_regulations(
    admin: RagplusAdminClient,
    kbs: dict[str, dict[str, Any]],
    apply: bool,
    report: Report,
) -> None:
    from app.modules.safety.feishu.knowledge_bitable_handler import (
        _extract_attachment_list,
        _extract_rich_text,
    )
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    kb = kbs[KB_REGULATION]
    print(f"== 法规两表 → 「{KB_REGULATION}」（kb_id={kb.get('id')}）==")

    existing_maps = await _load_existing_maps("regulation") if apply else {}
    pending: list[dict[str, Any]] = []
    counts = report.counts["regulation"]

    for kind in ("collection", "collection_env"):
        label = _KIND_LABELS[kind]
        try:
            client = bd_reader.resolve_client("knowledge", kind)
            records = await bd_reader.fetch_all_records(client)
        except Exception as exc:
            print(f"  [{label}] 直读失败（跳过该表）：{exc}")
            continue
        counts["total"] += len(records)
        print(f"  [{label}] 行数：{len(records)}")

        for rec in records:
            rid = str(rec.get("record_id") or "")
            if not rid:
                continue
            fields = rec.get("fields") or {}
            title = _extract_rich_text(fields.get("法律法规及标准名称")) or "(未命名)"
            attachments = _extract_attachment_list(fields.get("法规原件"))
            if not attachments:
                counts["skipped_no_attachment"] += 1
                continue
            counts["with_attachment"] += 1

            mapped = existing_maps.get(rid)
            if mapped is not None and mapped.status == "active" and mapped.kb_doc_id:
                counts["skipped_active"] += 1
                continue
            if mapped is not None and mapped.status == "failed" and mapped.kb_doc_id:
                # 上传成功但解析失败/超时：只补解析，不重复下载上传（幂等）
                pending.append(
                    {
                        "biz_key": rid,
                        "title": title,
                        "file_name": mapped.file_name or f"{rid}.pdf",
                        "kb_doc_id": mapped.kb_doc_id,
                    }
                )
                continue

            att = attachments[0]
            file_token = str(att.get("file_token") or "")
            file_name = str(att.get("name") or f"{rid}.pdf")
            try:
                blob = await client.download_attachment(file_token)
            except Exception as exc:
                counts["download_failed"] += 1
                report.fail("regulation", rid, title, "download", exc)
                continue
            if not blob:
                counts["download_failed"] += 1
                report.fail("regulation", rid, title, "download", "空文件")
                continue
            pending.append(
                {
                    "biz_key": rid,
                    "title": title,
                    "file_name": file_name,
                    "blob": blob,
                    "content_type": att.get("type") or "application/pdf",
                }
            )

    print(
        f"  待上传：{len(pending)}"
        f"（无附件跳过 {counts['skipped_no_attachment']}，已 active 跳过 {counts['skipped_active']}）"
    )
    if not apply or not pending:
        return
    await _upload_parse_and_register(
        admin,
        domain="regulation",
        dataset_name=KB_REGULATION,
        kb=kb,
        pending=pending,
        report=report,
    )


# ═══════════════════════════════════════════════════════════════
# MSDS 存量
# ═══════════════════════════════════════════════════════════════


async def ingest_msds(
    admin: RagplusAdminClient,
    kbs: dict[str, dict[str, Any]],
    apply: bool,
    report: Report,
) -> None:
    from app.core.database import async_session_factory
    from app.modules.safety.attachment_store import materialize
    from app.modules.safety.models import MsdsCollectionRecord

    kb = kbs[KB_MSDS]
    print(f"== MSDS 存量 → 「{KB_MSDS}」（kb_id={kb.get('id')}）==")

    async with async_session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(MsdsCollectionRecord).where(
                        MsdsCollectionRecord.attachment_path.isnot(None),
                        MsdsCollectionRecord.is_deleted.is_(False),
                    )
                )
            )
            .scalars()
            .all()
        )

    counts = report.counts["msds"]
    counts["total"] = len(rows)
    print(f"  有附件采集记录：{len(rows)}")

    existing_maps = await _load_existing_maps("msds") if apply else {}
    pending: list[dict[str, Any]] = []
    for row in rows:
        biz_key = str(row.id)
        date_label = row.source_date.isoformat() if row.source_date else "无日期"
        title = f"MSDS-{date_label}-{biz_key[:8]}"
        mapped = existing_maps.get(biz_key)
        if mapped is not None and mapped.status == "active" and mapped.kb_doc_id:
            counts["skipped_active"] += 1
            continue
        if mapped is not None and mapped.status == "failed" and mapped.kb_doc_id:
            # 上传成功但解析失败/超时：只补解析，不重复上传（幂等）
            counts["with_attachment"] += 1
            pending.append(
                {
                    "biz_key": biz_key,
                    "title": title,
                    "file_name": mapped.file_name or f"{biz_key}.pdf",
                    "kb_doc_id": mapped.kb_doc_id,
                }
            )
            continue
        path = row.attachment_path or ""
        local = materialize(path, suffix=".pdf")
        if local is None or not Path(local).exists() or Path(local).stat().st_size == 0:
            counts["download_failed"] += 1
            report.fail("msds", biz_key, title, "materialize", f"附件不可读：{path}")
            continue
        counts["with_attachment"] += 1
        blob = Path(local).read_bytes()
        if str(local) != path:  # MinIO 临时物化文件，读完即清
            Path(local).unlink(missing_ok=True)
        pending.append(
            {
                "biz_key": biz_key,
                "title": title,
                "file_name": Path(path).name or f"{biz_key}.pdf",
                "blob": blob,
            }
        )

    print(f"  待上传：{len(pending)}（已 active 跳过 {counts['skipped_active']}）")
    if not apply or not pending:
        return
    await _upload_parse_and_register(
        admin,
        domain="msds",
        dataset_name=KB_MSDS,
        kb=kb,
        pending=pending,
        report=report,
    )


# ═══════════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════════


async def main(apply: bool) -> int:
    print(f"== ragplus 存量全量入库（{'APPLY' if apply else 'DRY-RUN'}）==")

    admin = _admin_from_config()
    report = Report()
    try:
        kbs = await bootstrap(admin, apply)
    except Exception as exc:
        print(f"bootstrap 失败（ragplus 在跑吗？{admin.base_url}）：{exc}")
        return 2

    await ingest_regulations(admin, kbs, apply, report)
    await ingest_msds(admin, kbs, apply, report)
    await admin.aclose()

    report.dump()
    total_fail = sum(
        r["upload_failed"] + r["download_failed"] + r["parse_failed"]
        for r in report.counts.values()
    )
    print(f"== 完成：失败 {total_fail} 条 ==")
    return 1 if total_fail else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ragplus-x 存量全量入库（法规+MSDS）")
    ap.add_argument("--apply", action="store_true", help="真正执行（默认 dry-run）")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(args.apply)))
