"""法规收录对账兜底巡检（推送为主 + 拉取对账兜底）。

拉取 ragplus 契约③近期 runs，与本仓收录留痕按 run_id 比对：漏推的
run 若带候选明细（items 数组，防御式读取——契约 v1 未逐项冻结），构造
契约①同构请求重走完整处理链（幂等天然防重）；无明细的 run 记入
missing_no_items 留痕告警，等 ragplus 重推或人工介入。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import RegulationIngestRun
from app.modules.safety.regulation_ingest.ragplus_crawler_client import (
    get_ragplus_crawler_client,
)
from app.modules.safety.regulation_ingest.schemas import IngestCandidatesRequest
from app.modules.safety.regulation_ingest.service import RegulationIngestService

logger = logging.getLogger(__name__)

# 巡检只回看近 N 天的 ragplus runs（太老的漏推无补处理价值）
_PATROL_WINDOW_RUNS = 30


async def run_reconcile_patrol(session: AsyncSession) -> dict[str, Any]:
    """对账巡检主入口（scheduler 每日调度；ragplus 不可达直接抛错留痕）。"""
    client = get_ragplus_crawler_client()
    status = await client.get_crawler_status()  # 不可达=任务失败，交 guarded 留痕
    rag_runs = status.get("runs") or []

    stmt = select(RegulationIngestRun.source_run_id).where(
        RegulationIngestRun.is_deleted.is_(False),
        RegulationIngestRun.status == "completed",
    )
    known_run_ids = {str(r) for r in (await session.execute(stmt)).scalars()}

    recovered: list[str] = []
    missing_no_items: list[str] = []

    for run in rag_runs:
        run_id = str(run.get("run_id") or "")
        if not run_id:
            continue
        if run_id in known_run_ids:
            continue  # 已收：推送链已完成，幂等不再动
        items = run.get("items") or run.get("candidates") or []
        if not isinstance(items, list) or not items:
            missing_no_items.append(run_id)
            continue
        # 契约①同构请求重走完整处理链（预去重/判定/写入/回执/推送/留痕）
        service = RegulationIngestService(session)
        try:
            await service.ingest_candidates(
                IngestCandidatesRequest(run_id=run_id, items=items),
                source="reconcile",
            )
            recovered.append(run_id)
        except Exception:
            logger.exception("对账补处理失败: run_id=%s", run_id)
            missing_no_items.append(run_id)

    result = {
        "checked_runs": len(rag_runs),
        "recovered_runs": recovered,
        "missing_no_items": missing_no_items,
    }
    if recovered or missing_no_items:
        logger.info("法规收录对账巡检: %s", result)
    return result
