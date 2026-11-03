"""FireAlarmScanSource —— R1 消防报警 cron 门控扫描源（kind=cron_scan）。

§9.2 组件映射定案形态：17:15 cron 门控（复用底座 due_fire_times——
幂等网格/停机回溯窗/首见 rebase 语义与 CronTickSource 完全对齐）到期才
拉近 window_days 天窗口，产出**报警记录粒度** Trigger：
``external_id = fire_alarm:<record_id>:<指纹>``（性质/原因分类/处理情况
三字段指纹——字段变更=新 Trigger，支撑闭环规则时变性，R8）。

closure_class 在本翻译层算好进 ``payload._derived``（规则引擎只判结构化
值，零 AI、无文本操作符需求）。读位=last_tick，推进由 ingest_source_once
在所覆盖 Trigger 全部落库后同事务承接（底座不变量，本源不自写 cursor）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.modules.safety.service.alarm_hazard_r1.closure import classify_closure
from app.platform.scheduler import ScheduleConfig
from app.platform.superagent.bitable_poll import relevant_fingerprint
from app.platform.superagent.models import AgentSource
from app.platform.superagent.sources import (
    DEFAULT_MAX_CATCHUP_SECONDS,
    PollResult,
    Source,
    TriggerDraft,
    due_fire_times,
)

logger = logging.getLogger(__name__)


async def fetch_fire_alarm_window(window_days: int) -> list[dict[str, Any]]:
    """拉近 N 天消防报警（报警时间倒序+提前终止；唯一数据源直读）。

    消防表不支持系统字段（修改时间）过滤（1254018 实测）——窗口语义按业务
    时间，幂等由 external_id 指纹约束兜底（重扫同批自动 duplicate）。
    """
    from app.modules.safety.service.bitable_direct import reader as bd_reader

    client = bd_reader.resolve_client("fire_alarm", "alarm")
    now = datetime.now(UTC)
    return await bd_reader.fetch_window_records(
        client,
        time_field="报警时间",
        start=now - timedelta(days=window_days),
        end=now + timedelta(days=1),
        page_size=500,
        automatic_fields=True,
    )


class FireAlarmScanSource(Source):
    """cron 门控批量扫描源（safety 侧定义，SourceRegistry 注册制挂入底座）。

    config 约定：
    - ``schedule``：ScheduleConfig 字段（R1= cron 15 17 * * * Asia/Shanghai）
    - ``window_days``：滚动窗口（默认 7，§9.2）
    - ``relevant_fields``：参与指纹的字段（R1= 报警性质/报警原因分类/处理情况）
    - ``thread_prefix``：thread_key 前缀（默认 fire_alarm）
    - ``evaluate``：true=落库后走 Slow Path 研判（observe/auto 由 Policy 管）
    - ``max_catchup_seconds``：停机回溯窗（默认 86400，对齐 CronTickSource）

    读位：``last_tick``（最后触发点 ISO 时间；首见只登记基准不回溯）。
    """

    kind = "cron_scan"

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

        # ── cron 门控（语义与 CronTickSource.poll 对齐）──
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

        # ── 到期：拉窗翻译为记录粒度 drafts ──
        window_days = int(cfg.get("window_days", 7))
        relevant = list(cfg.get("relevant_fields") or [])
        prefix = cfg.get("thread_prefix") or "fire_alarm"

        # 拉取失败直接抛（ingest_round 逐源容错记 poll_failed；读位未推进，
        # 下一轮 poll 重算同一触发点网格 → 窗口重拉，at-least-once）
        records = await fetch_fire_alarm_window(window_days)

        drafts: list[TriggerDraft] = []
        for rec in records or []:
            rid = rec.get("record_id") or ""
            if not rid:
                continue
            fields = rec.get("fields") or {}
            fp = relevant_fingerprint(fields, relevant)
            drafts.append(TriggerDraft(
                external_id=f"fire_alarm:{rid}:{fp}",
                thread_key=f"bitable:{prefix}:{rid}",
                actor={"id": rid, "type": "bitable_record"},
                human=False,
                addressed=False,
                payload={
                    "record_id": rid,
                    "fields": fields,
                    "last_modified_time": rec.get("last_modified_time"),
                    "fingerprint": fp,
                    "_derived": {"closure_class": classify_closure(fields.get("处理情况"))},
                    "channel": {"kind": "bitable", "record_id": rid},
                },
            ))
        logger.info(
            "cron_scan %s 一轮：窗口 %d 天 %d 条 → %d drafts",
            source_row.name, window_days, len(records or []), len(drafts),
        )
        # 读位推进到最后触发点（网格稳定不漂移；同事务由 ingest 承接）
        return PollResult(drafts=drafts, cursor_updates={"last_tick": fires[-1].isoformat()})
