"""GuardianScorePollSource —— R2 成绩表轮询源（kind=guardian_score_poll）。

复用平台 bitable_poll 的水位/指纹幂等（首见 rebase 零回溯——353 条存量
不回放，名单现状已人工维护正确），子类只做翻译层增强：成绩 fields →
``payload._derived`` 结构化（parse_score_record），规则零文本操作符。

fetcher（guardian_score_ledger）在 superagent_bridge 注册：拉理论考试
分数表全量（automatic_fields 取 last_modified_time）+ 客户端水位过滤。
"""

from __future__ import annotations

import logging
from typing import Any

from app.modules.safety.service.guardian_r2.score_parse import parse_score_record
from app.platform.superagent.bitable_poll import BitablePollSource

logger = logging.getLogger(__name__)


async def guardian_score_fetcher(watermark_ms: int) -> list[dict[str, Any]]:
    """拉理论考试分数表（水位过滤；模式照 hazard_ledger_fetcher）。"""
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    client = bd_reader.resolve_client("guardian_score", "score")
    records = await bd_reader.fetch_all_records(client, automatic_fields=True)
    out: list[dict[str, Any]] = []
    for rec in records or []:
        lms = rec.get("last_modified_time")
        if lms is not None and int(lms) >= watermark_ms:
            out.append(rec)
        elif lms is None:
            # 无修改时间戳的记录：保守放行（指纹幂等兜底，不会重复派生）
            out.append(rec)
    return out


class GuardianScorePollSource(BitablePollSource):
    """bitable_poll 子类：成绩翻译进 _derived（人员/类型路由/合格/考核日期）。"""

    kind = "guardian_score_poll"

    async def poll(
        self,
        session: Any,
        source_row: Any,
        cursors: dict[str, Any],
    ):
        result = await super().poll(session, source_row, cursors)
        for draft in result.drafts or []:
            facts = parse_score_record(draft.payload.get("fields") or {})
            draft.payload["_derived"] = {
                "person_name": facts.person_name,
                "open_id": facts.open_id,
                "department": facts.department,
                "cert_category": facts.cert_category,  # guardian_a/b 路由
                "passed": facts.passed,                # 合格/不合格/None（缺考）
                "exam_date": facts.exam_date.isoformat() if facts.exam_date else None,
                "score_value": facts.score_value,
            }
        return result
