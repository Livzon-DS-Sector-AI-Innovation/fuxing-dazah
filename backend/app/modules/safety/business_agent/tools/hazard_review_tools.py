"""P1-3 例外复核员工具组（hazard_review）——observe 期五工具 + 入口工具。

五工具是 ``hazard_direct.exception_reviewer`` impl 的薄适配（ctx.deps →
默认依赖构建器），全部只读注册（TOOL_KIND=False）：

- hazard_view_images / hazard_search_regulations / hazard_get_record_context /
  hazard_cross_check / hazard_propose_writeback（observe 期=propose_only，
  只产出结构化建议，无任何 Bitable 写路径）；
- review_hazard_exceptions（入口，仅 creator）：捞取死信/人工指定 →
  ``run_exception_review``（多步补检 + 成本护栏）→ 摘要返回聊天。

observe 铁律在本组两处强制：propose 工具显式标注 observe_only/writeback=
disabled；入口工具返回体携带 observe=no_writeback。
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import BinaryContent, RunContext

from app.modules.safety.business_agent.schemas import SafetyDeps
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    BitableRecordReader as _BitableRecordReader,
)
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    RetrieverSearcher as _RetrieverSearcher,
)
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    build_default_review_deps as _build_default_review_deps,
)
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    build_proposal,
    cross_check_conclusion,
    data_uri_to_binary,
    fetch_record_context,
    pick_exceptions,
    run_exception_review,
    search_regulation_chunks,
)

logger = logging.getLogger(__name__)

__all__ = [
    "hazard_view_images",
    "hazard_search_regulations",
    "hazard_get_record_context",
    "hazard_cross_check",
    "hazard_propose_writeback",
    "review_hazard_exceptions",
]


# ── 五工具（薄适配）────────────────────────────────────────────────────────


async def hazard_view_images(
    ctx: RunContext[SafetyDeps], record_id: str
) -> list[BinaryContent]:
    """查看隐患记录的缺陷图片（多模态直传，observe 复核用）。

    Args:
        record_id: 隐患登记表记录 ID
    """
    reader = _BitableRecordReader()
    uris = await reader.defect_images(record_id)
    binaries: list[BinaryContent] = []
    for uri in uris[:4]:
        parsed = data_uri_to_binary(uri)
        if parsed is not None:
            binaries.append(BinaryContent(parsed[0], media_type=parsed[1]))
    return binaries


async def hazard_search_regulations(
    ctx: RunContext[SafetyDeps], query: str
) -> list[dict[str, Any]]:
    """检索安全法规知识库条款（复核员的候选证据来源，不联网）。

    Args:
        query: 检索词（建议「设备/物质/行为/场所 + 标准关键词」）
    """
    return await search_regulation_chunks(_RetrieverSearcher(ctx.deps.db), query)


async def hazard_get_record_context(
    ctx: RunContext[SafetyDeps], record_id: str
) -> dict[str, Any]:
    """读取隐患记录上下文：人工列/AI列当前值 + 失败账本状态（只读）。

    Args:
        record_id: 隐患登记表记录 ID
    """
    context = await fetch_record_context(
        reader=_BitableRecordReader(), redis=None, record_id=record_id
    )
    if context is None:
        return {"error": f"记录不存在: {record_id}", "record_id": record_id}
    return context


async def hazard_cross_check(
    ctx: RunContext[SafetyDeps],
    record_id: str,
    ai_conclusion: dict[str, Any],
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """交叉核对：AI 结论 vs 人工结论逐字段 diff + 引用可验证性。

    Args:
        record_id: 隐患登记表记录 ID
        ai_conclusion: AI 新结论（hazard_level/hazard_type/hazard_category/
            major_hazard_basis 等键）
        evidence: 可选检索证据（source_doc/source_article/chunk_text/chunk_id），
            传入时核验引用可验证性
    """
    context = await fetch_record_context(
        reader=_BitableRecordReader(), redis=None, record_id=record_id
    )
    if context is None:
        return {"error": f"记录不存在: {record_id}", "record_id": record_id}
    return cross_check_conclusion(
        ai_conclusion=ai_conclusion or {},
        manual_conclusion=context.get("manual_conclusion") or {},
        evidence_entries=evidence,
        ai_basis=str((ai_conclusion or {}).get("major_hazard_basis") or ""),
    )


async def hazard_propose_writeback(
    ctx: RunContext[SafetyDeps], record_id: str, proposal: dict[str, Any]
) -> dict[str, Any]:
    """结构化复核建议（observe 期 propose_only：只生成建议，绝不写回）。

    Args:
        record_id: 隐患登记表记录 ID
        proposal: 建议内容（hazard_level/hazard_type/hazard_category/
            major_hazard_basis/rectification_suggestion 等）
    """
    return build_proposal(record_id, proposal or {})


# ── 入口工具（仅 creator）──────────────────────────────────────────────────


async def review_hazard_exceptions(
    ctx: RunContext[SafetyDeps],
    limit: int = 10,
    record_ids: list[str] | None = None,
) -> dict[str, Any]:
    """触发例外复核（observe）：捞取死信/人工指定记录，多步补检产出结构化
    复核报告。**observe 期不写回任何表格列**，报告仅作人工复核的候选证据。

    Args:
        limit: 本次复核条数上限（受每日总上限约束，默认 20/日）
        record_ids: 可选，点名复核的记录 ID（抽检已写回的存疑条目）；
            不传则自动捞取死信
    """
    deps = _build_default_review_deps(ctx.deps.db)
    items = await pick_exceptions(
        manual_record_ids=record_ids, limit=limit, redis=deps.redis
    )
    if not items:
        return {
            "observe": "no_writeback",
            "reviewed": 0,
            "skipped": 0,
            "rescued": 0,
            "items": [],
            "message": "当前没有待复核的例外（死信为空且未点名记录）",
        }
    result = await run_exception_review(items, deps=deps)
    # chat 触发：复核报告以 observe 确认卡回发发起会话（web 渠道无会话，
    # 报告经摘要与看板留痕呈现）；发卡失败不影响复核结果返回。
    card_note = "报告见摘要与看板（当前渠道无飞书会话）"
    chat_id = getattr(ctx.deps, "chat_id", None)
    if chat_id:
        try:
            from app.modules.safety.feishu.exception_review_card import (
                send_review_summary_card,
            )

            message_id = await send_review_summary_card(chat_id, result)
            card_note = (
                "复核报告卡已发送到本会话"
                if message_id
                else "复核报告卡发送失败，报告见摘要与看板"
            )
        except Exception:  # noqa: BLE001 — 发卡失败不阻断复核
            logger.exception("例外复核卡片发送失败（不影响复核结果）")
            card_note = "复核报告卡发送失败，报告见摘要与看板"
    return {
        "observe": "no_writeback",
        "reviewed": result.reviewed,
        "skipped": result.skipped,
        "rescued": result.rescued,
        "stopped_reason": result.stopped_reason,
        "card": card_note,
        "items": [r.summary() for r in result.reports],
    }
