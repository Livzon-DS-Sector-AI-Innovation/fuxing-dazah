"""FireAlarmAnalyst 逐条分析 — 增量（跳过已分析）单测。

不依赖数据库 / AI 服务：ai_service 用 MagicMock + patch RAG 检索器
（副作用抛异常→被 analyze_per_records 的 except pass 吞掉）。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.safety.service.fire_alarm.analyst import FireAlarmAnalyst


def make_record(rid: str = "r1", analyzed: datetime | None = None) -> MagicMock:
    r = MagicMock()
    r.id = rid
    r.alarm_type = "火灾报警"
    r.cause_category = "设备"
    r.cause_description = "传感器老化误触发"
    r.ai_dimension = None
    r.ai_reason_analysis = None
    r.ai_rectification_direction = None
    r.ai_analyzed_at = analyzed
    return r


class TestAnalyzePerRecordsIncremental:
    def test_skips_already_analyzed_records(self):
        analyzed = datetime(2026, 8, 28, 1, 0, tzinfo=UTC)
        r1 = make_record("r1", analyzed=analyzed)
        r2 = make_record("r2", analyzed=None)
        ai = MagicMock()
        ai.chat_parsed = AsyncMock(return_value={
            "dimension": "工艺",
            "reason_analysis": "原因",
            "rectification_direction": "建议",
        })
        analyst = FireAlarmAnalyst(session=None, ai_service=ai)

        with patch(
            "app.modules.safety.knowledge.retriever.SafetyKnowledgeRetriever",
            side_effect=Exception("no-db"),  # RAG 检索失败降级，不阻塞分析
        ):
            results = asyncio.run(analyst.analyze_per_records([r1, r2], channel="test"))

        # 只分析未回写的 r2；r1 保持原值不重写
        assert list(results.keys()) == ["r2"]
        assert ai.chat_parsed.await_count == 1
        assert r2.ai_dimension == "process"
        assert r2.ai_reason_analysis == "原因"
        assert r2.ai_rectification_direction == "建议"
        assert r2.ai_analyzed_at is not None
        assert r1.ai_analyzed_at == analyzed
        assert r1.ai_dimension is None
