"""GuardianCertScanSource —— R2 监护人持证 cron 门控扫描源（kind=cron_scan）。

拍板⑧：每日 08:00 扫监护人 A/B 证表全量（cert 直读链路，strict 失败聚合
上抛走补发），按「人+节点」粒度产出四型 Trigger（external_id 语义）：

- 提醒（拍板⑧核心）：``guardian:<rid>:<node>:<deadline:YYYY-MM>`` ——提醒月
  =「截止月-3/-2/-1」三个自然月（**不含全字段指纹**：同月内成绩写回等字段
  变化不产生新提醒；跨月键不同 → 每月恰一次、合计封顶 3 次）
- 逾期：``guardian:<rid>:<node>:overdue``（节点一次性键）
- 不合格：``guardian:<rid>:failed:<考核日期>``（再考再败可再触发）
- 恢复：``guardian:<rid>:restore:<考核日期>``（revoked 后出现新合格事件）

节点判定/成绩消费由 node_engine 纯函数完成（links.exam_history 注入视图）；
文本语义零参与——_derived 全结构化，规则引擎只判 trigger_type（rule.py）。
读位 last_tick，推进由 ingest_source_once 同事务承接（底座不变量）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.service.guardian_r2.node_engine import current_node
from app.modules.safety.service.guardian_r2.score_parse import (
    _flat_text,
    parse_person,
)
from app.platform.scheduler import ScheduleConfig
from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import (
    DEFAULT_MAX_CATCHUP_SECONDS,
    PollResult,
    Source,
    TriggerDraft,
    due_fire_times,
)

logger = logging.getLogger(__name__)

#: R2 持证扫描源实例名（迁移播种的 agent_sources.name；规则 source 过滤依据）
R2_CERT_SOURCE_NAME = "safety.guardian.r2"

#: 提醒窗口（拍板⑧）：截止月往前 3 个自然月；次数封顶 3
REMIND_MONTHS_BEFORE = 3
REMIND_MAX_COUNT = 3

_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

_GUARDIAN_KINDS = ("guardian_a", "guardian_b")


# ═══════════════════════════════════════════════════════════
# 纯函数：视图构建 / 分型 / 草稿
# ═══════════════════════════════════════════════════════════


@dataclass
class GuardianCertView:
    """持证记录视图（Bitable fields + links 状态合流；node_engine duck-typing）。"""

    record_id: str
    cert_category: str
    person_name: str
    guardian_open_id: str | None = None
    department: str | None = None
    issue_date: date | None = None
    first_review_deadline: date | None = None
    second_review_deadline: date | None = None
    should_renew_date: date | None = None
    renewed_date: date | None = None
    exam_score: str | None = None        # 考核成绩（机器人写回列，最新一次）
    exam_date: date | None = None        # 考核日期（写回列）
    exam_type: str | None = None         # 考核类型（取证/复审/换证，写回列）
    # links 合流字段
    exam_history: list[dict[str, Any]] = field(default_factory=list)
    last_score_event: dict[str, Any] | None = None
    qualification_status: str = "active"
    revoked_at: str | None = None            # ISO 日期（恢复校验：事件须晚于此）
    remind_count: int = 0
    last_reminded_month: str | None = None


def _ms_to_date(value: Any) -> date | None:
    """Bitable 原生日期列毫秒 → date（UTC 口径，与 cert 既有映射链一致）。

    机器人写回「考核日期」时按同口径构造毫秒，读写往返稳定。
    """
    if value in (None, ""):
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, tz=UTC).date()
    except (OSError, OverflowError):
        return None


def cert_view_from_fields(
    kind: str,
    record_id: str,
    fields: dict[str, Any],
    links_entry: dict[str, Any] | None,
) -> GuardianCertView | None:
    """Bitable fields + links 行 → 引擎视图（无姓名 → None 跳过）。

    基础日期字段复用 cert_bitable.map_guardian_cert_fields（既有映射单一
    来源），R2 扩展列（考核三列/人员 open_id）在此叠加——不污染既有镜像
    链路的 mapped dict 键集。
    """
    from app.modules.safety.feishu.cert_bitable import map_guardian_cert_fields

    mapped = map_guardian_cert_fields(fields, kind)
    if mapped is None:
        return None
    _, open_id = parse_person(fields.get("姓名"))
    links_entry = links_entry or {}
    return GuardianCertView(
        record_id=record_id,
        cert_category=kind,
        person_name=mapped.get("person_name") or "",
        guardian_open_id=open_id,
        department=mapped.get("department"),
        issue_date=mapped.get("issue_date"),
        first_review_deadline=mapped.get("first_review_deadline"),
        second_review_deadline=mapped.get("second_review_deadline"),
        should_renew_date=mapped.get("should_renew_date"),
        renewed_date=mapped.get("renewed_date"),
        exam_score=_flat_text(fields.get("考核成绩")),
        exam_date=_ms_to_date(fields.get("考核日期")),
        exam_type=_flat_text(fields.get("考核类型")),
        exam_history=list(links_entry.get("exam_history") or []),
        last_score_event=links_entry.get("last_score_event"),
        revoked_at=links_entry.get("revoked_at"),
        qualification_status=links_entry.get("qualification_status") or "active",
        remind_count=int(links_entry.get("remind_count") or 0),
        last_reminded_month=links_entry.get("last_reminded_month"),
    )


def remind_month_keys(deadline: date) -> list[str]:
    """截止月 M → [M-3, M-2, M-1]（YYYY-MM，跨年正确，恰 3 个自然月）。"""
    keys: list[str] = []
    year, month = deadline.year, deadline.month
    for back in range(REMIND_MONTHS_BEFORE, 0, -1):
        m = month - back
        y = year
        while m <= 0:
            m += 12
            y -= 1
        keys.append(f"{y:04d}-{m:02d}")
    return keys


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _build_draft(
    view: GuardianCertView,
    trigger_type: str,
    external_id: str,
    node: Any,
    today: date,
) -> TriggerDraft:
    derived: dict[str, Any] = {
        "trigger_type": trigger_type,
        "record_id": view.record_id,
        "person_name": view.person_name,
        "guardian_open_id": view.guardian_open_id,
        "department": view.department,
        "cert_category": view.cert_category,
        "issue_date": view.issue_date.isoformat() if view.issue_date else None,
        "node_key": getattr(node, "node_key", None),
        "node_label": getattr(node, "label", None),
        "exam_kind": getattr(node, "exam_kind", None),
        "deadline": node.deadline.isoformat() if getattr(node, "deadline", None) else None,
        "remaining_days": getattr(node, "remaining_days", None),
        "exam_score": view.exam_score,
        "exam_date": view.exam_date.isoformat() if view.exam_date else None,
        "exam_type": view.exam_type,
        "qualification_status": view.qualification_status,
        "remind_count": view.remind_count,
        "remind_seq": view.remind_count + 1,  # 本次是第 N 次（文案用）
        "remind_month": _month_key(today),    # 发送月（执行器计数键）
    }
    return TriggerDraft(
        external_id=external_id,
        thread_key=f"guardian_cert:{view.record_id}",
        actor={"id": view.record_id, "type": "bitable_record"},
        human=False,
        addressed=False,
        payload={
            "record_id": view.record_id,
            "_derived": derived,
            "channel": {"kind": "bitable", "record_id": view.record_id},
        },
    )


def build_cert_drafts(
    records: list[dict[str, Any]],
    links_map: dict[str, dict[str, Any]],
    *,
    today: date,
) -> list[TriggerDraft]:
    """记录批 + links 状态 → 四型 TriggerDraft（纯函数，分型矩阵见测试）。

    revoked 静默（仅恢复路径）；remind 需 当前月∈提醒窗 且 remind_count<3；
    failed/overdue 键含日期/节点防误重复。
    """
    drafts: list[TriggerDraft] = []
    for rec in records or []:
        rid = rec.get("record_id") or ""
        fields = rec.get("fields") or {}
        kind = rec.get("kind") or ""
        if not rid or kind not in _GUARDIAN_KINDS:
            continue
        view = cert_view_from_fields(kind, rid, fields, links_map.get(rid))
        if view is None:
            continue
        node = current_node(view, ref_date=today)

        if view.qualification_status == "revoked":
            # revoked + **新的**合格事件（晚于吊销日；last_score_event 权威，
            # history 兜底）→ 恢复确认（键=考核日期）——吊销前的旧合格事件
            # 不触发恢复
            score_event = view.last_score_event
            if (score_event or {}).get("passed") != "合格":
                score_event = _latest_pass_event(view.exam_history)
            if (
                score_event is not None
                and score_event.get("passed") == "合格"
                and _event_after(score_event.get("exam_date"), view.revoked_at)
            ):
                drafts.append(_build_draft(
                    view, "restore",
                    f"guardian:{rid}:restore:{score_event.get('exam_date')}",
                    node, today,
                ))
            continue

        if view.exam_score == "不合格" and view.exam_date is not None:
            drafts.append(_build_draft(
                view, "failed",
                f"guardian:{rid}:failed:{view.exam_date.isoformat()}",
                node, today,
            ))
            continue

        if node.node_key is None or node.deadline is None:
            continue
        if node.remaining_days is not None and node.remaining_days < 0:
            # 逾期静默（2026-11-06 拍板④）：不产 overdue Trigger、不进速递
            # 「需要人」、不 DM——大量逾期者是放弃考证/放弃监护资格的存量，
            # 系统只做「提醒 + 成绩/证书联动管理」；逾期者若日后考合格，
            # 走成绩映射链正常写回/进名单，无需逾期链路催办。
            continue
        if (
            _month_key(today) in remind_month_keys(node.deadline)
            and view.remind_count < REMIND_MAX_COUNT
        ):
            # 提醒键=发送月（非截止月）：跨月新键 → 每月恰一次、合计 3 次
            drafts.append(_build_draft(
                view, "remind",
                f"guardian:{rid}:{node.node_key}:remind:{_month_key(today)}",
                node, today,
            ))
    return drafts


def _latest_pass_event(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """考核事件流中最新一条合格事件（恢复判定依据）。"""
    for event in reversed(history or []):
        if isinstance(event, dict) and event.get("passed") == "合格":
            return event
    return None


def _event_after(event_date: Any, revoked_at: str | None) -> bool:
    """恢复校验：合格事件日期须晚于吊销日（吊销前旧事件不触发恢复）。"""
    if revoked_at is None:
        return True
    try:
        return date.fromisoformat(str(event_date)) > date.fromisoformat(
            str(revoked_at)[:10]
        )
    except (TypeError, ValueError):
        return False


# ═══════════════════════════════════════════════════════════
# IO 壳：拉取 + links 合流 + cron 门控
# ═══════════════════════════════════════════════════════════


async def fetch_guardian_cert_records() -> list[dict[str, Any]]:
    """拉监护人 A/B 证两表全量（cert 直读链路，strict：任一失败聚合上抛）。"""
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for kind in _GUARDIAN_KINDS:
        try:
            client = bd_reader.resolve_client("cert", kind)
            rows = await bd_reader.fetch_all_records(client)
        except Exception as exc:  # strict：聚合后上抛（poll_failed → 补发）
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")
            continue
        for row in rows or []:
            records.append({
                "record_id": row.get("record_id") or "",
                "kind": kind,
                "fields": row.get("fields") or {},
            })
    if errors:
        raise RuntimeError(
            "监护人持证表拉取失败（strict 聚合）: " + " | ".join(errors)
        )
    return records


async def load_links_map(session: Any) -> dict[str, dict[str, Any]]:
    """links 活行全量 → {record_id: 摘要 dict}（_view_from_fields 消费）。"""
    from sqlalchemy import select

    from app.modules.safety.models.guardian_qualification_link import (
        GuardianQualificationLink,
    )

    rows = (
        await session.execute(
            select(GuardianQualificationLink).where(
                GuardianQualificationLink.is_deleted == False,  # noqa: E712
            )
        )
    ).scalars().all()
    return {
        r.record_id: {
            "qualification_status": r.qualification_status,
            "remind_count": r.remind_count,
            "last_reminded_month": r.last_reminded_month,
            "exam_history": list(r.exam_history or []),
            "last_score_event": r.last_score_event,
        }
        for r in rows
    }


class GuardianCertScanSource(Source):
    """cron 门控批量扫描源（safety 侧定义，SourceRegistry 注册制挂入底座）。

    kind=guardian_cert_scan（应用侧自定义 kind——"cron_scan" 已被 R1 消防源
    占用，SourceRegistry 按 kind 唯一映射插件实例）。

    config 约定（迁移播种）：
    - ``schedule``：ScheduleConfig（R2 = cron 0 8 * * * Asia/Shanghai）
    - ``evaluate``：true → 落库后走 Slow Path 研判（observe/auto 由 Policy 管）
    - ``thread_prefix``：thread_key 前缀（默认 guardian_cert）
    - ``max_catchup_seconds``：停机回溯窗（默认 86400）

    读位：``last_tick``（首见只登记基准不回溯）。
    """

    kind = "guardian_cert_scan"

    async def poll(
        self,
        session: Any,
        source_row: AgentSource,
        cursors: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> PollResult:
        cfg = source_row.config or {}
        schedule = ScheduleConfig(**(cfg.get("schedule") or {
            "strategy": "interval", "interval_seconds": 86400,
        }))
        tz = ZoneInfo(schedule.timezone)
        now = now or datetime.now(tz)
        max_catchup = int(cfg.get("max_catchup_seconds", DEFAULT_MAX_CATCHUP_SECONDS))

        # ── cron 门控（语义与 CronTickSource/R1 对齐）──
        last_raw = cursors.get("last_tick")
        if isinstance(last_raw, dict):
            last_raw = last_raw.get("value")
        if not last_raw:
            return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
        last = datetime.fromisoformat(str(last_raw))

        fires = due_fire_times(schedule, last, now, max_catchup_seconds=max_catchup)
        if not fires:
            if (now - last).total_seconds() > max_catchup:
                return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
            return PollResult()

        # ── 到期：拉全量 + links 合流 → 分型 drafts ──
        records = await fetch_guardian_cert_records()  # 失败上抛 → poll_failed 补发
        links_map = await load_links_map(session)
        today = now.astimezone(tz).date()
        drafts = build_cert_drafts(records, links_map, today=today)

        logger.info(
            "cron_scan %s 一轮：%d 条记录 → %d drafts（提醒 %d）",
            source_row.name, len(records), len(drafts),
            sum(1 for d in drafts
                if d.payload["_derived"]["trigger_type"] == "remind"),
        )
        return PollResult(
            drafts=drafts, cursor_updates={"last_tick": fires[-1].isoformat()}
        )
