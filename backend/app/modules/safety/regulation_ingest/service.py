"""法规收录服务（契约①接收侧处理链）。

处理链：鉴权（API 层）→ 总闸 → 幂等重放 → 预去重（vs Bitable 台账）→
AI 批量相关性判定（token 预算护栏，ai_config 场景 regulation_ingest）→
台账写入（含修订编排）→ 契约②生命周期回执 → doc_map 登记 → 飞书推送
→ run 级留痕。

本模块只 flush 不 commit（请求级事务由 get_db 收口，测试走回滚
session 零残留）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit import ai_audit_scope
from app.modules.safety.app_config.store import store as app_config_store
from app.modules.safety.models import RegulationIngestRun
from app.modules.safety.regulation_crawler.engine.extractors import AIExtractor
from app.modules.safety.regulation_crawler.notifier.push_notifier import PushNotifier
from app.modules.safety.regulation_crawler.schemas import (
    CrawledRegulation,
    CrawlItemResult,
    CrawlResultSummary,
)
from app.modules.safety.regulation_crawler.writer.bitable_writer import (
    BitableWriter,
    _extract_document_number,
    _extract_plain_text,
    _extract_standard_identifier,
    _normalize_title,
)
from app.modules.safety.regulation_ingest.ragplus_crawler_client import (
    get_ragplus_crawler_client,
)
from app.modules.safety.regulation_ingest.schemas import (
    IngestCandidateItem,
    IngestCandidatesRequest,
    IngestCandidatesResponse,
    IngestItemResult,
)

logger = logging.getLogger(__name__)

# 收录总闸沿用既有键（原爬虫调度开关，语义升级为收录服务总闸）
_INGEST_ENABLED_KEY = "SAFETY_REGULATION_CRAWLER_ENABLED"
# 单批 AI token 预算上限（超限标 pending 留痕，不调 AI）
_MAX_AI_TOKENS_KEY = "SAFETY_REGULATION_CRAWLER_MAX_AI_TOKENS_PER_RUN"

# AI 相关性判定阈值（content_type=regulation 且 score 达标 → 相关）
_RELEVANCE_THRESHOLD = 0.5
# 批量判定 prompt 固定开销粗估（每批 system+模板 token）
_PROMPT_OVERHEAD_TOKENS_PER_BATCH = 600

# 幂等锚点只认已处理完成的行（skipped/failed 可重试多行，与唯一索引口径一致）
_STATUS_COMPLETED = "completed"
_STATUS_SKIPPED_DISABLED = "skipped_disabled"


class RegulationIngestService:
    """契约①候选批次收录处理。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.writer = BitableWriter()
        self.extractor = AIExtractor()

    # ── 主入口 ──────────────────────────────────────────────

    async def ingest_candidates(
        self, payload: IngestCandidatesRequest,
    ) -> IngestCandidatesResponse:
        # ① 总闸：关闭时跳过处理并留痕（不锚定幂等，开闸后重推可正常处理）
        if not app_config_store.get_bool(_INGEST_ENABLED_KEY, False):
            run = await self._record_run(
                payload,
                status=_STATUS_SKIPPED_DISABLED,
                error_summary="收录总闸关闭，跳过处理",
            )
            return IngestCandidatesResponse(
                accepted=False,
                run_log_id=str(run.id),
                reason="disabled",
            )

        # ② 幂等：同 run_id 已处理完成 → 直接返回既有结果（不重复写台账/回执）
        existing = await self._find_completed_run(payload.run_id)
        if existing is not None:
            return IngestCandidatesResponse(
                accepted=True,
                run_log_id=str(existing.id),
                results=[IngestItemResult(**r) for r in (existing.items_result or [])],
            )

        # ③ 预去重 → AI 判定 → 执行链 → 逐条结果
        results, ai_tokens_used, receipts = await self._process_items(payload.items)

        # ④ run 级留痕 + 响应
        counts = self._count_results(results)
        run = await self._record_run(
            payload,
            status=_STATUS_COMPLETED,
            results=results,
            counts=counts,
            ai_tokens_used=ai_tokens_used,
            receipts=receipts,
        )
        return IngestCandidatesResponse(
            accepted=True, run_log_id=str(run.id), results=results,
        )

    # ── 处理链 ──────────────────────────────────────────────

    async def _process_items(
        self, items: list[IngestCandidateItem],
    ) -> tuple[list[IngestItemResult], int, dict[str, Any]]:
        """逐条候选处理：预去重 → AI 批量判定 → 执行链（写入/回执）。

        返回 (逐条结果, AI token 预估消耗, 回执记录)。
        """
        results: list[IngestItemResult] = []
        receipts: dict[str, Any] = {}
        try:
            keys = await self._load_existing_standard_keys()
        except Exception:
            logger.exception("加载台账已有标准键失败，本批跳过预去重（保守放行）")
            keys = {"exact_titles": set(), "norm_titles": set(),
                    "std_to_years": {}, "doc_numbers": set()}

        passed: list[IngestCandidateItem] = []
        for item in items:
            dup_reason = self._duplicate_reason(item, keys)
            if dup_reason:
                results.append(IngestItemResult(
                    candidate_id=item.candidate_id,
                    action_taken="duplicate",
                    reason=dup_reason,
                ))
                continue
            passed.append(item)

        verdicts, ai_tokens = await self._classify_items(passed)
        to_execute: list[tuple[IngestCandidateItem, dict[str, Any]]] = []
        for item in passed:
            verdict = verdicts.get(item.candidate_id)
            disposition, reason = self._verdict_disposition(item, verdict)
            if disposition == "execute":
                assert verdict is not None  # execute 分派仅在判定存在时发生
                to_execute.append((item, verdict))
            elif disposition == "reject":
                results.append(await self._finalize_reject(item, reason, receipts))
            else:
                results.append(IngestItemResult(
                    candidate_id=item.candidate_id,
                    action_taken="pending",
                    reason=reason,
                ))

        for item, verdict in to_execute:
            results.append(await self._execute_promotion(item, verdict, receipts))

        await self._notify_batch(items, results)
        return results, ai_tokens, receipts

    # ── AI 批量判定（token 预算护栏） ───────────────────────

    async def _classify_items(
        self, items: list[IngestCandidateItem],
    ) -> tuple[dict[str, dict[str, Any]], int]:
        """AI 批量相关性判定（移植既有批量判定段，场景 regulation_ingest）。

        返回 ({candidate_id: 判定字段}, token 预估)。预算超限时返回
        ({}, 0) 且不发起 AI 调用（调用方整批判 pending）。
        """
        if not items:
            return {}, 0

        batch_inputs = [
            {
                "index": idx,
                "title": item.title or "",
                "source_url": item.url or "",
                "raw_text": (
                    item.content_digest
                    if (item.content_digest and len(item.content_digest.strip()) >= 50)
                    else f"标题: {item.title}\n来源: {item.url}"
                ) or "",
            }
            for idx, item in enumerate(items)
        ]

        est_tokens = self._estimate_tokens(batch_inputs)
        budget = app_config_store.get_int(_MAX_AI_TOKENS_KEY, 20000)
        if est_tokens > budget:
            logger.warning(
                "AI 判定预算超限：预估 %d > 预算 %d，本批 %d 条标 pending",
                est_tokens, budget, len(items),
            )
            return {}, 0

        with ai_audit_scope(
            scenario="regulation_ingest", channel="system",
            extra={"entry": "regulation_ingest", "items": len(items)},
        ):
            try:
                batch_results = await self.extractor.classify_and_assess_batch(batch_inputs)
            except Exception:
                logger.exception("批量判定失败")
                batch_results = []

        verdicts: dict[str, dict[str, Any]] = {}
        if batch_results:
            by_index = {r["index"]: r for r in batch_results if "index" in r}
            for idx, item in enumerate(items):
                br = by_index.get(idx)
                if br is not None:
                    verdicts[item.candidate_id] = br
        else:
            # 批量失败 → 逐条回退（移植既有降级模式：行业相关性终判）
            for item in items:
                try:
                    relevant = await self.extractor.check_industry_relevance(
                        item.title or "",
                    )
                    verdicts[item.candidate_id] = {
                        "content_type": "regulation",
                        "fallback": True,
                        "industry_relevant": bool(relevant),
                    }
                except Exception:
                    logger.exception("逐条回退判定失败: %s", item.title)
        return verdicts, est_tokens

    @staticmethod
    def _estimate_tokens(batch_inputs: list[dict[str, Any]]) -> int:
        """粗估本批 token（中文 1 字≈1 token 保守口径 + 每批 prompt 开销）。

        精确 token 以 ai_call_audits 审计为准；此预估仅用于预算护栏熔断。
        """
        batches = max(1, (len(batch_inputs) + 19) // 20)
        text_tokens = sum(
            len(str(b.get("title") or "")) + len(str(b.get("raw_text") or ""))
            for b in batch_inputs
        )
        return text_tokens + batches * _PROMPT_OVERHEAD_TOKENS_PER_BATCH

    @staticmethod
    def _verdict_disposition(
        item: IngestCandidateItem, verdict: dict[str, Any] | None,
    ) -> tuple[str, str]:
        """AI 判定 → 处置分派。

        返回 (disposition, reason)：execute=进入收录执行链；reject=不相关；
        pending=未判定（预算超限/判定失败，待复核）。
        """
        if verdict is None:
            return "pending", "未判定（AI 预算超限或判定失败），待复核"
        content_type = (verdict.get("content_type") or "regulation").strip()
        if content_type not in ("regulation", "news", "speech", "other"):
            content_type = "regulation"
        if content_type != "regulation":
            return "reject", f"内容类型 {content_type}，非法规"
        if verdict.get("fallback"):
            if not bool(verdict.get("industry_relevant")):
                return "reject", "AI 判定与本厂业务不相关（逐条回退）"
            return "execute", "判定相关（逐条回退）"
        score = verdict.get("relevance_score")
        if isinstance(score, (int, float)) and score < _RELEVANCE_THRESHOLD:
            return "reject", f"AI 判定不相关（score={score}）"
        score_txt = f"score={score}" if isinstance(score, (int, float)) else "score=高"
        return "execute", f"判定相关（{score_txt}）"

    # ══════════════════════════════════════════════════════════
    # 收录执行链（写入/修订编排/回执/doc_map）
    # ══════════════════════════════════════════════════════════

    async def _execute_promotion(
        self,
        item: IngestCandidateItem,
        verdict: dict[str, Any],
        receipts: dict[str, Any],
    ) -> IngestItemResult:
        """判定相关候选的收录执行：写台账（含修订编排）→ 回执 → doc_map。

        各环节独立容错：写入失败=error（无回执，留待对账补处理）；
        回执失败不改变收录结果（reason 注记，receipts 记错误）。
        """
        crawled = self._to_crawled(item, verdict)
        related_old_title: str | None = None
        try:
            # 修订/替代检测（契约 old_version_hint + 标题关键词，移植既有口径）
            if item.old_version_hint or self.extractor.has_revision_indicator(item.title or ""):
                old = await self._find_old_version(crawled.title)
                if old:
                    related_old_title = old["title"]
                    crawled.related_old_title = related_old_title

            write = await self.writer.write_regulation(crawled)
        except Exception as exc:
            logger.exception("台账写入失败: %s", item.title)
            return IngestItemResult(
                candidate_id=item.candidate_id,
                action_taken="error",
                reason=f"台账写入失败: {str(exc)[:150]}",
            )

        _, base_reason = self._verdict_disposition(item, verdict)
        if related_old_title:
            base_reason += f"，修订替代《{related_old_title}》"

        if write is None:
            # 写入层去重兜底（TOCTOU/三层分类命中）：候选使命完成，仍回执转正
            ok, err = await self._send_receipt(
                item.candidate_id, "promote", f"{base_reason}（台账已有，写入层去重）",
                receipts,
            )
            reason = f"{base_reason}（台账已有，写入层去重）"
            if not ok:
                reason += f"；回执失败: {err}"
            return IngestItemResult(
                candidate_id=item.candidate_id,
                action_taken="promote", reason=reason,
            )

        record_id = write.get("record_id", "")
        # doc_map 登记（biz_key=台账 record_id；kb/engine 文档 id 由 ragplus
        # 转正后经映射对账工具回填）
        try:
            from app.modules.safety.knowledge.ragplus_sync import (
                KB_REGULATION,
                upsert_ragplus_map,
            )

            await upsert_ragplus_map(
                self.session,
                domain="regulation",
                biz_key=record_id,
                dataset_name=KB_REGULATION,
                status="active",
                title=item.title,
            )
        except Exception:
            logger.exception("doc_map 登记失败: record_id=%s", record_id)

        ok, err = await self._send_receipt(
            item.candidate_id, "promote", base_reason, receipts,
        )
        reason = base_reason + (f"（{write.get('action', 'created')}）" if write.get("action") else "")
        if not ok:
            reason += f"；回执失败: {err}"
        return IngestItemResult(
            candidate_id=item.candidate_id,
            action_taken="promote",
            reason=reason,
            bitable_record_id=record_id or None,
        )

    async def _finalize_reject(
        self,
        item: IngestCandidateItem,
        reason: str,
        receipts: dict[str, Any],
    ) -> IngestItemResult:
        """判定不相关：reject 回执（候选终态），不写台账。"""
        ok, err = await self._send_receipt(
            item.candidate_id, "reject", reason, receipts,
        )
        final_reason = reason if ok else f"{reason}；回执失败: {err}"
        return IngestItemResult(
            candidate_id=item.candidate_id,
            action_taken="reject",
            reason=final_reason,
        )

    async def _send_receipt(
        self,
        candidate_id: str,
        action: str,
        reason: str,
        receipts: dict[str, Any],
        replace_candidate_id: str | None = None,
    ) -> tuple[bool, str | None]:
        """契约②回执调用（失败容错：返回错误并记入 receipts，不抛出）。"""
        try:
            client = get_ragplus_crawler_client()
            await client.send_lifecycle(
                candidate_id, action, reason, replace_candidate_id,
            )
            receipts[candidate_id] = {"action": action, "ok": True}
            return True, None
        except Exception as exc:
            logger.warning("契约②回执失败: %s %s: %s", action, candidate_id, exc)
            receipts[candidate_id] = {
                "action": action, "ok": False, "error": str(exc)[:200],
            }
            return False, str(exc)[:150]

    @staticmethod
    def _to_crawled(
        item: IngestCandidateItem, verdict: dict[str, Any],
    ) -> CrawledRegulation:
        """契约①候选 + AI 判定 → 台账写入模型（字段映射）。"""
        return CrawledRegulation(
            title=item.title,
            document_number=item.metadata.doc_no,
            publish_date=item.metadata.issued_at,
            implementation_date=item.metadata.effective_at,
            issuing_authority=item.metadata.puborg,
            source_url=item.url,
            source_type=item.source,
            raw_text=item.content_digest,
            content_type=verdict.get("content_type"),
            impact_level=verdict.get("impact_level"),
            business_domains=verdict.get("business_domains"),
            relevance_score=verdict.get("relevance_score"),
            core_summary=verdict.get("core_summary"),
        )

    async def _find_old_version(self, title: str) -> dict[str, str] | None:
        """在台账中查找可能的旧版法规（归一化标题模糊匹配，移植既有逻辑）。"""
        try:
            norm = _normalize_title(title)
            if len(norm) < 4:
                return None
            records: list[dict[str, Any]] = []
            for client in (self.writer.safety_bitable, self.writer.env_bitable):
                records.extend(await client.list_all_records(page_size=100))
            best_match: dict[str, str] | None = None
            best_score = 0
            for record in records:
                fields = record.get("fields", {}) or {}
                existing = _extract_plain_text(fields.get("法律法规及标准名称"))
                if not existing:
                    continue
                existing_norm = _normalize_title(existing)
                if len(existing_norm) < 4:
                    continue
                if norm in existing_norm or existing_norm in norm:
                    score = len(existing_norm)
                    if score > best_score:
                        best_score = score
                        best_match = {
                            "title": existing,
                            "publish_date": str(fields.get("颁布修订日期", "")),
                            "summary": str(fields.get("核心要点总结", "")),
                        }
            if best_match:
                logger.info("找到旧版法规: new=%s old=%s", title, best_match["title"])
            return best_match
        except Exception:
            logger.exception("查找旧版法规失败: title=%s", title)
            return None

    async def _notify_batch(
        self, items: list[IngestCandidateItem], results: list[IngestItemResult],
    ) -> None:
        """批次飞书推送（复用既有分级卡片，失败只留痕不阻断）。"""
        promoted = [r for r in results if r.action_taken == "promote"]
        if not promoted:
            return
        titles = {i.candidate_id: i.title for i in items}
        summary = CrawlResultSummary(
            new_count=len(promoted),
            items=[
                CrawlItemResult(
                    title=titles.get(r.candidate_id, r.candidate_id),
                    status="created",
                    action="created",
                )
                for r in promoted
            ],
        )
        try:
            notifier = PushNotifier()
            await notifier.send_crawl_result_notification(summary)
        except Exception:
            logger.exception("收录结果飞书推送失败（不阻断收录链）")

    async def _load_existing_standard_keys(self) -> dict[str, Any]:
        """加载 Bitable 已有记录的标准号/文号/标题集合（双表单次拉取）。

        移植自 regulation_crawler 预去重段；Bitable 是唯一权威台账，
        查重必须在本端执行。
        """
        records: list[dict[str, Any]] = []
        for client in (self.writer.safety_bitable, self.writer.env_bitable):
            records.extend(await client.list_all_records(page_size=500))
        exact_titles: set[str] = set()
        norm_titles: set[str] = set()
        std_to_years: dict[str, set[str]] = {}
        doc_numbers: set[str] = set()
        for rec in records:
            fields = rec.get("fields", {}) or {}
            title = _extract_plain_text(fields.get("法律法规及标准名称")).strip()
            if not title:
                continue
            exact_titles.add(title)
            nt = _normalize_title(title)
            if nt:
                norm_titles.add(nt)
            std, year = _extract_standard_identifier(title)
            if std:
                std_to_years.setdefault(std, set()).add(year)
            doc = _extract_document_number(title)
            if doc:
                doc_numbers.add(doc)
        return {
            "exact_titles": exact_titles,
            "norm_titles": norm_titles,
            "std_to_years": std_to_years,
            "doc_numbers": doc_numbers,
        }

    @staticmethod
    def _duplicate_reason(
        item: IngestCandidateItem, keys: dict[str, Any],
    ) -> str | None:
        """判定候选是否已在台账（三路匹配，移植既有逻辑）。

        返回命中原因文案；None=未命中（放行进入判定）。
        契约①候选自带 metadata.doc_no，额外参与文号比对。
        """
        title = (item.title or "").strip()
        if title:
            # ① 标题精确 / 归一化匹配
            if title in keys["exact_titles"]:
                return "标题已在台账"
            if _normalize_title(title) in keys["norm_titles"]:
                return "归一化标题已在台账"
            # ② 标准号：同年份=重复；不同年份=新版（放行走修订编排）
            std, year = _extract_standard_identifier(title)
            if std and std in keys["std_to_years"]:
                if year in keys["std_to_years"][std]:
                    return f"标准号 {std}（{year}）已在台账"
                return None
            # ③ 文号匹配（标题提取 + 候选自带）
            doc = _extract_document_number(title)
            if doc and doc in keys["doc_numbers"]:
                return f"文号 {doc} 已在台账"
        doc_no = (item.metadata.doc_no or "").strip()
        if doc_no and doc_no in keys["doc_numbers"]:
            return f"文号 {doc_no} 已在台账"
        return None

    # ── 留痕 ────────────────────────────────────────────────

    async def _find_completed_run(self, run_id: str) -> RegulationIngestRun | None:
        stmt = select(RegulationIngestRun).where(
            RegulationIngestRun.source_run_id == run_id,
            RegulationIngestRun.status == _STATUS_COMPLETED,
            RegulationIngestRun.is_deleted.is_(False),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _record_run(
        self,
        payload: IngestCandidatesRequest,
        *,
        status: str,
        results: list[IngestItemResult] | None = None,
        counts: dict[str, int] | None = None,
        error_summary: str | None = None,
        ai_tokens_used: int = 0,
        receipts: dict[str, Any] | None = None,
    ) -> RegulationIngestRun:
        counts = counts or {}
        items_result = None
        if results is not None:
            # 留痕逐条附加 title/url/attachment_missing（内部口径，非契约①响应字段）
            # 供监控 feed/原文待补统计消费
            by_candidate = {i.candidate_id: i for i in payload.items}
            items_result = []
            for r in results:
                extra = by_candidate.get(r.candidate_id)
                items_result.append({
                    **r.model_dump(),
                    "title": extra.title if extra else None,
                    "url": extra.url if extra else None,
                    "attachment_missing": bool(
                        extra is not None and not extra.attachment.file_id
                    ),
                })
        run = RegulationIngestRun(
            source_run_id=payload.run_id,
            source="push",
            status=status,
            received_count=len(payload.items),
            duplicate_count=counts.get("duplicate", 0),
            pending_count=counts.get("pending", 0),
            promoted_count=counts.get("promote", 0),
            rejected_count=counts.get("reject", 0),
            failed_count=counts.get("error", 0),
            ai_tokens_used=ai_tokens_used,
            items_result=items_result,
            receipts=receipts or None,
            error_summary=error_summary,
            finished_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    @staticmethod
    def _count_results(results: list[IngestItemResult]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in results:
            counts[r.action_taken] = counts.get(r.action_taken, 0) + 1
        return counts
