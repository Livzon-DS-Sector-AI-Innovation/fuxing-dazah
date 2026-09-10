"""消防报警分析 — FireAlarmAnalyst（AI + RAG 分析器）。

流程:
  1. 对每条报警（上限 MAX_RECORDS_TO_ANALYZE）→ RAG 检索 → 独立 AI 调用
     → {dimension, reason_analysis, rectification_direction} → 回写内存对象
  2. 汇总 AI 调用 → {summary, key_issues, rectification_suggestions}
  3. 任何环节失败返回 None/跳过该条，报告退化为纯数据汇总版本，不阻塞生成与推送。

降级链路（backend-design.md §5.4）：
  - RAG 检索失败 → rag_md=""，LLM 仍调用（无参考法规）
  - 单条 AI 分析失败 → 该条不回写 ai_* 字段，其余照常
  - 汇总 AI 失败 → 返回 None，renderer 省略 AI 汇总块
所有 AI 调用包在 ai_audit_scope(scenario="fire_alarm_analysis") 内，channel 参数化。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit import ai_audit_scope
from app.modules.safety.models import FireAlarmRecord
from app.modules.safety.service.config import create_ai_service
from app.modules.safety.service.fire_alarm.aggregator import (
    FireAlarmDailyAgg,
    FireAlarmWeeklyAgg,
)
from app.modules.safety.service.fire_alarm.prompts import (
    EXPECTED_KEYS_DAILY_SUMMARY,
    EXPECTED_KEYS_PER_RECORD,
    EXPECTED_KEYS_WEEKLY_SUMMARY,
    build_daily_summary_messages,
    build_per_record_messages,
    build_weekly_summary_messages,
)

logger = logging.getLogger(__name__)

# 逐条 AI 分析上限（参照 special_op AIAnalyst 的 high[:15] 上限）
MAX_RECORDS_TO_ANALYZE = 50
# 并发限流（参照 AIAnalyst Semaphore(3)）
MAX_CONCURRENCY = 3


class FireAlarmAnalyst:
    """AI + RAG 报警分析器（逐条 + 汇总两级调用）。"""

    def __init__(self, session: AsyncSession, ai_service: Any = None) -> None:
        self.session = session
        self._ai = ai_service

    async def _get_ai(self) -> Any:
        if self._ai is None:
            self._ai = create_ai_service("text")
        return self._ai

    async def analyze_per_records(
        self, records: list[FireAlarmRecord], *, channel: str = "system",
    ) -> dict[str, dict[str, str]]:
        """逐条 AI 分析并回写记录（RAG + Semaphore 限流）。

        增量：跳过 ai_analyzed_at 已非空的记录（17:00 群日报与私发两个任务
        先后跑时，后跑者复用先跑者回写的 AI 结果，不重复调用 AI）。

        Returns:
            {"<record_id>": {dimension, reason_analysis, rectification_direction}}
            失败的记录不包含在返回中。

        回写只 setattr 内存对象（ai_dimension 已归一化为英文枚举），
        flush + commit 由调用方 service 统一处理（UPDATE 后 re-fetch 铁律）。
        """
        from app.core.database import async_session_factory

        targets = [
            r for r in records[:MAX_RECORDS_TO_ANALYZE]
            if getattr(r, "ai_analyzed_at", None) is None
        ]
        by_id = {str(r.id): r for r in targets}
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def _analyze_one(
            r: FireAlarmRecord,
        ) -> tuple[str, dict[str, str]] | None:
            try:
                # RAG 检索（失败降级为空，参照 AIAnalyst 的 try/except pass）
                rag_md = ""
                try:
                    from app.modules.safety.knowledge.retriever import (
                        SafetyKnowledgeRetriever,
                    )
                    rag_query = (
                        f"消防报警 {r.alarm_type or ''} {r.cause_category or ''} "
                        f"{(r.cause_description or '')[:100]}"
                    )
                    async with async_session_factory() as rag_session:
                        retriever = SafetyKnowledgeRetriever(rag_session)
                        ctx = await retriever.retrieve(
                            description=rag_query[:200],
                            categories=["laws_regulations", "standards", "management_systems"],
                            target_chunks=4,
                        )
                        rag_md = ctx.markdown or ""
                except Exception:
                    pass

                ai = await self._get_ai()
                messages = build_per_record_messages(r, rag_md)
                with ai_audit_scope(
                    scenario="fire_alarm_analysis",
                    resource_type="fire_alarm_record",
                    resource_id=r.id,
                    channel=channel,
                ):
                    result = await ai.chat_parsed(
                        messages=messages,
                        expected_keys=EXPECTED_KEYS_PER_RECORD,
                        temperature=0.3,
                    )
                return str(r.id), {
                    "dimension": result.get("dimension", ""),
                    "reason_analysis": result.get("reason_analysis", ""),
                    "rectification_direction": result.get("rectification_direction", ""),
                }
            except Exception:
                logger.warning("单条 AI 分析失败 record_id=%s", r.id)
                return None

        async def _with_sem(r: FireAlarmRecord) -> tuple[str, dict[str, str]] | None:
            async with sem:
                return await _analyze_one(r)

        results = await asyncio.gather(
            *[_with_sem(r) for r in targets], return_exceptions=True,
        )

        out: dict[str, dict[str, str]] = {}
        now = datetime.now(UTC)
        for result in results:
            if isinstance(result, BaseException) or result is None:
                continue
            rid, analysis = result
            out[rid] = analysis
            r = by_id.get(rid)
            if r is None:
                continue
            r.ai_dimension = _normalize_dimension(analysis.get("dimension", ""))
            r.ai_reason_analysis = analysis.get("reason_analysis", "")
            r.ai_rectification_direction = analysis.get("rectification_direction", "")
            r.ai_analyzed_at = now
        return out

    async def analyze_daily_summary(
        self, agg: FireAlarmDailyAgg, per_summaries: list[str], *,
        channel: str = "system",
    ) -> dict[str, Any] | None:
        """日报汇总 AI 分析；失败返回 None（调用方省略 AI 块）。"""
        try:
            ai = await self._get_ai()
            messages = build_daily_summary_messages(agg, per_summaries)
            with ai_audit_scope(
                scenario="fire_alarm_analysis",
                resource_type="fire_alarm_daily_report",
                channel=channel,
            ):
                result = await ai.chat_parsed(
                    messages=messages,
                    expected_keys=EXPECTED_KEYS_DAILY_SUMMARY,
                    temperature=0.3,
                )
            return result if isinstance(result, dict) else None
        except Exception:
            logger.warning("日报汇总 AI 分析失败")
            return None

    async def analyze_weekly_summary(
        self, agg: FireAlarmWeeklyAgg, *, channel: str = "system",
    ) -> dict[str, Any] | None:
        """周报汇总 AI 分析；失败返回 None（ticket 06 使用）。"""
        try:
            ai = await self._get_ai()
            messages = build_weekly_summary_messages(agg)
            with ai_audit_scope(
                scenario="fire_alarm_analysis",
                resource_type="fire_alarm_weekly_report",
                channel=channel,
            ):
                result = await ai.chat_parsed(
                    messages=messages,
                    expected_keys=EXPECTED_KEYS_WEEKLY_SUMMARY,
                    temperature=0.3,
                )
            return result if isinstance(result, dict) else None
        except Exception:
            logger.warning("周报汇总 AI 分析失败")
            return None


def _normalize_dimension(raw: str) -> str | None:
    """AI 返回的维度中文 → 英文枚举（process/operation/equipment/other）。

    未识别文本归入 other；空值返回 None（不回写 ai_dimension）。
    """
    mapping = {
        "工艺": "process", "人员操作": "operation", "设备设施": "equipment", "其他": "other",
    }
    return mapping.get(raw.strip()) or ("other" if raw else None)
