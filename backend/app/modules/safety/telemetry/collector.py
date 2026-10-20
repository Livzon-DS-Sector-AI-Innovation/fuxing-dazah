"""锅炉群消息采集编排（facilities-p2 票 03）。

单轮 = 拉新消息 → 逐条解析（模板优先/AI 兜底）→ 归属（编号优先/发送人
映射兜底）→ 幂等落快照 → 对新增快照跑规则判定（票 02 报警链）→ 游标推进。

留痕语义（DESIGN §3.1 未接入态口径）：
- 源群未配置 → no_source（不拉不落，如实跳过）；
- 配置了但拉不通 → 上抛 TelemetrySourceError（调度层记 failed）；
- 解析失败不丢弃：pending_review 行 + 连续失败轮计数告警（告警后重置）。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.telemetry.alerter import evaluate_and_alarm
from app.modules.safety.telemetry.parser import (
    ai_parse_image,
    ai_parse_text,
    effective_metric_set,
    extract_equipment_no,
    template_parse,
    validate_ai_result,
)
from app.modules.safety.telemetry.rules import RuleSpec
from app.modules.safety.telemetry.source import (
    GroupMessageSource,
    SourceMessage,
    TelemetrySourceAdapter,
    TelemetrySourceError,
    save_cursor,
    source_chat_id,
)
from app.modules.safety.telemetry.store import (
    excerpt_of,
    message_processed,
    upsert_snapshots,
)

logger = logging.getLogger(__name__)

# 连续失败轮告警阈值（轮内 ≥1 条 pending/解析异常即计失败轮；告警后重置）
ALERT_AFTER_FAILURE_ROUNDS = 3

# AI 解析函数签名：async (message, allowed) -> dict
AIParser = Callable[[SourceMessage, set[str]], Awaitable[dict]]

_CONSECUTIVE_FAILURES = 0


def load_sender_map() -> dict[str, str]:
    """发送人 → 默认设备编号（SAFETY_TELEMETRY_SENDER_MAP JSON）。"""
    import json

    from app.modules.safety.app_config.store import store

    raw = store.get_str("SAFETY_TELEMETRY_SENDER_MAP", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("SAFETY_TELEMETRY_SENDER_MAP 非法 JSON，忽略映射")
        return {}


def resolve_equipment(
    message: SourceMessage,
    readings: list[dict],
    *,
    sender_map_cfg: dict[str, str],
) -> str | None:
    """归属：readings 内编号 > 消息文本显式编号 > 发送人映射。"""
    for r in readings:
        if r.get("equipment_no"):
            return str(r["equipment_no"])
    if message.text:
        explicit = extract_equipment_no(message.text)
        if explicit:
            return explicit
    return sender_map_cfg.get(message.sender_id)


class CollectRoundResult:
    """单轮结果（留痕与断言依据）。"""

    def __init__(self) -> None:
        self.no_source = False
        self.fetched = 0
        self.inserted = 0
        self.pending = 0
        self.skipped = 0
        self.alarms = 0
        self.new_snapshots: list[Any] = []
        # 本轮末位消息 (message_id, create_time_epoch)——游标写入时机归调用方：
        # 必须在主事务 commit 之后（事务回滚时游标已推进 = 消息漏拉）
        self.cursor: tuple[str, int] | None = None

    def summary(self) -> str:
        if self.no_source:
            return "no_source（锅炉群未配置，跳过）"
        return (
            f"fetched={self.fetched} inserted={self.inserted} "
            f"pending={self.pending} skipped={self.skipped} alarms={self.alarms}"
        )


async def _default_ai(message: SourceMessage, allowed: set[str]) -> dict:
    """真实 AI 解析：文本消息走文本模型，图片/文件走视觉模型。"""
    if message.msg_type == "text" and message.text is not None:
        return await ai_parse_text(message.text)
    if message.image_key:
        path = await _download_resource(message)
        if path is None:
            raise RuntimeError(f"消息资源下载失败: {message.message_id}")
        return await ai_parse_image(path)
    return {"type": "chat"}


async def _download_resource(message: SourceMessage) -> str | None:
    """下载消息图片/文件到临时文件（vision 输入），返回本地路径。"""
    import os
    import tempfile

    from app.modules.safety.feishu.business_agent_bot_handler import (
        _download_message_file,
    )

    try:
        data = await _download_message_file(message.message_id, message.image_key or "")
    except Exception:
        logger.warning("遥测消息资源下载失败: %s", message.message_id, exc_info=True)
        return None
    os.makedirs("uploads/safety/telemetry", exist_ok=True)
    fd, path = tempfile.mkstemp(
        suffix=".png", prefix="tm_", dir="uploads/safety/telemetry"
    )
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


async def run_collect_round(
    db: AsyncSession,
    *,
    adapter: TelemetrySourceAdapter,
    ai_parser: AIParser | None = None,
    sender_map: dict[str, str] | None = None,
    rules: tuple[RuleSpec, ...] | None = None,
    equipment_info: dict[str, dict[str, Any]] | None = None,
    notifier: Any = None,
    chat_id: str | None = None,
    now: datetime | None = None,
) -> CollectRoundResult:
    """采集单轮（session 事务边界归调用方；测试传回滚 session）。

    chat_id 显式传入优先（测试/调度注入），缺省读 app_config。空 → no_source。
    """
    result = CollectRoundResult()
    resolved_chat = chat_id if chat_id is not None else source_chat_id()
    if not resolved_chat:
        result.no_source = True
        return result

    from app.modules.safety.telemetry.rules import effective_rules as _eff

    effective_ruleset = rules if rules is not None else _eff(None)
    allowed = {r.metric for r in effective_ruleset} | effective_metric_set()
    smap = sender_map if sender_map is not None else load_sender_map()
    info = equipment_info or {}
    ai = ai_parser or _default_ai

    messages = await adapter.fetch_new_messages()
    result.fetched = len(messages)
    excerpt_by_mid: dict[str, str | None] = {}
    pending_mids: list[str] = []
    round_failed = False

    for message in messages:
        if await message_processed(db, message.message_id):
            continue
        excerpt = excerpt_of(message.text)
        excerpt_by_mid[message.message_id] = excerpt

        try:
            readings: list[dict] | None = None
            parse_method = "template"
            if message.msg_type == "text" and message.text is not None:
                readings = template_parse(message.text, allowed=allowed)
            if readings is None:
                parse_method = "ai"
                readings = validate_ai_result(
                    await ai(message, allowed),
                    allowed=allowed,
                    allowed_equipment=set(info) or None,
                )
                if readings == []:
                    result.skipped += 1
                    continue

            equipment = resolve_equipment(message, readings or [], sender_map_cfg=smap)
            if equipment is None and readings:
                # 数值可信但归属缺失：带 metric/value 落 pending（人工确认设备）
                equipment = None
                new = await upsert_snapshots(
                    db,
                    [
                        {
                            "equipment_no": None,
                            "metric": r["metric"],
                            "value": r["value"],
                            "unit": r.get("unit"),
                            "recorded_at": message.create_time,
                        }
                        for r in readings
                    ],
                    parse_method=parse_method,
                    parse_status="pending_review",
                    raw_message_id=message.message_id,
                    raw_excerpt=excerpt,
                )
                result.pending += len(new)
                result.new_snapshots.extend(new)
                round_failed = True
                continue
            if not readings:
                # 模板/AI 都没给出读数且未判闲聊 → pending（原文留痕）
                new = await upsert_snapshots(
                    db,
                    [{
                        "equipment_no": None, "metric": None, "value": None,
                        "unit": None, "recorded_at": message.create_time,
                    }],
                    parse_method=parse_method,
                    parse_status="pending_review",
                    raw_message_id=message.message_id,
                    raw_excerpt=excerpt,
                )
                result.pending += len(new)
                result.new_snapshots.extend(new)
                round_failed = True
                continue

            new = await upsert_snapshots(
                db,
                [
                    {
                        "equipment_no": equipment,
                        "metric": r["metric"],
                        "value": r["value"],
                        "unit": r.get("unit"),
                        "recorded_at": message.create_time,
                    }
                    for r in readings
                ],
                parse_method=parse_method,
                raw_message_id=message.message_id,
                raw_excerpt=excerpt,
            )
            result.inserted += len(new)
            result.new_snapshots.extend(new)
        except Exception:
            # AI 调用异常等：整条 pending 留痕不丢弃
            round_failed = True
            logger.warning(
                "遥测消息处理异常（落 pending）: %s", message.message_id, exc_info=True
            )
            new = await upsert_snapshots(
                db,
                [{
                    "equipment_no": None, "metric": None, "value": None,
                    "unit": None, "recorded_at": message.create_time,
                }],
                parse_method="ai",
                parse_status="pending_review",
                raw_message_id=message.message_id,
                raw_excerpt=excerpt_by_mid.get(message.message_id),
            )
            result.pending += len(new)
            result.new_snapshots.extend(new)

    # 游标只携带不落库：写库时机=调用方事务 commit 之后（防事务回滚后
    # 游标越位漏拉；commit 后崩溃则游标未进而重拉，幂等防重兜底）
    if messages:
        last = messages[-1]
        result.cursor = (last.message_id, int(last.create_time.timestamp()))

    # 当轮即判即发（票 02 链）：类别缺失的设备按锅炉兜底（采集源即锅炉群）
    alarm_info = {
        eq: {"category": (meta or {}).get("category") or "锅炉",
             "department": (meta or {}).get("department")}
        for eq, meta in info.items()
    }
    alarms = await evaluate_and_alarm(
        db, result.new_snapshots, rules=effective_ruleset,
        now=now, notifier=notifier, equipment_info=alarm_info,
    )
    result.alarms = len(alarms)

    await _count_failures(round_failed, resolved_chat)
    return result


async def _count_failures(round_failed: bool, chat_id: str) -> None:
    """连续失败轮计数；达阈值告警一次并重置（防每轮轰炸）。"""
    global _CONSECUTIVE_FAILURES
    if not round_failed:
        _CONSECUTIVE_FAILURES = 0
        return
    _CONSECUTIVE_FAILURES += 1
    if _CONSECUTIVE_FAILURES < ALERT_AFTER_FAILURE_ROUNDS:
        return
    _CONSECUTIVE_FAILURES = 0
    try:
        from app.modules.safety.feishu.notification import send_group_card
        from app.modules.safety.telemetry.notify import alarm_chat_id

        await send_group_card(
            alarm_chat_id(),
            "遥测采集连续解析失败",
            f"锅炉群消息采集已连续 {ALERT_AFTER_FAILURE_ROUNDS} 轮出现解析失败"
            "（已自动落 pending_review 待补录，数据不丢）。请到「设备设施管理 →"
            " 特种设备 → 监控 → 待补录」处理，或检查抄表消息格式。",
            header_template="orange",
        )
    except Exception:
        logger.warning("解析失败计数告警发送失败（忽略）", exc_info=True)


def build_group_source(chat_id: str) -> GroupMessageSource:
    """组装真实群消息源（调度入口用）。"""
    return GroupMessageSource(chat_id)


# ── 调度入口（interval 任务单轮；outcome 语义对齐一期 no_source 口径）──


def poll_enabled() -> bool:
    """采集总开关（SAFETY_TELEMETRY_POLL_ENABLED，restart_required）。"""
    from app.modules.safety.app_config.store import store

    return store.get_bool("SAFETY_TELEMETRY_POLL_ENABLED", False)


async def load_monitored_equipment_info() -> dict[str, dict[str, Any]]:
    """特种设备台账 monitored=是 行 → {编号: {category, department}}。

    复用一期 reader 直读链；连接未登记返回空 dict（collector 内类别按
    「锅炉」兜底——采集源即锅炉群，事实即类别证据），不抛错不阻塞采集。
    """
    try:
        from app.modules.safety.facilities.ledger import BIZ_SPECIAL
        from app.modules.safety.facilities import reader as fac_reader

        if not fac_reader.connection_configured(BIZ_SPECIAL):
            return {}
        views = await fac_reader.open_reader().fetch_ledger(BIZ_SPECIAL, strict=True)
        return {
            v.equipment_no: {"category": v.category, "department": v.department}
            for v in views
            if v.equipment_no and v.monitor_flag
        }
    except Exception:
        logger.warning("monitored 设备清单读取失败（本轮按锅炉兜底）", exc_info=True)
        return {}


async def run_scheduled_round() -> str:
    """调度单轮（真实 adapter + 真实 AI + 真实通知），返回 outcome。

    - 源群未配置 → "no_source"（不拉，如实跳过）；
    - 拉取失败 → TelemetrySourceError 上抛（调度层记 failed）；
    - 正常 → "success"（含 pending/skipped 明细在日志）。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.app_config.store import store as _store
    from app.modules.safety.telemetry.notify import TelemetryAlarmNotifier
    from app.modules.safety.telemetry.rules import effective_rules as _eff

    chat = source_chat_id()
    if not chat:
        return "no_source"
    info = await load_monitored_equipment_info()
    notifier = TelemetryAlarmNotifier(equipment_info=info)
    rules = _eff(_store.get_str("SAFETY_TELEMETRY_RULES") or None)
    async with async_session_factory() as session:
        result = await run_collect_round(
            session,
            adapter=build_group_source(chat),
            rules=rules,
            equipment_info=info,
            notifier=notifier,
            chat_id=chat,
        )
        await session.commit()
    # 游标在主事务提交后才推进（回滚不越位；commit 后崩溃重拉由幂等兜底）
    if result.cursor is not None:
        await save_cursor(*result.cursor)
    logger.info("锅炉群采集单轮完成: %s", result.summary())
    return "no_source" if result.no_source else "success"


class RunLogGate:
    """运行留痕节流（5 分钟一轮不刷屏任务运行中心）。

    写行条件：outcome 状态变化，或换日首行（心跳）；同状态同日只写一次。
    no_source/success/failed 同权处理——结果变化即值得留痕。
    """

    def __init__(self) -> None:
        self._state: dict[str, tuple[str, date]] = {}

    def should_log(self, job_name: str, outcome: str, today: date) -> bool:
        prev = self._state.get(job_name)
        if prev is None or prev[0] != outcome or prev[1] != today:
            self._state[job_name] = (outcome, today)
            return True
        return False
