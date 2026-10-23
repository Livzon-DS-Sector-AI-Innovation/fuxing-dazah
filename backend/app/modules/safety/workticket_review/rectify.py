"""作业票审核问题整改复查（run_rectify_check）。

《作业票判定规则》2026-10-23 口径：每日 10 点审核昨日作业票，并复查
前一日审核结果中的问题票是否整改。复查 = 按票重拉平台 detail 最新数据 →
parser 归一化 → rule_engine 重判 → 与昨日落库的违规明细按 rule_no 比对：

- 昨日违规的规则今日重判不再出现（通过/不适用）→ 已整改（resolved）；
- 仍出现 → 未整改；今日新出现昨日没有的规则 → 新增问题（按未整改展示）；
- 拉取失败 / raw_json 缺失无法定位流程实例 → uncheckable（黄色提示）。

比对按 rule_no 通用，对规则集无感知——后续新增规则（如安全措施判定）
自动纳入复查，无需改本模块。仅复查一次：不滚动追踪历史未整改票。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import WorkTicketRectifyCheck
from app.modules.safety.workticket_review.client import WorkTicketPlatformClient
from app.modules.safety.workticket_review.parser import (
    WorkTicketParser,
    _resolve_type_key,
)
from app.modules.safety.workticket_review.report_builder import TICKET_TYPE_NAMES
from app.modules.safety.workticket_review.repository import WorkTicketReviewRepository
from app.modules.safety.workticket_review.rule_engine import (
    RULE_NAME_MAP,
    Violation,
    WorkTicketRuleEngine,
)

logger = logging.getLogger(__name__)

STATUS_RECTIFIED = "rectified"
STATUS_UNRECTIFIED = "unrectified"
STATUS_UNCHECKABLE = "uncheckable"

# 数据不足伪违规（service 汇总里的 rule_no=DATA_INSUFFICIENT）不在引擎
# RULE_NAME_MAP 中，比对展示时兜底为中文。
_DATA_INSUFFICIENT_RULE_NO = "DATA_INSUFFICIENT"
_DATA_INSUFFICIENT_RULE_NAME = "数据不足"


def _rule_display_name(rule_no: str) -> str:
    if rule_no == _DATA_INSUFFICIENT_RULE_NO:
        return _DATA_INSUFFICIENT_RULE_NAME
    return RULE_NAME_MAP.get(rule_no, rule_no)

_DETAIL_CONCURRENCY = 5


def _is_flagged(violation: Violation) -> bool:
    """是否计入「问题票」：真实违规或数据不足（不适用行不算问题）。"""
    return not violation.not_applicable


def _is_flagged_row(not_applicable: bool) -> bool:
    return not not_applicable


@dataclass
class RuleResult:
    """单规则比对结论（昨日违规 vs 今日重判）。"""

    rule_no: str
    rule_name: str
    yesterday_detail: str | None  # None = 今日新增问题
    resolved: bool
    today_detail: str | None = None


@dataclass
class TicketCheck:
    """单票复查结论。"""

    ticket_no: str
    ticket_type: str
    status: str  # rectified / unrectified / uncheckable
    rule_results: list[RuleResult] = field(default_factory=list)
    note: str | None = None

    @property
    def ticket_type_name(self) -> str:
        return TICKET_TYPE_NAMES.get(self.ticket_type, self.ticket_type)


def _compare_rules(
    yesterday: dict[str, list[str]],
    today: dict[str, list[str]],
) -> list[RuleResult]:
    """按 rule_no 比对昨日/今日问题集，产出逐规则结论。

    yesterday/today: {rule_no: [detail...]}；today 含真实违规与数据不足。
    昨日规则的今日重判中不再出现 → resolved；仍出现 → 未整改；
    仅今日出现的规则 → 新增问题（yesterday_detail=None, resolved=False）。
    """
    results: list[RuleResult] = []
    for rule_no, details in yesterday.items():
        resolved = rule_no not in today
        results.append(
            RuleResult(
                rule_no=rule_no,
                rule_name=_rule_display_name(rule_no),
                yesterday_detail="；".join(details),
                resolved=resolved,
                today_detail="；".join(today.get(rule_no, [])) or None,
            )
        )
    for rule_no, details in today.items():
        if rule_no in yesterday:
            continue
        results.append(
            RuleResult(
                rule_no=rule_no,
                rule_name=_rule_display_name(rule_no),
                yesterday_detail=None,
                resolved=False,
                today_detail="；".join(details),
            )
        )
    return results


def _flagged_by_rule(violations: list[Violation]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for v in violations:
        if not _is_flagged(v):
            continue
        grouped.setdefault(v.rule_no, []).append(v.detail)
    return grouped


def _pid_map_from_raw(raw_json: dict[str, Any] | None) -> dict[str, tuple[str, str]]:
    """raw_json.tickets → {ticket_no: (type_key, processInstanceId)}。"""
    if not isinstance(raw_json, dict):
        return {}
    tickets = raw_json.get("tickets")
    if not isinstance(tickets, list):
        return {}
    mapping: dict[str, tuple[str, str]] = {}
    for entry in tickets:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("processInstanceId") or entry.get("processInstanceID") or entry.get("id")
        if not pid:
            continue
        variables = entry.get("variables")
        ticket_no = str(
            entry.get("serialNumber")
            or entry.get("serialNo")
            or entry.get("ticketNo")
            or (variables.get("serialNumber") if isinstance(variables, dict) else "")
            or ""
        )
        if not ticket_no:
            continue
        mapping[ticket_no] = (str(entry.get("type") or ""), str(pid))
    return mapping


class RectifyChecker:
    """整改复查编排（依赖注入 parser/engine/repo 便于测试）。"""

    def __init__(
        self,
        session: AsyncSession,
        client: WorkTicketPlatformClient | None = None,
        parser: WorkTicketParser | None = None,
        rule_engine: WorkTicketRuleEngine | None = None,
        repo: WorkTicketReviewRepository | None = None,
    ) -> None:
        self.session = session
        self.client = client
        self.parser = parser or WorkTicketParser()
        self.rule_engine = rule_engine or WorkTicketRuleEngine()
        self.repo = repo or WorkTicketReviewRepository(session)

    async def run(
        self,
        source_review_date: date,
        checked_date: date,
    ) -> dict[str, Any] | None:
        """复查 source_review_date 审核的问题票，落库并返回汇总。

        返回 None = 无可复查对象（该日无审核记录 / 审核无问题票 / 拉取失败），
        调用方省略复查节，不视为错误。
        """
        review = await self.repo.get_by_date(source_review_date)
        if review is None:
            logger.info("整改复查：无 %s 审核记录，跳过", source_review_date)
            return None

        violations = await self.repo.list_violations(review.id)
        flagged_rows = [v for v in violations if _is_flagged_row(v.not_applicable)]
        if not flagged_rows:
            logger.info("整改复查：%s 审核无问题票，跳过", source_review_date)
            return None

        # 昨日问题票 → {ticket_no: (ticket_type, {rule_no: [detail]})}
        yesterday: dict[str, tuple[str, dict[str, list[str]]]] = {}
        for row in flagged_rows:
            _, grouped = yesterday.setdefault(
                row.ticket_no, (row.ticket_type, {}),
            )
            grouped.setdefault(row.rule_no, []).append(row.detail)

        pid_map = _pid_map_from_raw(review.raw_json)
        checks = await self._check_tickets(yesterday, pid_map)

        await self._save(source_review_date, checked_date, checks)
        return self._summary(source_review_date, checked_date, checks)

    # ── 逐票重拉重判 ──
    async def _check_tickets(
        self,
        yesterday: dict[str, tuple[str, dict[str, list[str]]]],
        pid_map: dict[str, tuple[str, str]],
    ) -> list[TicketCheck]:
        sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)

        async def check_one(ticket_no: str) -> TicketCheck:
            ticket_type, y_rules = yesterday[ticket_no]
            located = pid_map.get(ticket_no)
            if located is None:
                return TicketCheck(
                    ticket_no=ticket_no,
                    ticket_type=ticket_type,
                    status=STATUS_UNCHECKABLE,
                    note="审核快照缺该票原始数据，无法定位流程实例",
                )
            async with sem:
                today_rules = await self._rejudge(ticket_no, located)
            if today_rules is None:
                return TicketCheck(
                    ticket_no=ticket_no,
                    ticket_type=ticket_type,
                    status=STATUS_UNCHECKABLE,
                    note="复查拉取平台详情失败",
                )
            results = _compare_rules(y_rules, today_rules)
            all_resolved = all(r.resolved for r in results)
            return TicketCheck(
                ticket_no=ticket_no,
                ticket_type=ticket_type,
                status=STATUS_RECTIFIED if all_resolved else STATUS_UNRECTIFIED,
                rule_results=results,
            )

        return list(await asyncio.gather(*(check_one(no) for no in sorted(yesterday))))

    async def _rejudge(
        self,
        ticket_no: str,
        located: tuple[str, str],
    ) -> dict[str, list[str]] | None:
        """重拉 detail → 重解析 → 重判；返回 {rule_no: [detail]}，失败 None。"""
        type_key_raw, pid = located
        if self.client is None:
            return None
        try:
            detail = await self.client.detail(pid)
            process = detail.get("process") if isinstance(detail, dict) else None
            variables = process.get("variables") if isinstance(process, dict) else None
            if not isinstance(variables, dict):
                return None
            record = {
                "processInstanceId": pid,
                "serialNumber": ticket_no,
                "variables": variables,
            }
            ticket = self.parser.normalize(record, _resolve_type_key(type_key_raw))
            if ticket.is_void:
                return None
            return _flagged_by_rule(self.rule_engine.evaluate(ticket))
        except Exception:
            logger.warning("整改复查重判失败 ticket=%s pid=%s", ticket_no, pid, exc_info=True)
            return None

    # ── 落库（(source_review_date, ticket_no) 幂等覆盖）──
    async def _save(
        self,
        source_review_date: date,
        checked_date: date,
        checks: list[TicketCheck],
    ) -> None:
        stmt = select(WorkTicketRectifyCheck).where(
            WorkTicketRectifyCheck.source_review_date == source_review_date,
            WorkTicketRectifyCheck.is_deleted.is_(False),
        )
        existing = {
            row.ticket_no: row
            for row in (await self.session.execute(stmt)).scalars().all()
        }
        for check in checks:
            row = existing.get(check.ticket_no)
            if row is None:
                row = WorkTicketRectifyCheck(
                    source_review_date=source_review_date,
                    ticket_no=check.ticket_no,
                )
                self.session.add(row)
            row.checked_date = checked_date
            row.ticket_type = check.ticket_type
            row.status = check.status
            row.rule_results = [
                {
                    "rule_no": r.rule_no,
                    "rule_name": r.rule_name,
                    "yesterday_detail": r.yesterday_detail,
                    "resolved": r.resolved,
                    "today_detail": r.today_detail,
                }
                for r in check.rule_results
            ]
            row.note = check.note
        await self.session.flush()

    @staticmethod
    def _summary(
        source_review_date: date,
        checked_date: date,
        checks: list[TicketCheck],
    ) -> dict[str, Any]:
        by_status = {STATUS_RECTIFIED: 0, STATUS_UNRECTIFIED: 0, STATUS_UNCHECKABLE: 0}
        for check in checks:
            by_status[check.status] += 1
        return {
            "source_date": source_review_date.isoformat(),
            "checked_date": checked_date.isoformat(),
            "problem_total": len(checks),
            "rectified": by_status[STATUS_RECTIFIED],
            "unrectified": by_status[STATUS_UNRECTIFIED],
            "uncheckable": by_status[STATUS_UNCHECKABLE],
            "tickets": [
                {
                    "ticket_no": c.ticket_no,
                    "ticket_type": c.ticket_type,
                    "ticket_type_name": c.ticket_type_name,
                    "status": c.status,
                    "rule_results": [
                        {
                            "rule_no": r.rule_no,
                            "rule_name": r.rule_name,
                            "yesterday_detail": r.yesterday_detail,
                            "resolved": r.resolved,
                            "today_detail": r.today_detail,
                        }
                        for r in c.rule_results
                    ],
                    "note": c.note,
                }
                for c in checks
            ],
        }


async def run_rectify_check(
    session: AsyncSession,
    client: WorkTicketPlatformClient | None,
    source_review_date: date,
    checked_date: date,
) -> dict[str, Any] | None:
    """独立入口：复查某日审核的问题整改情况（service.run_review 内部调用）。"""
    return await RectifyChecker(session, client=client).run(
        source_review_date, checked_date,
    )


__all__ = [
    "RectifyChecker",
    "run_rectify_check",
    "TicketCheck",
    "RuleResult",
    "STATUS_RECTIFIED",
    "STATUS_UNRECTIFIED",
    "STATUS_UNCHECKABLE",
]
