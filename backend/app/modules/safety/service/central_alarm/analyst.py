"""中控报警分析 — CentralAlarmAnalyst（AI + 历史上下文分析器）。

流程:
  1. 对每条报警（上限 MAX_RECORDS_TO_ANALYZE）→ 本地表查询历史趋势上下文
     → 独立 AI 调用 → {alarm_type, equipment, pattern, dimension,
     reason_analysis, rectification_direction} → 回写内存对象
  2. 汇总 AI 调用 → {summary, key_issues, rectification_suggestions}
  3. 任何环节失败返回 None/跳过该条，报告退化为纯数据汇总版本。

区别（与 fire_alarm）：本功能「关联历史数据」= 历史趋势对比（同设备/同岗位上周同期、
本周重复计数），而非知识库 RAG。历史上下文从本地表查询，失败降级为空。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.ai_audit import ai_audit_scope
from app.modules.safety.models import CentralAlarmRecord
from app.modules.safety.service.central_alarm.aggregator import CentralAlarmDailyAgg
from app.modules.safety.service.central_alarm.prompts import (
    EXPECTED_KEYS_DAILY_SUMMARY,
    EXPECTED_KEYS_PER_RECORD,
    build_daily_summary_messages,
    build_per_record_messages,
)
from app.modules.safety.service.config import create_ai_service

logger = logging.getLogger(__name__)

# 逐条 AI 分析上限 + 并发限流（参照 fire_alarm / AIAnalyst）
MAX_RECORDS_TO_ANALYZE = 50
MAX_CONCURRENCY = 3


class CentralAlarmAnalyst:
    """AI + 历史上下文报警分析器（逐条 + 汇总两级调用）。"""

    def __init__(self, session: AsyncSession, ai_service: Any = None) -> None:
        self.session = session
        self._ai = ai_service

    async def _get_ai(self) -> Any:
        if self._ai is None:
            self._ai = create_ai_service("text")
        return self._ai

    async def _load_history_context(self, record: CentralAlarmRecord) -> str:
        """本地表查询同(workshop, line, post)上周同期 + 本周重复计数 → JSON 字符串。

        - 本周窗口：报警日期所在自然周（周一~周日）
        - 上周同期：上周同一自然周
        - 只统计非软删 + 同 workshop/line/post 的报警
        返回紧凑 JSON（供 AI 判断 pattern），失败返回 ""。
        """
        try:
            from .aggregator import get_natural_week_range

            if not record.alarm_date:
                return ""
            ref = (record.alarm_date + timedelta(hours=8)).date()  # 北京时间日期
            week_start, week_end = get_natural_week_range(ref)
            week_start_utc = datetime.combine(week_start, time.min, tzinfo=UTC) - timedelta(hours=8)
            week_end_utc = datetime.combine(week_end + timedelta(days=1), time.min, tzinfo=UTC) - timedelta(hours=8)
            last_start_utc = week_start_utc - timedelta(days=7)
            last_end_utc = week_start_utc

            conds = [
                CentralAlarmRecord.is_deleted == False,  # noqa: E712
                CentralAlarmRecord.workshop == record.workshop,
                CentralAlarmRecord.post == record.post,
                CentralAlarmRecord.alarm_date.is_not(None),
            ]
            week_count = (
                await self.session.scalar(
                    select(func.count(CentralAlarmRecord.id)).where(
                        *conds,
                        CentralAlarmRecord.alarm_date >= week_start_utc,
                        CentralAlarmRecord.alarm_date < week_end_utc,
                    )
                )
            ) or 0
            # 目标记录自身计入本周计数 → 排除自身（单条时 week_count=0）
            week_count = max(0, week_count - 1)
            last_count = (
                await self.session.scalar(
                    select(func.count(CentralAlarmRecord.id)).where(
                        *conds,
                        CentralAlarmRecord.alarm_date >= last_start_utc,
                        CentralAlarmRecord.alarm_date < last_end_utc,
                    )
                )
            ) or 0
            recent = list(
                (
                    await self.session.scalars(
                        select(CentralAlarmRecord)
                        .where(*conds)
                        .order_by(CentralAlarmRecord.alarm_date.desc())
                        .limit(5)
                    )
                ).all()
            )
            recent_brief = [
                f"{_bj(r.alarm_date)} {r.post or '?'}: {(r.alarm_description or '')[:60]}"
                for r in recent
            ]
            payload = {
                "workshop": record.workshop,
                "post": record.post,
                "本周同岗位报警数(不含本条)": week_count,
                "上一完整自然周报警数": last_count,
                "最近报警": recent_brief,
            }
            return json.dumps(payload, ensure_ascii=False)
        except Exception:
            logger.warning("中控报警历史上下文查询失败 record_id=%s", record.id)
            return ""

    async def analyze_per_records(
        self, records: list[CentralAlarmRecord], *, channel: str = "system",
    ) -> dict[str, dict[str, str]]:
        """逐条 AI 分析并回写记录（历史上下文 + Semaphore 限流）。

        Returns:
            {"<record_id>": {alarm_type, equipment, pattern, dimension,
                              reason_analysis, rectification_direction}}
            失败的记录不包含在返回中。

        回写只 setattr 内存对象（ai_dimension/ai_pattern 已归一化为英文枚举）；
        flush + commit 由调用方 service 统一处理（UPDATE 后 re-fetch 铁律）。
        """
        targets = [
            r for r in records[:MAX_RECORDS_TO_ANALYZE]
            if getattr(r, "ai_analyzed_at", None) is None
        ]
        by_id = {str(r.id): r for r in targets}
        sem = asyncio.Semaphore(MAX_CONCURRENCY)

        async def _analyze_one(r: CentralAlarmRecord) -> tuple[str, dict[str, str]] | None:
            try:
                history = await self._load_history_context(r)
                ai = await self._get_ai()
                messages = build_per_record_messages(r, history)
                with ai_audit_scope(
                    scenario="central_alarm_analysis",
                    resource_type="central_alarm_record",
                    resource_id=r.id,
                    channel=channel,
                ):
                    result = await ai.chat_parsed(
                        messages=messages,
                        expected_keys=EXPECTED_KEYS_PER_RECORD,
                        temperature=0.3,
                    )
                return str(r.id), {
                    "alarm_type": result.get("alarm_type", ""),
                    "equipment": result.get("equipment", ""),
                    "pattern": result.get("pattern", ""),
                    "dimension": result.get("dimension", ""),
                    "reason_analysis": result.get("reason_analysis", ""),
                    "rectification_direction": result.get("rectification_direction", ""),
                }
            except Exception:
                logger.warning("单条 AI 分析失败 record_id=%s", r.id)
                return None

        async def _with_sem(r: CentralAlarmRecord) -> tuple[str, dict[str, str]] | None:
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
            r.ai_alarm_type = analysis.get("alarm_type") or None
            r.ai_equipment = analysis.get("equipment") or None
            r.ai_pattern = _normalize_pattern(analysis.get("pattern", ""))
            r.ai_dimension = _normalize_dimension(analysis.get("dimension", ""))
            r.ai_reason_analysis = analysis.get("reason_analysis", "")
            r.ai_rectification_direction = analysis.get("rectification_direction", "")
            r.ai_analyzed_at = now
        return out

    async def analyze_daily_summary(
        self, agg: CentralAlarmDailyAgg, per_summaries: list[str], *,
        channel: str = "system",
    ) -> dict[str, Any] | None:
        """日报汇总 AI 分析；失败返回 None（renderer 省略 AI 块）。"""
        try:
            ai = await self._get_ai()
            messages = build_daily_summary_messages(agg, per_summaries)
            with ai_audit_scope(
                scenario="central_alarm_analysis",
                resource_type="central_alarm_daily_report",
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


def _normalize_pattern(raw: str) -> str | None:
    """AI 返回的 pattern 中文/英文 → 英文枚举。

    normal_transient(正常瞬报) / repeated(重复报警) / false_alarm(误报) / anomalous(异常依赖)。
    未识别归 anomalous（保守偏高）；空值返回 None。
    """
    mapping = {
        "正常瞬报": "normal_transient", "normal_transient": "normal_transient",
        "重复报警": "repeated", "repeated": "repeated",
        "误报": "false_alarm", "false_alarm": "false_alarm",
        "异常依赖": "anomalous", "anomalous": "anomalous",
    }
    v = mapping.get(raw.strip()) if raw else None
    return v or ("anomalous" if raw else None)


def _normalize_dimension(raw: str) -> str | None:
    """AI 返回的维度中文 → 英文枚举（process/operation/equipment/other）。"""
    mapping = {
        "工艺": "process", "操作": "operation", "设备": "equipment", "其他": "other",
    }
    return mapping.get(raw.strip()) or ("other" if raw else None)


def _bj(dt: datetime | None) -> str:
    """UTC → 北京时间字符串。"""
    if dt is None:
        return "?"
    return (dt + timedelta(hours=8)).strftime("%m/%d %H:%M")
