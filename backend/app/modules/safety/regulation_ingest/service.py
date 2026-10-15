"""法规收录服务（契约①接收侧处理链）。

处理链（一期骨架）：鉴权（API 层）→ 总闸 → 幂等重放 → 预去重（vs Bitable
台账，移植 regulation_crawler 预过滤逻辑）→ [AI 批量判定] → [台账写入/
修订编排/回执/doc_map/推送] → run 级留痕。

判定与执行段随票据逐步填充；本模块只 flush 不 commit（请求级事务由
get_db 收口，测试走回滚 session 零残留）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.app_config.store import store as app_config_store
from app.modules.safety.models import RegulationIngestRun
from app.modules.safety.regulation_crawler.writer.bitable_writer import (
    BitableWriter,
    _extract_document_number,
    _extract_plain_text,
    _extract_standard_identifier,
    _normalize_title,
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

# 幂等锚点只认已处理完成的行（skipped/failed 可重试多行，与唯一索引口径一致）
_STATUS_COMPLETED = "completed"
_STATUS_SKIPPED_DISABLED = "skipped_disabled"


class RegulationIngestService:
    """契约①候选批次收录处理。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.writer = BitableWriter()

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

        # ③ 预去重 → 判定 → 逐条结果（判定/执行段随票据填充）
        results = await self._process_items(payload.items)

        # ④ run 级留痕 + 响应
        counts = self._count_results(results)
        run = await self._record_run(
            payload,
            status=_STATUS_COMPLETED,
            results=results,
            counts=counts,
        )
        return IngestCandidatesResponse(
            accepted=True, run_log_id=str(run.id), results=results,
        )

    # ── 处理链 ──────────────────────────────────────────────

    async def _process_items(
        self, items: list[IngestCandidateItem],
    ) -> list[IngestItemResult]:
        """逐条候选处理：预去重 → （AI 判定/执行段随票据填充）。"""
        results: list[IngestItemResult] = []
        try:
            keys = await self._load_existing_standard_keys()
        except Exception:
            logger.exception("加载台账已有标准键失败，本批跳过预去重（保守放行）")
            keys = {"exact_titles": set(), "norm_titles": set(),
                    "std_to_years": {}, "doc_numbers": set()}

        for item in items:
            dup_reason = self._duplicate_reason(item, keys)
            if dup_reason:
                results.append(IngestItemResult(
                    candidate_id=item.candidate_id,
                    action_taken="duplicate",
                    reason=dup_reason,
                ))
                continue
            # AI 判定与执行链（02/03 票填充）：当前标记 pending 留痕
            results.append(IngestItemResult(
                candidate_id=item.candidate_id,
                action_taken="pending",
                reason="判定管线接入前置态",
            ))
        return results

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
    ) -> RegulationIngestRun:
        counts = counts or {}
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
            items_result=[r.model_dump() for r in results] if results else None,
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
