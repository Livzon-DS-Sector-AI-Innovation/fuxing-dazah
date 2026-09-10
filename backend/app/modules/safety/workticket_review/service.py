"""作业票审核服务编排（WorkTicketReviewService）。

run_review 依次执行：
  client 拉取当日 8 类票 → parser 归一化 → rule_engine 规则判定 →
  repository 幂等落库（review 摘要 + 逐票违规明细）→ report_builder 生成 Markdown →
  push=True 时 send_group_card 推送（失败抛异常由调度器重试）。

约定：
- 只审核“已具备 start_time”的票；其余计入 data_insufficient（报告以“数据不足”标记）。
- 违规/不适用/数据不足的分类沿用 rule_engine 与 report_builder 的约定：
  * 真实违规 = not_applicable=False 且 detail 不以“数据不足：”开头；
  * 数据不足 = 缺少关键时间字段 或 detail 以“数据不足：”开头；
  * 不适用 = not_applicable=True。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.feishu.notification import send_group_card
from app.modules.safety.models import (
    WorkTicketReview,
    WorkTicketReviewViolation,
)
from app.modules.safety.workticket_review.client import (
    TICKET_TYPE_KEYS,
    WorkTicketPlatformClient,
)
from app.modules.safety.workticket_review.parser import WorkTicket, WorkTicketParser
from app.modules.safety.workticket_review.report_builder import (
    TICKET_TYPE_NAMES,
    WorkTicketReviewReportBuilder,
)
from app.modules.safety.workticket_review.repository import WorkTicketReviewRepository
from app.modules.safety.workticket_review.rule_engine import (
    Violation,
    WorkTicketRuleEngine,
)

logger = logging.getLogger(__name__)

# ── 环境变量加载（与 client.py 保持一致） ──
_env_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
_app_env = os.getenv("APP_ENV", "development")
_env_path = _env_dir / f".env.{_app_env}"
if _env_path.exists():
    load_dotenv(_env_path, override=True)

TZ = ZoneInfo("Asia/Shanghai")

# 特殊作业自动分配群；可用环境变量 SAFETY_WORKTICKET_GROUP_ID 覆盖。
REPORT_GROUP_CHAT_ID = os.getenv(
    "SAFETY_WORKTICKET_GROUP_ID",
    "oc_d102e1a11eaaa9a1de3b41859de9d0c1",
)

# 数据不足伪违规编号（报告模板仅遍历 RuleNo 的真实规则，不影响展示）。
_DATA_INSUFFICIENT_RULE_NO = "DATA_INSUFFICIENT"
_DATA_INSUFFICIENT_RULE_NAME = "数据不足"


def _is_data_insufficient(violation: Violation) -> bool:
    """判断 Violation 是否属于“数据不足/待跟进”。"""
    return (
        not violation.not_applicable
        and violation.detail.strip().startswith("数据不足")
    )


def _is_real_violation(violation: Violation) -> bool:
    return not violation.not_applicable and not _is_data_insufficient(violation)


class WorkTicketReviewService:
    """作业票审核服务编排（拉→解析→判→落库→推送）。"""

    def __init__(
        self,
        session: AsyncSession,
        client: WorkTicketPlatformClient | None = None,
        parser: WorkTicketParser | None = None,
        rule_engine: WorkTicketRuleEngine | None = None,
        repo: WorkTicketReviewRepository | None = None,
        builder: WorkTicketReviewReportBuilder | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.session = session
        self.client = client or WorkTicketPlatformClient()
        self.parser = parser or WorkTicketParser()
        self.rule_engine = rule_engine or WorkTicketRuleEngine()
        self.repo = repo or WorkTicketReviewRepository(session)
        self.builder = builder or WorkTicketReviewReportBuilder()
        self.chat_id = chat_id  # 发送目标唯一来源：调度器/调用方配置（DB 播种/覆写），不再回退默认群
        self._owns_client = client is None

    # ── 对外入口 ──

    async def run_review(
        self,
        review_date: date_cls | str,
        push: bool = True,
    ) -> dict[str, Any]:
        """执行一次作业票审核。

        Args:
            review_date: 审核日期（date 或 'YYYY-MM-DD'）。
            push: 是否推送飞书群卡片。

        Returns:
            包含 date/total/reviewed/violation_count/compliant_count/
            data_insufficient/markdown_report/push_result/message_id 等的 dict。
        """
        review_date = self._coerce_date(review_date)
        raw_tickets: list[dict[str, Any]] = []

        try:
            raw_tickets = await self.client.list_tickets_for_date(review_date)
        except Exception as exc:
            logger.exception("作业票拉取失败 date=%s", review_date)
            failed = self._make_failed_review(
                review_date,
                error=f"拉取失败：{exc}",
                raw_tickets=None,
            )
            await self.repo.save_review(failed, [])
            await self.session.commit()
            raise RuntimeError(
                f"作业票审核拉取失败 {review_date}: {exc}"
            ) from exc
        finally:
            if self._owns_client:
                await self.client.close()

        tickets, parse_errors = self._normalize(raw_tickets)
        violations_by_ticket, stats = self._evaluate(tickets)

        # 先构建“未推送”版本 markdown 用于卡片内容；push 失败时亦以此落库。
        markdown = self.builder.build(
            review_date,
            tickets,
            violations_by_ticket,
            {**stats, "pushed": False},
        )

        push_result: dict[str, Any] = {
            "chat_id": self.chat_id,
            "pushed": False,
            "success": None,
            "message_id": None,
        }

        if push:
            try:
                msg_id = await send_group_card(
                    chat_id=self.chat_id,
                    title=f"作业票审核日报 - {review_date.isoformat()}",
                    content=markdown,
                )
                if msg_id:
                    push_result = {
                        "chat_id": self.chat_id,
                        "pushed": True,
                        "success": True,
                        "message_id": msg_id,
                    }
                else:
                    push_result = {
                        "chat_id": self.chat_id,
                        "pushed": False,
                        "success": False,
                        "message_id": None,
                        "error": "飞书未返回 message_id",
                    }
            except Exception as exc:
                logger.exception(
                    "作业票审核推送失败 date=%s chat_id=%s",
                    review_date,
                    self.chat_id,
                )
                push_result = {
                    "chat_id": self.chat_id,
                    "pushed": False,
                    "success": False,
                    "message_id": None,
                    "error": str(exc),
                }

            if not push_result.get("success"):
                error_text = push_result.get("error") or "未返回 message_id"
                review = self._make_review(
                    review_date,
                    stats,
                    markdown,
                    status="failed",
                    pushed=False,
                    message_id=None,
                    error=f"推送失败：{error_text}",
                    raw_tickets=raw_tickets,
                    parse_errors=parse_errors,
                )
                await self.repo.save_review(
                    review,
                    self._build_violation_rows(review, tickets, violations_by_ticket),
                )
                await self.session.commit()
                raise RuntimeError(
                    f"作业票审核推送失败 {review_date} ({self.chat_id}): {error_text}"
                ) from None

            review = self._make_review(
                review_date,
                stats,
                markdown,
                status="success",
                pushed=True,
                message_id=push_result.get("message_id"),
                error=None,
                raw_tickets=raw_tickets,
                parse_errors=parse_errors,
            )
            # 推送成功后更新 markdown 的“已推送”状态。
            markdown = self.builder.build(
                review_date,
                tickets,
                violations_by_ticket,
                {**stats, "pushed": True},
            )
            review.report_markdown = markdown
        else:
            review = self._make_review(
                review_date,
                stats,
                markdown,
                status="success",
                pushed=False,
                message_id=None,
                error=None,
                raw_tickets=raw_tickets,
                parse_errors=parse_errors,
            )

        await self.repo.save_review(
            review,
            self._build_violation_rows(review, tickets, violations_by_ticket),
        )
        await self.session.commit()

        return self._build_result(
            review_date=review_date,
            stats=stats,
            markdown=markdown,
            push_result=push_result,
            tickets=tickets,
            violations_by_ticket=violations_by_ticket,
            status="success",
            parse_errors=parse_errors,
        )

    # ── 内部编排辅助 ──

    @staticmethod
    def _coerce_date(value: date_cls | str) -> date_cls:
        if isinstance(value, date_cls):
            return value
        return date_cls.fromisoformat(str(value).strip())

    def _normalize(
        self,
        raw_tickets: list[dict[str, Any]],
    ) -> tuple[list[WorkTicket], list[dict[str, Any]]]:
        """逐条归一化；单票解析异常不回退整个任务，降级为“数据不足”票。"""
        tickets: list[WorkTicket] = []
        parse_errors: list[dict[str, Any]] = []
        for raw in raw_tickets:
            type_key = self._resolve_type_key(raw.get("type", ""))
            try:
                ticket = self.parser.normalize(raw, type_key)
                if ticket.is_void:  # 废案（已终止/无信息）不计入
                    continue
                tickets.append(ticket)
            except Exception as exc:
                logger.warning("解析作业票失败: %s", exc)
                parse_errors.append(
                    {
                        "type": type_key,
                        "serialNumber": str(
                            raw.get("serialNumber") or raw.get("serialNo") or ""
                        ),
                        "error": str(exc),
                    }
                )
                ticket = WorkTicket(
                    ticket_type=type_key or "unknown",
                    ticket_no=str(
                        raw.get("serialNumber")
                        or raw.get("serialNo")
                        or raw.get("ticketNo")
                        or ""
                    ),
                    process_instance_id=str(
                        raw.get("processInstanceId")
                        or raw.get("processInstanceID")
                        or raw.get("id")
                        or ""
                    ),
                    start_time=None,
                    missing=["parse_error"],
                    raw=dict(raw),
                    status=str(raw.get("status") or ""),
                )
                tickets.append(ticket)
        return tickets, parse_errors

    def _evaluate(
        self,
        tickets: list[WorkTicket],
    ) -> tuple[dict[str, list[Violation]], dict[str, int]]:
        """对每张票执行规则引擎并统计。

        只审核已具备 start_time 的票；缺失 start_time 的票直接标记为数据不足。
        """
        violations_by_ticket: dict[str, list[Violation]] = {}
        reviewed = 0
        real_ticket_keys: set[str] = set()
        insufficient_ticket_keys: set[str] = set()
        compliant = 0

        for ticket in tickets:
            key = ticket.ticket_no or ticket.process_instance_id or ""
            if ticket.start_time is None:
                # 主动补充一条数据不足标记，确保报告模板将其归入“数据不足/待跟进”。
                violations_by_ticket.setdefault(key, []).append(
                    Violation(
                        rule_no=_DATA_INSUFFICIENT_RULE_NO,
                        rule_name=_DATA_INSUFFICIENT_RULE_NAME,
                        detail="数据不足：缺少 start_time",
                        key_times=[],
                        not_applicable=False,
                    )
                )
                insufficient_ticket_keys.add(key)
                continue

            reviewed += 1
            result = self.rule_engine.evaluate(ticket)
            violations_by_ticket[key] = list(result)

            real = [v for v in result if _is_real_violation(v)]
            insufficient = [v for v in result if _is_data_insufficient(v)]
            if real:
                real_ticket_keys.add(key)
            if insufficient:
                insufficient_ticket_keys.add(key)
            if not real and not insufficient:
                compliant += 1

        total = len(tickets)
        data_insufficient = len(insufficient_ticket_keys)

        stats = {
            "total": total,
            "reviewed": reviewed,
            "violation_count": len(real_ticket_keys),
            "compliant_count": compliant,
            "data_insufficient": data_insufficient,
        }
        return violations_by_ticket, stats

    def _make_review(
        self,
        review_date: date_cls,
        stats: dict[str, int],
        markdown: str | None,
        *,
        status: str,
        pushed: bool,
        message_id: str | None,
        error: str | None,
        raw_tickets: list[dict[str, Any]] | None,
        parse_errors: list[dict[str, Any]] | None,
    ) -> WorkTicketReview:
        return WorkTicketReview(
            date=review_date,
            total=stats["total"],
            reviewed=stats["reviewed"],
            violation_count=stats["violation_count"],
            compliant_count=stats["compliant_count"],
            data_insufficient=stats["data_insufficient"],
            status=status,
            raw_json=self._raw_payload(raw_tickets, parse_errors, stats),
            report_markdown=markdown,
            pushed=pushed,
            push_message_id=message_id,
            error=error,
            finished_at=datetime.now(TZ),
        )

    def _make_failed_review(
        self,
        review_date: date_cls,
        *,
        error: str,
        raw_tickets: list[dict[str, Any]] | None,
    ) -> WorkTicketReview:
        return WorkTicketReview(
            date=review_date,
            total=0,
            reviewed=0,
            violation_count=0,
            compliant_count=0,
            data_insufficient=0,
            status="failed",
            raw_json=self._raw_payload(raw_tickets, [], {"total": 0}),
            report_markdown=None,
            pushed=False,
            push_message_id=None,
            error=error,
            finished_at=datetime.now(TZ),
        )

    def _build_violation_rows(
        self,
        review: WorkTicketReview,
        tickets: list[WorkTicket],
        violations_by_ticket: dict[str, list[Violation]],
    ) -> list[WorkTicketReviewViolation]:
        """构造逐票违规明细 ORM 行（review_id 由仓储在 save 时回填）。"""
        del review  # 未直接使用
        rows: list[WorkTicketReviewViolation] = []
        for ticket in tickets:
            key = ticket.ticket_no or ticket.process_instance_id or ""
            for violation in violations_by_ticket.get(key, []):
                rows.append(
                    WorkTicketReviewViolation(
                        ticket_no=ticket.ticket_no or ticket.process_instance_id or key,
                        ticket_type=ticket.ticket_type,
                        rule_no=violation.rule_no,
                        rule_name=violation.rule_name,
                        detail=violation.detail,
                        key_times=self._key_times_to_dict(violation.key_times),
                        not_applicable=violation.not_applicable,
                    )
                )
        return rows

    def _build_result(
        self,
        *,
        review_date: date_cls,
        stats: dict[str, int],
        markdown: str,
        push_result: dict[str, Any],
        tickets: list[WorkTicket],
        violations_by_ticket: dict[str, list[Violation]],
        status: str,
        parse_errors: list[dict[str, Any]],
    ) -> dict[str, Any]:
        real_details: list[dict[str, Any]] = []
        insufficient_details: list[dict[str, Any]] = []
        ticket_by_key = {
            (t.ticket_no or t.process_instance_id or ""): t for t in tickets
        }
        for key, violations in violations_by_ticket.items():
            ticket = ticket_by_key.get(key)
            ticket_type = ticket.ticket_type if ticket else ""
            type_name = TICKET_TYPE_NAMES.get(ticket_type, ticket_type)
            for v in violations:
                if _is_real_violation(v):
                    real_details.append(
                        {
                            "ticket_no": key,
                            "ticket_type": ticket_type,
                            "ticket_type_name": type_name,
                            "rule_no": v.rule_no,
                            "rule_name": v.rule_name,
                            "detail": v.detail,
                        }
                    )
                elif _is_data_insufficient(v):
                    insufficient_details.append(
                        {
                            "ticket_no": key,
                            "ticket_type": ticket_type,
                            "ticket_type_name": type_name,
                            "rule_no": v.rule_no,
                            "rule_name": v.rule_name,
                            "detail": v.detail,
                        }
                    )

        return {
            "date": review_date.isoformat(),
            "total": stats["total"],
            "reviewed": stats["reviewed"],
            "violation_count": stats["violation_count"],
            "compliant_count": stats["compliant_count"],
            "data_insufficient": stats["data_insufficient"],
            "status": status,
            "markdown_report": markdown,
            "push_result": push_result,
            "message_id": push_result.get("message_id"),
            "violation_details": real_details,
            "data_insufficient_details": insufficient_details,
            "parse_errors": parse_errors,
        }

    # ── 工具方法 ──

    @staticmethod
    def _resolve_type_key(type_key: str) -> str:
        if type_key in TICKET_TYPE_KEYS:
            return type_key
        for ticket_type, process_key in TICKET_TYPE_KEYS.items():
            if process_key == type_key:
                return ticket_type
        return type_key

    @staticmethod
    def _raw_payload(
        raw_tickets: list[dict[str, Any]] | None,
        parse_errors: list[dict[str, Any]] | None,
        stats: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tickets": raw_tickets or [],
            "parse_errors": parse_errors or [],
            "stats": stats or {},
        }
        try:
            return cast(dict[str, Any], json.loads(json.dumps(payload, default=str, ensure_ascii=False)))
        except (TypeError, ValueError):
            return {
                "tickets": [],
                "parse_errors": parse_errors or [],
                "stats": stats or {},
            }

    @staticmethod
    def _key_times_to_dict(key_times: list[str] | None) -> dict[str, Any] | None:
        if not key_times:
            return None
        result: dict[str, Any] = {}
        for item in key_times:
            if "=" in item:
                key, _, value = item.partition("=")
                result[key.strip()] = value.strip()
            else:
                result[str(item)] = str(item)
        return result


__all__ = [
    "REPORT_GROUP_CHAT_ID",
    "WorkTicketReviewService",
]
