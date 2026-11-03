"""事件层 —— Source 插件抽象 + cron_tick 内置源 + Fast Path 纯函数。

Source 协议四要素（对标仓库 SourceKind）：
- ``kind``：插件稳定标识
- ``scope``：收什么/不收什么——这里固化为 :func:`fastpath_reason` 纯函数，
  仅凭 meta（actor/thread 键）与配置判定，复验可用；**永不读消息文本**（红线⑦）
- ``poll``：拉取一轮并翻译为 Trigger 草稿；读位由 ingest 在所覆盖 Trigger
  全部落库后同事务推进（Source 不自写 cursor）
- ``fields``：配置 schema（文档化约定，一期以 dataclass 约定承载）
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter  # type: ignore[import-untyped]

from app.platform.scheduler import ScheduleConfig, ScheduleStrategy
from app.platform.superagent.models import AgentSource

logger = logging.getLogger(__name__)

# 停机回溯窗（默认 24h）：基准早于该窗 → 不回溯、要求重设基准（防重启洪泛）
DEFAULT_MAX_CATCHUP_SECONDS = 86400


# ═══════════════════════════════════════════════════════════════
# 纯函数：disposition / Fast Path / 调度触发点
# ═══════════════════════════════════════════════════════════════


def make_disposition_step(step: str, *, reason: str = "") -> dict[str, Any]:
    """构造一条追加式处置步骤。step ∈ stored/duplicate/filtered/reached_task。"""
    out: dict[str, Any] = {"step": step, "at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()}
    if reason:
        out["reason"] = reason
    return out


def fastpath_reason(source_config: dict | None, draft: TriggerDraft) -> str | None:
    """程序级确定性过滤：返回 None=放行，str=拦截原因（记 filtered）。

    只看 actor 结构化字段与配置名单；消息文本永不参与（红线⑦）。
    规则（按序）：
    1. ``self_actors``：机器人自身消息 → 拦截（防环）
    2. ``thread_allowlist``：声明了线程/群白名单且不在名单 → 拦截（群白名单维度）
    3. ``actor_allowlist``：声明了白名单且 actor 不在 → 拦截
    4. ``ignore_actors``：显式忽略名单 → 拦截
    """
    cfg = source_config or {}
    actor_id = (draft.actor or {}).get("id") or ""

    self_actors = set(cfg.get("self_actors") or [])
    if actor_id and actor_id in self_actors:
        return f"self_actor:{actor_id}"

    thread_allowlist = cfg.get("thread_allowlist")
    if isinstance(thread_allowlist, list):
        channel = (draft.payload or {}).get("channel") or {}
        keys = {draft.thread_key, str(channel.get("chat_id") or "")}
        if not keys & set(thread_allowlist):
            return f"thread_not_in_allowlist:{draft.thread_key[:64]}"

    allowlist = cfg.get("actor_allowlist")
    if isinstance(allowlist, list):
        if not actor_id or actor_id not in set(allowlist):
            return f"actor_not_in_allowlist:{actor_id or 'none'}"

    ignore_actors = set(cfg.get("ignore_actors") or [])
    if actor_id and actor_id in ignore_actors:
        return f"ignored_actor:{actor_id}"

    return None


def due_fire_times(
    schedule: ScheduleConfig,
    last: datetime,
    now: datetime,
    *,
    max_catchup_seconds: int = DEFAULT_MAX_CATCHUP_SECONDS,
) -> list[datetime]:
    """推导 (last, now] 区间内的全部调度触发点（外部按计划时间构造幂等键）。

    停机超窗守卫：last 距 now 超过 max_catchup_seconds → 零触发（由调用方
    重设基准），防重启回溯洪泛。
    """
    if (now - last).total_seconds() > max_catchup_seconds:
        return []

    match schedule.strategy:
        case ScheduleStrategy.INTERVAL:
            return _interval_fires(schedule, last, now, max_catchup_seconds)
        case ScheduleStrategy.FIXED_TIME:
            return _fixed_time_fires(schedule, last, now)
        case ScheduleStrategy.CRON:
            return _cron_fires(schedule, last, now, max_catchup_seconds)
    return []


def _interval_fires(
    schedule: ScheduleConfig, last: datetime, now: datetime, max_catchup: int,
) -> list[datetime]:
    fires: list[datetime] = []
    cap = max_catchup // max(1, schedule.interval_seconds) + 1
    t = last.timestamp() + schedule.interval_seconds
    while t <= now.timestamp() and len(fires) < cap:
        fires.append(datetime.fromtimestamp(t, tz=last.tzinfo or ZoneInfo(schedule.timezone)))
        t += schedule.interval_seconds
    return fires


def _fixed_time_fires(
    schedule: ScheduleConfig, last: datetime, now: datetime,
) -> list[datetime]:
    h, m = (int(x) for x in schedule.time_of_day.split(":"))
    fires: list[datetime] = []
    day = last.date()
    from datetime import time as dtime

    while day <= now.date():
        candidate = datetime.combine(day, dtime(h, m), tzinfo=last.tzinfo or ZoneInfo(schedule.timezone))
        if last < candidate <= now:
            fires.append(candidate)
        day = _next_day(day)
    return fires


def _next_day(day: Any) -> Any:
    from datetime import timedelta

    return day + timedelta(days=1)


def _cron_fires(
    schedule: ScheduleConfig, last: datetime, now: datetime, max_catchup: int,
) -> list[datetime]:
    if not schedule.expression:
        return []
    tz = last.tzinfo or ZoneInfo(schedule.timezone)
    naive = last.replace(tzinfo=None)
    cron = croniter(schedule.expression, naive)
    fires: list[datetime] = []
    cap = max_catchup // 60 + 1  # cron 最细分钟级
    while len(fires) < cap:
        nxt_naive: datetime = cron.get_next(datetime)
        nxt = nxt_naive.replace(tzinfo=tz)
        if nxt > now:
            break
        fires.append(nxt)
    return fires


# ═══════════════════════════════════════════════════════════════
# Trigger 草稿与 Source 协议
# ═══════════════════════════════════════════════════════════════


@dataclass(slots=True)
class TriggerDraft:
    """Source 翻译产出的事件草稿（入库前形态）。"""

    external_id: str
    thread_key: str
    actor: dict[str, Any] | None = None
    human: bool = False
    addressed: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def cron_tick(cls, job: str, scheduled_at: datetime) -> TriggerDraft:
        """cron_tick 事件的稳定形态（external_id=job:计划时间，天然幂等）。"""
        return cls(
            external_id=f"{job}:{scheduled_at.isoformat()}",
            thread_key=f"cron:{job}",
            human=False,
            addressed=False,
            payload={"job": job, "scheduled_at": scheduled_at.isoformat()},
        )


@dataclass(slots=True)
class PollResult:
    """单轮拉取结果：草稿 + 读位推进值（由 ingest 在草稿全部落库后同事务写入）。"""

    drafts: list[TriggerDraft] = field(default_factory=list)
    cursor_updates: dict[str, Any] = field(default_factory=dict)
    # 基准重设（首见/超窗）：无草稿但读位直接推进到 now
    rebase: bool = False


class Source(ABC):
    """Source 插件协议。子类设置 ``kind`` 并实现 :meth:`poll`。"""

    kind: str = ""

    @abstractmethod
    async def poll(
        self,
        session: Any,
        source_row: AgentSource,
        cursors: dict[str, Any],
    ) -> PollResult:
        """拉取一轮并翻译为草稿。cursor 值为当前持久化读位（勿自写）。"""


class CronTickSource(Source):
    """内置源：把时间调度翻译成 Trigger（定时→研判→任务，为二期定时任务工单化铺路）。

    config 约定：
    - ``job``：任务名（external_id 前缀；缺省用实例 name）
    - ``schedule``：ScheduleConfig 字段（strategy/expression/interval_seconds/time_of_day/timezone）
    - ``max_catchup_seconds``：停机回溯窗（默认 86400）

    读位：``last_tick``（ISO 时间）。首次无读位只登记基准不回溯（防启用洪泛）。
    """

    kind = "cron_tick"

    async def poll(
        self,
        session: Any,
        source_row: AgentSource,
        cursors: dict[str, Any],
    ) -> PollResult:
        cfg = source_row.config or {}
        job = cfg.get("job") or source_row.name
        schedule = ScheduleConfig(**(cfg.get("schedule") or {"strategy": "interval", "interval_seconds": 3600}))
        tz = ZoneInfo(schedule.timezone)
        now = datetime.now(tz)
        max_catchup = int(cfg.get("max_catchup_seconds", DEFAULT_MAX_CATCHUP_SECONDS))

        last_raw = (cursors.get("last_tick") or {}).get("value") if isinstance(cursors.get("last_tick"), dict) else cursors.get("last_tick")
        if not last_raw:
            # 首见：只登记基准（对齐引擎「首 tick 不执行」语义）
            return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
        last = datetime.fromisoformat(str(last_raw))

        fires = due_fire_times(schedule, last, now, max_catchup_seconds=max_catchup)
        if not fires:
            if (now - last).total_seconds() > max_catchup:
                return PollResult(rebase=True, cursor_updates={"last_tick": now.isoformat()})
            return PollResult()

        drafts = [TriggerDraft.cron_tick(job, ft) for ft in fires]
        # 读位推进到最后一个触发点（保持网格稳定，不漂移）
        return PollResult(drafts=drafts, cursor_updates={"last_tick": fires[-1].isoformat()})


# ═══════════════════════════════════════════════════════════════
# 插件注册表
# ═══════════════════════════════════════════════════════════════


class SourceRegistry:
    """kind → Source 插件实例（进程内单例语义，启动时注册）。"""

    def __init__(self) -> None:
        self._plugins: dict[str, Source] = {}

    def register(self, plugin: Source) -> None:
        if not plugin.kind:
            raise ValueError("Source.kind must be set")
        if plugin.kind in self._plugins:
            raise ValueError(f"Duplicate source kind: {plugin.kind}")
        self._plugins[plugin.kind] = plugin

    def get(self, kind: str) -> Source | None:
        return self._plugins.get(kind)

    def kinds(self) -> list[str]:
        return sorted(self._plugins)


#: 全局注册表（bootstrap 时填入内置插件；测试可另建实例）
source_registry = SourceRegistry()


def register_builtin_sources(registry: SourceRegistry | None = None) -> SourceRegistry:
    """注册一期内置插件（cron_tick + bitable_poll）。"""
    target = registry if registry is not None else source_registry
    if target.get(CronTickSource.kind) is None:
        target.register(CronTickSource())
    from app.platform.superagent.bitable_poll import BitablePollSource

    if target.get(BitablePollSource.kind) is None:
        target.register(BitablePollSource())
    return target
