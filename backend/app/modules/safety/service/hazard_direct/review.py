"""② AI整改审核轮询 — 直读多维表格，不落库。

链路：
    search(纠正预防措施非空 AND AI初审结果空 AND 整改状态 isNot 已关闭)
      → per-record 锁 → 下载缺陷图 + 整改后图 → 视觉AI 对比 + RAG
      → 结构化输出 → 写回「AI初审结果」+「AI初审说明」

闸门说明（重要）：多维表格「整改状态」**不会自动变成整改中**（无自动化），
因此不能用 `整改状态 is 整改中` 作判据；改用「已填整改回复 + 未初审 + 未关闭」，
不依赖任何自动化即可捕获。

结论映射（以多维表格字段值为准）：
    通过 → 已通过 ／ 不通过 → 未通过 ／ 无需整改 → 无需整改
    未知或解析失败 → **不写该字段**（保持空，下一轮自动重试）
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.service.hazard_direct import bitable_repo, config
from app.modules.safety.service.hazard_direct.alert import notify_failures

logger = logging.getLogger(__name__)

# 进程级写回锁（同 ai_analysis：手动触发与定时轮询可能并发，需共享同一把锁）
_WRITE_LOCK = asyncio.Lock()


@dataclass
class ReviewRoundResult:
    """单轮执行结果。"""

    job_label: str = "隐患整改审核轮询"
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    no_conclusion: int = 0
    failures: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_label": self.job_label,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "no_conclusion": self.no_conclusion,
            "failures": self.failures,
        }


async def _load_knowledge_context(session: Any, description: str) -> str | None:
    """RAG 法规检索（知识库仍在平台数据库）。"""
    try:
        from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

        retriever = SafetyKnowledgeRetriever(session)
        context = await retriever.retrieve(description=description, target_chunks=8)
        return retriever.build_injection_context(context)
    except Exception:
        logger.warning("② RAG 法规检索失败，继续不使用知识增强", exc_info=True)
        return None


async def _review_one(client: Any, view: bitable_repo.HazardView) -> dict[str, Any]:
    """调用 AI 整改初审插件，返回结构化输出 dict（不做任何写回）。"""
    from app.modules.safety.ai_rectification_review import (
        AIRectificationReviewer,
        RectificationReviewInput,
    )
    from app.modules.safety.ai_rectification_review import (
        PluginConfig as ReviewPluginConfig,
    )
    from app.modules.safety.service.config import create_ai_service

    photos = await bitable_repo.download_photos(
        client, view.raw, record_id=view.record_id
    )
    defect_uris = bitable_repo.photos_to_data_uris(photos.get("defect", []))
    rectify_uris = bitable_repo.photos_to_data_uris(photos.get("rectification", []))

    advice = bitable_repo.f_text(view.raw, bitable_repo.F_ADVICE_AI)
    input_data = RectificationReviewInput(
        hazard_id=None,
        original_description=view.description or "",
        original_defect_photos=defect_uris,
        key_defect=bitable_repo.f_text(view.raw, bitable_repo.F_DESC_AI),
        hazard_type=bitable_repo.f_select(view.raw, bitable_repo.F_TYPE_AI),
        hazard_category=bitable_repo.f_select(view.raw, bitable_repo.F_CATEGORY_AI),
        hazard_level=bitable_repo.f_select(view.raw, bitable_repo.F_LEVEL_AI),
        ai_rectification_suggestion={"raw": advice} if advice else None,
        rectification_reply=view.rectify_reply,
        rectification_photos=rectify_uris,
        department=view.department or "",
        defect_substance="",
        defect_substance_reasoning="",
    )

    ai_service = create_ai_service("vision" if rectify_uris else "text")
    try:
        knowledge_context = None
        from app.core.database import async_session_factory

        async with async_session_factory() as session:
            knowledge_context = await _load_knowledge_context(session, view.description)

        plugin_config = ReviewPluginConfig(
            temperature=0.05,
            strict_mode=False,
            enable_vision=bool(rectify_uris),
            enable_knowledge=bool(knowledge_context),
        )
        from app.modules.safety.ai_audit import ai_audit_scope

        with ai_audit_scope(
            scenario="rectification_review",
            resource_type="hazard",
            channel="system",
            extra={"bitable_record_id": view.record_id, "source": "bitable_direct"},
        ):
            plugin = AIRectificationReviewer(
                ai_service, plugin_config, knowledge_context=knowledge_context
            )
            output = await plugin.review(input_data)

        return {
            "defect_reassessment": output.defect_reassessment,
            "defect_reassessment_level": output.defect_reassessment_level,
            "photo_match_analysis": output.photo_match_analysis,
            "photo_match_level": output.photo_match_level.value,
            "measure_quality_assessment": output.measure_quality_assessment,
            "measure_quality_level": output.measure_quality_level.value,
            "standard_compliance": output.standard_compliance,
            "standard_compliance_level": output.standard_compliance_level.value,
            "review_conclusion": output.review_conclusion.value,
            "review_comments": output.review_comments,
            "confidence": output.confidence,
            "reasoning": output.reasoning,
        }
    finally:
        await ai_service.close()


async def run_review_round(
    *, limit: int | None = None, notify: bool = True
) -> ReviewRoundResult:
    """执行一轮 ② AI整改审核。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard import _build_ai_review_summary

    result = ReviewRoundResult()
    client = SafetyBitableClient()
    records = await bitable_repo.search_pending_review(client, limit=limit)
    result.total = len(records)
    if not records:
        logger.info("② 无待审核记录")
        return result

    logger.info("② 待审核 %d 条（判据: 已填回复 + 未初审 + 未关闭）", len(records))
    write_lock = _WRITE_LOCK
    semaphore = asyncio.Semaphore(config.write_concurrency())

    async def _worker(record: dict[str, Any]) -> None:
        record_id = record.get("record_id", "")
        if not record_id:
            return
        async with bitable_repo.record_lock(record_id) as acquired:
            if not acquired:
                result.skipped += 1
                logger.info("② 跳过（记录锁被占用）: record_id=%s", record_id)
                return
            try:
                async with semaphore:
                    view = bitable_repo.to_view(record)
                    output = await _review_one(client, view)

                conclusion = (output.get("review_conclusion") or "").strip()
                mapped = bitable_repo.REVIEW_CONCLUSION_MAP.get(conclusion)
                if not mapped:
                    # 未知结论：不写字段，保持空 → 下一轮自动重试（不兜底写错值）
                    result.no_conclusion += 1
                    logger.warning(
                        "② 未知初审结论 %r，不写字段: record_id=%s", conclusion, record_id
                    )
                    return

                async with write_lock:
                    ok = await bitable_repo.write_review(
                        client,
                        record_id,
                        conclusion=mapped,
                        summary=_build_ai_review_summary(output),
                    )
                    if not ok:
                        raise RuntimeError("写回 Bitable 返回 False")

                result.succeeded += 1
                logger.info(
                    "② 完成: record_id=%s 结论=%s", record_id, mapped
                )
            except Exception as exc:
                result.failed += 1
                result.failures.append(
                    {"record_id": record_id, "reason": f"{type(exc).__name__}: {exc}"[:200]}
                )
                logger.exception("② 处理失败（不写字段，下轮自动重试）: record_id=%s", record_id)

    await asyncio.gather(*(_worker(rec) for rec in records))

    logger.info(
        "② 本轮结束: 总数=%d 成功=%d 失败=%d 跳过=%d 无结论=%d",
        result.total, result.succeeded, result.failed, result.skipped, result.no_conclusion,
    )
    if notify and len(result.failures) >= config.alert_min_failures():
        await notify_failures(
            result.job_label,
            failures=result.failures,
            total=result.total,
        )
    return result
