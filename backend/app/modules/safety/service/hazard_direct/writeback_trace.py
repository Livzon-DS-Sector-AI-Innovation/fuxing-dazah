"""①②⑤/P2-1 写回 Thread 留痕 —— 写回动作旁挂落底座（P2-2 G1/G2）。

设计（docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §4.5，2026-11-09 拍板）：
记录级 Thread 而非域 Agent——①②③⑤每次写回同一 Thread 的 Trigger 留痕，
按 ``thread_key=bitable:hazard:<record_id>`` 聚合出「AI 对这条记录做过什么」的
统一审计面。形态与 ``audit_trail.py``（③卡片留痕）同构：

- 动作已同步完成 → 只写 Trigger（payload 记 writer/写回列/结果），不写 Effect
  （Effect 无事可做，且 ``agent_effects`` 无 thread_key 列、底座 poller 关时
  会永久 pending 积压）；
- 每次写回是独立事件：external_id=``writeback:{writer}:{record_id}:{utc_ms}``
  （幂等入库由 ingest_draft 的 (source_id, external_id) 唯一约束兜底）；
- disposition 记 applied/failed 终态；判据性跳过（无字段可写/gate_blocked）
  不留痕（非写事件）；
- 自管短会话（可注入 session 供测试）；try/except 吞异常只记日志——留痕
  失败绝不拖垮业务写回。

开关 ``SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED``（app_config，默认关，管 G1/G2
写回留痕与 G3 收编留痕）；关=零 DB 写零行为变化。source 行
（safety.hazard.writeback_trace）首见 ensure，不参与 poll（enabled 恒 false，
仅作归属载体）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import TriggerDraft, make_disposition_step

logger = logging.getLogger(__name__)

TRACE_SOURCE_NAME = "safety.hazard.writeback_trace"
TRACE_SOURCE_KIND = "safety_writeback_trace"
THREAD_PREFIX = "bitable:hazard"

# 写链标识（payload.writer 合法值；①=识别主链 / P2-1=例外复核 / ②=初审 / ⑤=评分 / P3-1=stale 重算）
WRITER_AI_ANALYSIS = "ai_analysis"
WRITER_EXCEPTION_REVIEW = "exception_review"
WRITER_REVIEW = "review"
WRITER_SCORING = "scoring"
WRITER_AI_RERUN = "ai_rerun"
# P3-3 G2：③督办催办卡发送（非 Bitable 写回，卡动作同 Thread 留痕）——
# 与 audit_query 既有 kind="dunning" 词汇对齐；区别于 field_authority 的
# supervision（督办等级列写者）。
WRITER_DUNNING = "dunning"
# P3-3 G1 预埋：②-b 已关闭自动通过 / ②-c 已关闭跟随改写（规则性写回）。
# 调用点在 review.py 的 WIP ②-b/②-c 段（落库后经 write_review(writer=…)
# 传入，两行补丁见设计文档附录 B）；落库前二者经默认值留 writer="review"
# 行（有行、缺区分——比「无审计行」安全）。
WRITER_AI_AUTOPASS = "ai_autopass"
WRITER_AI_REWRITE = "ai_rewrite"


def trace_enabled() -> bool:
    from app.modules.safety.app_config.store import store

    return store.get_bool("SAFETY_HAZARD_WRITEBACK_TRACE_ENABLED", False)


async def _ensure_source_row(session: Any) -> AgentSource:
    """取/建留痕源行（幂等；enabled 恒 false 不参与 poll，仅归属载体）。"""
    row: AgentSource | None = (
        await session.execute(
            select(AgentSource).where(AgentSource.name == TRACE_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    if row is None:
        row = AgentSource(
            kind=TRACE_SOURCE_KIND, name=TRACE_SOURCE_NAME, config={}, enabled=False,
        )
        session.add(row)
        await session.flush()
    return row


def _field_names(fields: list[str] | dict[str, Any]) -> list[str]:
    """写回列清单（dict 取键名；排序稳定便于断言与对比）。"""
    names = list(fields.keys()) if isinstance(fields, dict) else list(fields)
    return sorted(names)


async def record_writeback(
    *,
    writer: str,
    record_id: str,
    fields: list[str] | dict[str, Any],
    applied: bool,
    note: str = "",
    hazard_no: str = "",
    session: Any | None = None,
) -> bool:
    """一次 Bitable 写回动作落 Trigger（失败绝不抛，返回是否新落一行）。

    Args:
        writer: 写链标识（WRITER_* 常量）。
        fields: 实际写回列（列名清单或 写回dict）。
        applied: 写回是否成功（False → disposition 记 failed）。
        session: 复用会话（缺省自建短会话；测试可注入）。
    """
    if not trace_enabled() or not record_id:
        return False
    if session is not None:
        # 复用会话：事务边界归调用方（ingest 约定，不 commit）
        return await _record(session, writer, record_id, fields, applied, note, hazard_no)
    try:
        from app.core.database import async_session_factory

        # 自管短会话：留痕即持久化——必须显式 commit（async with 退出不提交，
        # ingest_draft 只 flush；漏 commit = 生产留痕静默丢失）
        async with async_session_factory() as own:
            ok = await _record(own, writer, record_id, fields, applied, note, hazard_no)
            await own.commit()
            return ok
    except Exception:  # noqa: BLE001 — 留痕失败不影响业务链路
        logger.exception(
            "写回留痕失败（不影响业务链路）: writer=%s record=%s", writer, record_id
        )
        return False


async def _record(
    session: Any,
    writer: str,
    record_id: str,
    fields: list[str] | dict[str, Any],
    applied: bool,
    note: str,
    hazard_no: str,
) -> bool:
    try:
        from app.platform.superagent.ingest import ingest_draft

        source_row = await _ensure_source_row(session)
        draft = TriggerDraft(
            external_id=f"writeback:{writer}:{record_id}:{uuid4().hex[:12]}",
            thread_key=f"{THREAD_PREFIX}:{record_id}",
            actor={"id": writer, "type": "ai_pipeline"},
            human=False,
            addressed=False,
            payload={
                "record_id": record_id,
                "hazard_no": hazard_no,
                "writer": writer,
                "fields": _field_names(fields),
                "note": (note or "")[:200],
                "at": datetime.now(UTC).isoformat(),
                "channel": {"kind": "bitable", "record_id": record_id},
            },
        )
        outcome, trigger = await ingest_draft(session, source_row, draft)
        if outcome != "stored":
            return False
        trigger.disposition = [
            *list(trigger.disposition or []),
            make_disposition_step(
                "applied" if applied else "failed",
                reason=(note or "")[:200],
            ),
        ]
        return True
    except Exception:  # noqa: BLE001
        logger.exception(
            "写回留痕失败（不影响业务链路）: writer=%s record=%s", writer, record_id
        )
        return False
