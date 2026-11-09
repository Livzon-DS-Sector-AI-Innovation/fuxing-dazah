"""P2-1 —— 例外复核写回执行器（服务层单接缝 ``execute_writeback``）。

设计（docs/DESIGN-隐患AI识别-优化提升总结设计-20261105.md §4.3-B auto + §4.4）：
observe 期复核报告升格为可执行写回。铁律与既有护栏全数复用：

- **写目标=AI 六列白名单**（``field_authority`` 的 ``exception_reviewer``
  写链，恰六列；人工列混入立即 ``FieldAuthorityError``，不发起写入）；
- **P0 同款输出闸门**：判定依据非空非占位且引用可在报告证据中验证
  （复用 ``judge_rescued`` 同源口径），不过则 ``gate_blocked`` 零写；
- **CAS 写前回读**（P1-2 语义）：AI 列现值 ≠ 复核时快照（``ai_snapshot``）
  → ``cas_conflict`` 零 PUT；回读异常 fail-open（与 ``cas_guard`` 一致）；
- **成功 → ``record_success`` 清死信 + 报告 ``writeback=success`` 回写
  Redis + ai_audit 审计行**；瞬时失败重试一次仍失败 → ``writeback=failed``
  （死信不清，下轮复核自然重走=回 observe 池）。

依赖全注入（reader/writer/redis），测试零真实 Bitable/Redis/DB。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.modules.safety.ai_hazard_identification.citation_evidence import (
    CitationEvidence,
    EvidenceEntry,
)
from app.modules.safety.service.bitable_direct import writer as bd_writer
from app.modules.safety.service.hazard_direct import field_authority as fa
from app.modules.safety.service.hazard_direct.exception_reviewer import (
    AI_SNAPSHOT_FIELDS,
    REVIEWER_SCENARIO,
    ExceptionReviewReport,
    ProposedAction,
    RecordReader,
    judge_rescued,
    load_report,
    save_report,
)
from app.modules.safety.service.hazard_direct.failure_ledger import RedisLike

logger = logging.getLogger(__name__)

__all__ = [
    "WritebackDeps",
    "WritebackOutcome",
    "execute_writeback",
    "execute_writeback_for_record",
    "auto_writeback_pass",
    "build_writeback_fields",
    "classify_writeback_action",
]

# Bitable select 列 field_type（与 bitable_repo._SELECT_FIELD_TYPE 同值；单选=3）
_SELECT_FIELD_TYPE = 3

# 写回状态机（报告 writeback 字段合法值）
WB_NOT_ATTEMPTED = "not_attempted"
WB_PENDING_CONFIRM = "pending_confirm"
WB_SUCCESS = "success"
WB_FAILED = "failed"
WB_CAS_CONFLICT = "cas_conflict"
WB_GATE_BLOCKED = "gate_blocked"

# CAS 比对口径：列名单一事实源=AI_SNAPSHOT_FIELDS；select（单/多选）三列
# 与 field_authority 枚举列一致，其余按文本比对
_CAS_SELECT_KINDS = frozenset(
    {"隐患级别（AI）", "隐患分类（AI）", "隐患类别（AI）"}
)


def _cas_targets() -> dict[str, str]:
    return {
        name: ("select" if name in _CAS_SELECT_KINDS else "text")
        for name in AI_SNAPSHOT_FIELDS
    }


@dataclass
class WritebackDeps:
    """写回依赖（全注入；测试全 fake）。"""

    reader: RecordReader
    writer: Any  # BitableRecordWriter 协议（update_record(record_id, fields)）
    redis: RedisLike | None = None


@dataclass
class WritebackOutcome:
    """一次写回的结果（报告状态同步回写 Redis）。"""

    status: str  # success/failed/cas_conflict/gate_blocked
    written_fields: list[str] = field(default_factory=list)
    note: str = ""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _evidence_from_report(report: ExceptionReviewReport) -> CitationEvidence:
    """报告 evidence 快照 → CitationEvidence（引用可验证性闸门输入）。"""
    return CitationEvidence(
        entries=tuple(
            EvidenceEntry(
                doc_name=e.doc_name,
                source_article=e.source_article,
                chunk_text=e.quote,
                chunk_id=e.chunk_id,
            )
            for e in report.evidence
        )
    )


def build_writeback_fields(report: ExceptionReviewReport) -> dict[str, Any]:
    """报告结论 → AI 六列写负载（只写非空字段；EN→CN 枚举反转 + select 整形）。

    复核结论当前产出 级别/分类/依据/建议 四语义（描述/类别复核员不产，
    留白不写）；白名单仍为六列——后续扩结论不改写链。
    """
    from app.modules.safety.service.hazard_direct.field_authority import (
        HAZARD_LEVEL_REVERSE,
        HAZARD_TYPE_REVERSE,
    )

    fields: dict[str, Any] = {}
    conclusion = report.ai_conclusion
    if conclusion.hazard_level:
        fields["隐患级别（AI）"] = bd_writer.format_write_value(
            _SELECT_FIELD_TYPE,
            HAZARD_LEVEL_REVERSE.get(
                conclusion.hazard_level, conclusion.hazard_level
            ),
        )
    if conclusion.classification:
        fields["隐患分类（AI）"] = bd_writer.format_write_value(
            _SELECT_FIELD_TYPE,
            HAZARD_TYPE_REVERSE.get(
                conclusion.classification, conclusion.classification
            ),
        )
    if conclusion.major_hazard_basis:
        fields["隐患判定依据（AI）"] = conclusion.major_hazard_basis
    if conclusion.rectification_suggestion:
        fields["整改建议（AI）"] = conclusion.rectification_suggestion
    return fields


def _cas_conflicts(
    report: ExceptionReviewReport, current_fields: dict[str, Any]
) -> list[str]:
    """CAS 纯比对：报告快照 vs 写前回读（P1-2 ``cas_field_conflicts`` 同语义）。"""
    from app.modules.safety.service.hazard_direct.bitable_repo import (
        cas_field_conflicts,
    )

    return cas_field_conflicts(
        report.ai_snapshot,
        current_fields,
        _cas_targets(),
    )


async def _write_writeback_audit(
    report: ExceptionReviewReport, outcome: WritebackOutcome
) -> None:
    """写回留痕（ai_call_audits 一行 + P2-2 Thread 留痕；失败不影响写回结果）。

    Thread 留痕（writeback_trace）：全部终态路径都过本漏斗，一处挂载；
    gate_blocked=判据性拦截零写入，不留 Thread 行。
    """
    try:
        from app.modules.safety.ai_audit.audited_client import write_audit_record

        await write_audit_record(
            model="reviewer",
            scenario=REVIEWER_SCENARIO,
            input_text=f"exception writeback record={report.record_id}",
            output_text=report.model_dump_json(),
            status="success" if outcome.status == WB_SUCCESS else "skipped",
            channel_override="system",
            extra={
                "bitable_record_id": report.record_id,
                "writeback": outcome.status,
                "written_fields": ",".join(outcome.written_fields),
                "note": outcome.note,
            },
        )
    except Exception:  # noqa: BLE001
        logger.warning("写回审计写入失败", exc_info=True)
    try:
        if outcome.status in (WB_SUCCESS, WB_FAILED, WB_CAS_CONFLICT):
            from app.modules.safety.service.hazard_direct import writeback_trace

            await writeback_trace.record_writeback(
                writer=writeback_trace.WRITER_EXCEPTION_REVIEW,
                record_id=report.record_id,
                fields=outcome.written_fields or sorted(build_writeback_fields(report)),
                applied=outcome.status == WB_SUCCESS,
                note=outcome.note,
            )
    except Exception:  # noqa: BLE001 — Thread 留痕失败不影响写回结果
        logger.warning("写回 Thread 留痕失败", exc_info=True)


def _finalize(
    report: ExceptionReviewReport,
    status: str,
    *,
    note: str = "",
    written_fields: list[str] | None = None,
) -> WritebackOutcome:
    report.writeback = status
    report.writeback_at = _now_utc()
    report.writeback_note = note
    return WritebackOutcome(
        status=status, written_fields=written_fields or [], note=note
    )


async def execute_writeback(
    report: ExceptionReviewReport, *, deps: WritebackDeps
) -> WritebackOutcome:
    """复核报告 → 写回 AI 六列（P0 闸门 → 白名单 → CAS → 串行写 → 清死信）。

    就地更新报告的 ``writeback/writeback_at/writeback_note`` 并回写 Redis；
    结果同步 ai_audit。任何拦截路径零 Bitable 写调用。
    """
    # ① P0 同款闸门：依据非空非占位 + 引用可在报告证据中验证（judge_rescued 同源）
    basis = report.ai_conclusion.major_hazard_basis or ""
    evidence = _evidence_from_report(report)
    if not judge_rescued(basis, evidence=evidence):
        outcome = _finalize(report, WB_GATE_BLOCKED, note="占位或引用不可验证")
        await save_report(report, deps.redis)
        await _write_writeback_audit(report, outcome)
        return outcome

    fields = build_writeback_fields(report)
    if not fields:
        outcome = _finalize(report, WB_GATE_BLOCKED, note="无可写字段")
        await save_report(report, deps.redis)
        await _write_writeback_audit(report, outcome)
        return outcome

    # ② 写白名单钉子：exception_reviewer 恰 AI 六列（人工列混入即抛，零写入）
    fa.assert_write_allowed(fa.WRITER_EXCEPTION_REVIEW, fields.keys())

    # ③ CAS 写前回读：AI 列现值 ≠ 复核时快照 → 冲突放弃（零 PUT）；
    #    回读异常/记录缺失 fail-open（与 cas_guard 口径一致）；旧报告无快照跳过。
    if report.ai_snapshot:
        current: dict[str, Any] | None = None
        try:
            current = await deps.reader.get_fields(report.record_id)
        except Exception:  # noqa: BLE001 — 读故障不阻断写链（fail-open）
            logger.warning(
                "写回 CAS 回读异常，放行写入（fail-open）: record_id=%s",
                report.record_id,
                exc_info=True,
            )
        if current is not None:
            changed = _cas_conflicts(report, current)
            if changed:
                outcome = _finalize(
                    report,
                    WB_CAS_CONFLICT,
                    note=f"目标列已被并发修改: {','.join(changed)}",
                )
                await save_report(report, deps.redis)
                await _write_writeback_audit(report, outcome)
                return outcome

    # ④ 串行写（既有 write_serial 语义）+ 瞬时失败重试一次（P2-1 拍板 Q10A）
    written = False
    for _attempt in range(2):
        result = await bd_writer.write_serial(
            deps.writer,
            [bd_writer.RecordUpdate(record_id=report.record_id, fields=fields)],
            interval_seconds=0.0,
        )
        if result.written > 0:
            written = True
            break
        logger.warning(
            "写回尝试失败（%s/2）: record_id=%s failed=%s",
            _attempt + 1, report.record_id, result.failed,
        )

    if not written:
        outcome = _finalize(report, WB_FAILED, note="写入重试一次仍失败")
        await save_report(report, deps.redis)  # 死信不清：下轮复核重走
        await _write_writeback_audit(report, outcome)
        return outcome

    # ⑤ 成功：清死信（离开例外池与重试队列）+ 报告状态回写
    from app.modules.safety.service.hazard_direct.failure_ledger import (
        record_success,
    )

    await record_success(report.record_id, redis=deps.redis)
    outcome = _finalize(
        report,
        WB_SUCCESS,
        written_fields=sorted(fields),
        note="已写回 AI 列并清除死信",
    )
    await save_report(report, deps.redis)
    await _write_writeback_audit(report, outcome)
    return outcome


def build_default_writeback_deps() -> WritebackDeps:
    """默认写回依赖（真实链路）；测试注入 fake 替换。"""
    from app.modules.safety.feishu.bitable_client import SafetyBitableClient
    from app.modules.safety.service.hazard_direct.exception_reviewer import (
        BitableRecordReader,
        review_redis_client,
    )

    return WritebackDeps(
        reader=BitableRecordReader(),
        writer=SafetyBitableClient(),
        redis=review_redis_client(),
    )


async def execute_writeback_for_record(
    record_id: str, *, redis: RedisLike | None = None
) -> dict[str, Any]:
    """按 record_id 装载最新复核报告并执行写回（BA 确认流/人工点名入口）。

    报告缺失 → 显式 error 返回（不抛）；执行期过 ``execute_writeback`` 全套
    闸门（gate/白名单/CAS），任何拦截零写。
    """
    if redis is None:
        from app.modules.safety.service.hazard_direct.exception_reviewer import (
            review_redis_client,
        )

        redis = review_redis_client()
    report = await load_report(record_id, redis)
    if report is None:
        return {"error": f"未找到复核报告: {record_id}", "record_id": record_id}
    deps = build_default_writeback_deps()
    outcome = await execute_writeback(report, deps=deps)
    return {
        "record_id": record_id,
        "status": outcome.status,
        "written_fields": outcome.written_fields,
        "note": outcome.note,
    }


# ═══════════════════════════════════════════════════════════════════════════
# auto 分级处置（F2；Q2C 拍板 2026-11-09）
# ═══════════════════════════════════════════════════════════════════════════

# 分级动作（纯函数判定；auto 期免确认仅限 direct）
WB_ACTION_DIRECT = "direct"  # adopt_ai + effective_rescued + level∈{general,serious}
WB_ACTION_CONFIRM = "confirm"  # escalate 或 adopt_ai+major → 强制人工确认
WB_ACTION_SKIP = "skip"  # 其余（keep_manual/insufficient/未 rescued/人工否决）


def classify_writeback_action(report: ExceptionReviewReport) -> str:
    """auto 分级判定（纯函数）。

    - direct：采纳 AI 且 rescued 有效口径（人工改判优先）且级别 general/serious
      ——§4.4 写前人工确认仅针对重大隐患（major），serious 同 general 直写；
    - confirm：escalate（复核员主动提请专审）或 adopt_ai 且 major；
    - skip：其余。
    """
    if report.proposed_action == ProposedAction.ESCALATE:
        return WB_ACTION_CONFIRM
    if report.proposed_action != ProposedAction.ADOPT_AI:
        return WB_ACTION_SKIP
    if report.ai_conclusion.hazard_level == "major":
        return WB_ACTION_CONFIRM
    if not report.effective_rescued:
        return WB_ACTION_SKIP
    return WB_ACTION_DIRECT


async def auto_writeback_pass(
    reports: list[ExceptionReviewReport],
    *,
    reader: Any,
    writer: Any | None,
    redis: RedisLike | None,
) -> dict[str, int]:
    """auto 批分级处置：direct 直写 / confirm 标 pending_confirm / skip 不动。

    Returns: {"success", "failed", "pending_confirm", "skipped"} 计数。
    就地更新报告状态并回写 Redis（经 execute_writeback 的 save_report /
    pending_confirm 标记同样落 Redis 供看板与确认流消费）。
    """
    counts = {"success": 0, "failed": 0, "pending_confirm": 0, "skipped": 0}
    if writer is None:
        from app.modules.safety.feishu.bitable_client import SafetyBitableClient

        writer = SafetyBitableClient()
    deps = WritebackDeps(reader=reader, writer=writer, redis=redis)
    for report in reports:
        action = classify_writeback_action(report)
        if action == WB_ACTION_SKIP:
            counts["skipped"] += 1
            continue
        if action == WB_ACTION_CONFIRM:
            report.writeback = WB_PENDING_CONFIRM
            report.writeback_at = _now_utc()
            report.writeback_note = "major/escalate 需人工确认（会话点名复核后执行写回）"
            await save_report(report, redis)
            counts["pending_confirm"] += 1
            continue
        outcome = await execute_writeback(report, deps=deps)
        if outcome.status == WB_SUCCESS:
            counts["success"] += 1
        elif outcome.status == WB_FAILED:
            counts["failed"] += 1
        else:
            # gate_blocked / cas_conflict 不进 success/failed——分别留痕，
            # 归入 skipped（未形成写回；报告状态已由 execute_writeback 标注）
            counts["skipped"] += 1
    return counts
