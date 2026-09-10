"""安全模块定时任务引擎。

在 FastAPI lifespan 中启动，运行 tick-based 事件循环。

当前任务:
- 督办等级计算 (每日 07:30, 已启用): 拉取督办等级未关闭记录 → 规则计算 → 更新回填
- 持证到期预警 (每日 08:00, 已启用): 扫描 person_certificates → 推送本人/部门负责人/安管人员
- 督办通报 (周四 08:30, 群聊卡片, 已启用)
- 督办通知 (周四 08:30, 个人 DM, 已启用)
- 特殊作业日报 (每日 08:00, 已启用)
- 特殊作业日报17点 (每日 17:00, 已启用)
- Agent 手动触发: generate_supervision_bulletin 工具

失败重试/补发机制:
- 任务执行失败不会"死标记"当天完成，而是记录 status=failed 进入自动重试
- 补发窗口内每 RETRY_INTERVAL 重试一次，网络/服务器恢复后自动补发
- 连续失败达 ALERT_AFTER_FAILURES 次后向管理员发飞书告警（当天只发一次）
- 状态持久化到 PostgreSQL，重启后从 DB 恢复：成功不重发、失败继续补发
"""

import asyncio
import logging
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Stop flag, set during app shutdown
stop_scheduled_task_flag = asyncio.Event()

# Tick interval in seconds
TICK_INTERVAL = 30

# ── 失败重试/补发配置 ──
# 失败后重试间隔（秒）：网络/服务器恢复后最多 10 分钟内自动补发
RETRY_INTERVAL = 10 * 60
# 连续失败次数达到该值后发送失败告警（10 分钟 × 3 ≈ 30 分钟未恢复即告警）
ALERT_AFTER_FAILURES = 3
# 告警接收人（许康福）
ALERT_NOTIFY_OPEN_ID = "ou_495039d6335d347b07ff92ad982b3b4e"
ALERT_NOTIFY_NAME = "许康福"

# ── 并行调度配置 ──
# 每个任务以独立 asyncio task 执行，互不阻塞（8 点日报不会被 7:30 慢任务堵住）
# 防重入：同一任务同一时刻只允许一个实例（per-job 锁）
# 超时：任务超过 TASK_TIMEOUT 强制取消，状态保持 failed 由失败重试机制接管
# 2026-09-02 调大：17:00 五个 AI 日报任务并行，各自对每条记录做 RAG 检索 + AI 分析，
# 并发拖慢导致单任务 20+ 分钟（曾被 20min 超时取消靠重试才完成）；45min 给足余量。
TASK_TIMEOUT = 45 * 60  # 单个任务最长执行时间（秒）

_task_locks: dict[str, asyncio.Lock] = {}


# 消防报警日报「群聊→私发」串行信号：当日一把，群任务成功置位
_fire_group_done_events: dict[date, asyncio.Event] = {}


def _fire_group_event(today: date) -> asyncio.Event:
    """返回当日消防报警日报群推送完成信号（无则新建）。"""
    ev = _fire_group_done_events.get(today)
    if ev is None:
        ev = asyncio.Event()
        _fire_group_done_events[today] = ev
    return ev


async def _fire_group_report_done_today(today: date | None = None) -> bool:
    """检查群日报任务当天是否已成功落库（调度器重启后内存信号丢失时兜底）。

    scheduler_job_runs 中「消防报警日报」status=success 且 fired_date=今天 → True。
    DB 不可用/查不到 → False（仍走内存信号等待，行为与改动前一致）。
    """
    today = today or date.today()
    try:
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.modules.safety.models import SchedulerJobRun

        async with async_session_factory() as session:
            row = await session.scalar(
                select(SchedulerJobRun).where(
                    SchedulerJobRun.job_name == "消防报警日报",
                    SchedulerJobRun.is_deleted == False,  # noqa: E712
                )
            )
            return bool(
                row is not None
                and row.fired_date == today
                and row.status == "success"
            )
    except Exception:
        logger.debug("检查群日报落库状态失败", exc_info=True)
        return False


def _get_task_lock(job_name: str) -> asyncio.Lock:
    """每个任务一把锁，防止同一任务并发执行两个实例。"""
    if job_name not in _task_locks:
        _task_locks[job_name] = asyncio.Lock()
    return _task_locks[job_name]


async def _load_effective_jobs() -> list[dict[str, Any]]:
    """加载调度任务（代码默认 + scheduler_task_configs DB 覆写）。

    返回的 job dict 与 SCHEDULED_JOBS 字段兼容（name/hour/minute/dow/mode/
    description/retry_until_*/enabled/target_chat_id/target_chat_name）。
    """
    from app.modules.safety.service.scheduler_config import (
        load_scheduled_jobs_with_overrides,
    )

    tasks = await load_scheduled_jobs_with_overrides()
    out: list[dict[str, Any]] = []
    for t in tasks:
        job: dict[str, Any] = {
            "name": t["job_name"],
            "hour": t.get("hour"),
            "minute": t.get("minute"),
            "dow": t.get("dow"),
            "mode": t.get("mode"),
            "description": t.get("description"),
            "retry_until_hour": t.get("retry_until_hour"),
            "retry_until_minute": t.get("retry_until_minute"),
            "enabled": t.get("enabled", True),
            "target_chat_id": t.get("target_chat_id"),
            "target_chat_name": t.get("target_chat_name"),
        }
        out.append(job)
    return out

# ── 调度任务配置 ──

SCHEDULED_JOBS: list[dict[str, Any]] = [
    # ── 隐患督办通报（每周四 08:30，直读多维表格）──
    {
        "name": "隐患督办通报",
        "hour": 8, "minute": 30, "dow": 3,  # 周四
        "description": "直读多维表格的未关闭隐患，按部门分组推送督办通报到群聊",
    },
    # ── 未更新进展催办（每周三 10:00，直读多维表格 + Redis 跟踪进展变化）──
    {
        "name": "未更新进展催办",
        "hour": 10, "minute": 0, "dow": 2,  # 周三
        "enabled": True,
        # 发送对象为动态名单：每次执行按当前命中的隐患现算「责任人 + 分管安全员」，
        # 不保留固定收件人（target_chat_id 对本任务仅作展示，不参与发送）。
        "target_type": "dynamic",
        "target_chat_id": "ou_495039d6335d347b07ff92ad982b3b4e",
        "retry_until_hour": 18, "retry_until_minute": 0,
        "description": "未更新进展隐患催办卡片（每周三 10:00，直读多维表格，一卡一隐患，"
                       "动态名单：责任人 + 分管安全员，卡片内可提交进展）",
    },
    # ── 已下线（2026-09-09 改造）──
    #   · 隐患差异同步：隐患记录以多维表格为唯一数据源，不再做 DB 差异对账
    #   · 督办等级计算：并入 hazard_direct 轮询（每 5 分钟，只回写多维表格）
    #   · 隐患督办通知：功能删除
    #   · 隐患分析报告：功能删除
    # ── 特殊作业日报 ──
    {
        "name": "特殊作业日报",
        "hour": 8, "minute": 0,
        "mode": "today",
        # 补发窗口：16:30 截止（17 点日报会覆盖当天信息，避免重复轰炸群聊）
        "retry_until_hour": 16, "retry_until_minute": 30,
        "description": "当日特殊作业分析+推送（失败自动重试，补发窗口至 16:30）",
    },
    {
        "name": "特殊作业日报17点",
        "hour": 17, "minute": 0,
        "mode": "afternoon",
        # 补发窗口：23:30 截止
        "retry_until_hour": 23, "retry_until_minute": 30,
        "description": "17点特殊作业日报(含新增计划外作业对比总结)+推送（失败自动重试，补发窗口至 23:30）",
    },
    # ── 作业票审核（每日 17:00）──
    {
        "name": "作业票审核",
        "hour": 17, "minute": 0,
        # 补发窗口：当日 23:30 截止（失败自动重试）
        "retry_until_hour": 23, "retry_until_minute": 30,
        "description": "当日标准8类作业票按4条规则审核+生成审核日报+推送特殊作业自动分配群",
    },
    # ── 消防报警日报（每日 17:00）──
    {
        "name": "消防报警日报",
        "hour": 17, "minute": 0,
        # 补发窗口：当日 23:30 截止（失败自动重试）
        "retry_until_hour": 23, "retry_until_minute": 30,
        "description": "当日消防报警分析日报（按部门分组明细 + AI 原因分析/整改建议 + @部门负责人），推送安全AI创新交流群",
    },
    # ── 消防报警日报私发（每日 17:00）──
    {
        "name": "消防报警日报私发",
        "hour": 17, "minute": 0,
        # 补发窗口：当日 23:30 截止（失败自动重试）
        "retry_until_hour": 23, "retry_until_minute": 30,
        "target_type": "person",  # 私发个人（接收人为动态名单：涉及部门负责人+分管安全员）
        "description": "当日报警一卡一条 DM 私发给涉及部门的部门负责人+分管安全员（发送对象为动态名单，开关 SAFETY_FIRE_ALARM_DAILY_DM_ENABLED）",
    },
    # ── 中控报警日报（每日 17:00）──
    {
        "name": "中控报警日报",
        "hour": 17, "minute": 0,
        "retry_until_hour": 23, "retry_until_minute": 30,
        "description": "当日中控报警分析日报（车间/岗位/报警类型/异常模式统计 + AI 汇总分析），推送安全AI创新交流群",
    },
    # ── 持证到期预警（每日 08:00，补发窗口 12:00）──
    {
        "name": "持证到期预警",
        "hour": 8, "minute": 0,
        "retry_until_hour": 12, "retry_until_minute": 0,
        "description": "扫描 person_certificates → 计算预警 → 推送本人/部门负责人/安管人员",
    },
    # 次日预警已取消，改为通过 Agent 对话手动触发
    # {
    #     "name": "特殊作业次日预警",
    #     "hour": 19, "minute": 0,
    #     "mode": "tomorrow",
    #     "description": "次日计划作业风险预警",
    # },
    # ── 危化品库存周报（每周五 15:30，发送由 env 群聊配置控制）──
    {
        "name": "危化品库存周报",
        "hour": 15, "minute": 30, "dow": 4,  # 周五
        "retry_until_hour": 18, "retry_until_minute": 0,
        "description": "危化品库存：落快照→周环比→AI 小结→（配了群聊才）发送到安全AI创新交流群",
    },
    # ── 危化品库存日报（每天 19:30，拉取当日 Excel → 更新多维表 → 推送安全AI创新交流群）──
    {
        "name": "危化品库存日报",
        "hour": 19, "minute": 30,
        "retry_until_hour": 23, "retry_until_minute": 30,
        "description": "拉取危险品日报群当日 Excel → 更新多维表 → 重算风险 → 推送安全AI创新交流群（超量+昨日环比分析日报）",
    },
]

# ── 触发状态持久化（PostgreSQL）──
# 背景：后端重启会清空进程内状态，调度器会把当天已跑过的任务补跑一遍
#（如特殊作业日报重复推群通知）。状态写入 safety.scheduler_job_runs 持久化，
# 重启后从数据库恢复，避免补跑。
# 设计：进程内 _state_cache 作为首层缓存（避免每次 tick 都查库），miss 时再查库；
#       status=success 当天不重跑（重启去重），status=failed 补发窗口内自动重试；
#       数据库不可用时退化为纯内存去重，行为与改动前一致（fail-open，宁重复不错过）。

_state_cache: dict[str, dict[str, Any]] = {}


async def _load_state(job_name: str) -> dict[str, Any] | None:
    """读取任务状态（内存 → 数据库）。无记录返回 None。"""
    if job_name in _state_cache:
        return _state_cache[job_name]
    try:
        from sqlalchemy import select

        from app.core.database import async_session_factory
        from app.modules.safety.models import SchedulerJobRun

        async with async_session_factory() as session:
            row = await session.scalar(
                select(SchedulerJobRun).where(
                    SchedulerJobRun.job_name == job_name,
                    SchedulerJobRun.is_deleted == False,  # noqa: E712
                )
            )
            if row is not None:
                state = {
                    "job_name": row.job_name,
                    "fired_date": row.fired_date,
                    "status": row.status,
                    "last_attempt_at": row.last_attempt_at,
                    "attempt_count": row.attempt_count,
                    "alerted": row.alerted,
                }
                _state_cache[job_name] = state
                return state
    except Exception:
        logger.debug(
            "调度器读取数据库失败，退化为内存去重: %s", job_name, exc_info=True
        )
    return None


async def _save_state(job_name: str, state: dict[str, Any]) -> None:
    """更新任务状态（内存 + 数据库 upsert）。"""
    _state_cache[job_name] = state
    try:
        from sqlalchemy.dialects.postgresql import insert

        from app.core.database import async_session_factory
        from app.modules.safety.models import SchedulerJobRun

        async with async_session_factory() as session:
            stmt = insert(SchedulerJobRun).values(
                job_name=job_name,
                fired_date=state["fired_date"],
                status=state["status"],
                last_attempt_at=state["last_attempt_at"],
                attempt_count=state["attempt_count"],
                alerted=state["alerted"],
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["job_name"],
                set_={
                    "fired_date": state["fired_date"],
                    "status": state["status"],
                    "last_attempt_at": state["last_attempt_at"],
                    "attempt_count": state["attempt_count"],
                    "alerted": state["alerted"],
                },
            )
            await session.execute(stmt)
            await session.commit()
    except Exception:
        logger.debug(
            "调度器写入数据库失败，仅内存去重: %s", job_name, exc_info=True
        )


def _retry_until(job: dict[str, Any]) -> int:
    """补发窗口截止分钟（默认当天 23:59，不限制）。

    DB 覆写合并（load_scheduled_jobs_with_overrides）对未配置补发窗口的任务
    会把 retry_until_hour/minute 置为 None（键存在），这里按缺省处理。
    """
    hour = job.get("retry_until_hour") or 23
    minute = job.get("retry_until_minute") or 59
    return int(hour * 60 + minute)


async def _should_run(job: dict[str, Any], today: date, now: datetime | None = None) -> bool:
    """判断任务本次 tick 是否应执行。

    - 未到计划时间 → False
    - 当天已成功（status=success 且 fired_date=今天）→ False（重启后不重复发）
    - 从未触发 / 新的一天 → 到点即 True
    - 当天失败 → 距上次尝试 ≥ RETRY_INTERVAL 且仍在补发窗口内 → True（自动补发）
    """
    if job.get("enabled") is False:
        return False  # 已停用任务不触发
    now = now or datetime.now()
    scheduled_minutes = job["hour"] * 60 + job["minute"]
    current_minutes = now.hour * 60 + now.minute
    if current_minutes < scheduled_minutes:
        return False

    state = await _load_state(job["name"])
    if state is None:
        return True  # 从未触发过（首次）

    if state["fired_date"] != today:
        return True  # 新的一天（旧成功/旧失败都视为全新开始）

    if state["status"] == "success":
        return False  # 当天已成功，不重发

    # 当天失败 → 退避重试 + 补发窗口（last_attempt_at 为 UTC aware，与 now(UTC) 比较）
    last_attempt = state["last_attempt_at"]
    if last_attempt is not None:
        elapsed = (datetime.now(UTC) - last_attempt).total_seconds()
        if elapsed < RETRY_INTERVAL:
            return False
    return current_minutes <= _retry_until(job)


async def _maybe_send_failure_alert(job_name: str, attempt_count: int) -> None:
    """连续失败达阈值后向管理员发飞书告警（当天只发一次，失败不阻塞调度循环）。"""
    state = await _load_state(job_name)
    if state is None or state.get("alerted"):
        return
    try:
        from app.modules.safety.feishu.notification import send_user_card

        ok = await send_user_card(
            open_id=ALERT_NOTIFY_OPEN_ID,
            title="⚠️ 定时任务推送失败告警",
            content=(
                f"**{job_name}** 连续失败 **{attempt_count}** 次\n"
                f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"已进入自动重试：网络/服务器恢复后将在补发窗口内自动重试补发，无需人工操作。\n"
                f"若长时间未恢复，请检查服务器网络与服务状态。"
            ),
        )
        if ok:
            await _save_state(job_name, {**state, "alerted": True})
            logger.info("已发送失败告警: %s", job_name)
        else:
            logger.warning("失败告警发送失败(返回False): %s", job_name)
    except Exception:
        logger.exception("失败告警发送异常: %s", job_name)


async def _run_scheduled_job(job: dict[str, Any]) -> None:
    """执行一个定时任务，按任务名分发。

    时序：先记录 failed 状态（防 30s tick 内重复启动）→ 执行 → 成功改 success；
    失败保留 failed，由后续 tick 在补发窗口内自动重试，达阈值发告警给管理员。
    """
    job_name = job["name"]
    today = date.today()
    now = datetime.now(UTC)

    # 星期过滤（dow=0周一, ..., 6周日，未配置则每天触发）
    required_dow = job.get("dow")
    if required_dow is not None and today.weekday() != required_dow:
        return

    if not await _should_run(job, today):
        return

    # 先标记 failed，防止 30s tick 内重复启动；成功后再改 success
    state = await _load_state(job_name)
    new_day = state is None or state["fired_date"] != today
    prev = state or {}
    attempt_count = (
        1 if new_day or prev.get("status") != "failed"
        else int(prev.get("attempt_count", 0)) + 1
    )
    await _save_state(job_name, {
        "job_name": job_name,
        "fired_date": today,
        "status": "failed",
        "last_attempt_at": now,
        "attempt_count": attempt_count,
        "alerted": False if new_day else bool(prev.get("alerted", False)),
    })
    logger.info("定时任务触发: %s (第 %d 次尝试)", job_name, attempt_count)
    chat_id = job.get("target_chat_id")
    try:
        if job_name == "隐患督办通报":
            await _run_supervision_bulletin(chat_id=chat_id)
        elif job_name == "未更新进展催办":
            await _run_progress_dunning(chat_id=chat_id)
        elif job_name == "作业票审核":
            await _run_work_ticket_review(today, chat_id=chat_id)
        elif job_name == "消防报警日报":
            await _run_fire_alarm_daily_report(chat_id=chat_id)
        elif job_name == "消防报警日报私发":
            await _run_fire_alarm_daily_dm()
        elif job_name == "中控报警日报":
            await _run_central_alarm_daily_report(chat_id=chat_id)
        elif job_name == "持证到期预警":
            await _run_cert_warning_notification()
        elif job_name == "危化品库存周报":
            await _run_chemical_inventory_weekly(chat_id=chat_id)
        elif job_name == "危化品库存日报":
            await _run_chemical_inventory_daily(chat_id=chat_id)
        elif "mode" in job:
            await _run_special_op_daily_report(job, today, chat_id=chat_id)
        else:
            logger.warning("未知定时任务: %s", job_name)
        await _save_state(job_name, {
            "job_name": job_name,
            "fired_date": today,
            "status": "success",
            "last_attempt_at": now,
            "attempt_count": 0,
            "alerted": False,
        })
        logger.info("定时任务完成: %s", job_name)
    except Exception:
        logger.exception("定时任务执行失败: %s", job_name)
        if attempt_count >= ALERT_AFTER_FAILURES:
            await _maybe_send_failure_alert(job_name, attempt_count)


async def _run_supervision_bulletin(chat_id: str | None = None) -> None:
    """周四 08:30 督办通报（群聊卡片，直读多维表格）。"""
    from app.modules.safety.service.hazard_direct.bulletin import send_bulletin

    stats = await send_bulletin(chat_id)
    if stats.get("sent"):
        logger.info("督办通报已发送: %s", stats)
    else:
        logger.warning("督办通报发送失败: %s", stats)


async def _run_progress_dunning(chat_id: str | None = None) -> None:
    """未更新进展催办（周三 10:00，直读多维表格 + Redis 跟踪进展变化）。

    发送对象**始终动态**：每次执行时按当前命中的隐患现算收件人——
    每条隐患私发给「责任人 + 该部门分管安全员」（名单来自 DEPT_CONFIG /
    IdentityResolver，不保留固定收件人）。调度配置里的 target_chat_id 对本任务无效。
    """
    from app.modules.safety.service.hazard_direct.progress_dunning import (
        send_progress_dunning_dynamic,
    )

    if chat_id:
        logger.info(
            "未更新进展催办使用动态名单（责任人 + 分管安全员），"
            "忽略调度配置的固定收件人 %s",
            chat_id,
        )
    stats = await send_progress_dunning_dynamic()
    logger.info(
        "未更新进展催办完成: sent=%s skipped=%s errors=%s marked=%s recipients=%s",
        stats.get("sent"), stats.get("skipped"), stats.get("errors"),
        stats.get("marked"), stats.get("recipients", "-"),
    )


async def _run_special_op_daily_report(
    job: dict[str, Any], today: date, chat_id: str | None = None,
) -> None:
    """执行特殊作业日报任务（兼容旧接口）。"""
    from app.core.database import async_session_factory
    from app.modules.safety.service.special_operation_daily_report import (
        SpecialOperationDailyReportService,
    )

    async with async_session_factory() as session:
        service = SpecialOperationDailyReportService(session)
        if job.get("mode") == "today":
            # 08:00：每日唯一一次全量对账。删除记录、旧记录编辑只有全量能发现，
            # 增量（发起时间过滤）覆盖不了；这是该表当天的兜底基线。
            synced = await service.sync_from_bitable()
            if synced > 0:
                await session.commit()
            logger.info("特殊作业全量对账完成: synced=%s", synced)
        else:
            # 17点：改用增量同步（2026-09-03）。白天新增由 WS 事件实时同步，
            # 增量按「发起时间 > 本地水位-24h」补漏，秒级完成；失败自动退化为
            # 全量。此前每次全量拉 2033 条逐条 upsert 纯属浪费。
            inc = await service.check_and_sync_incremental()
            logger.info(
                "特殊作业增量同步: status=%s recent=%s pulled=%s elapsed=%sms",
                inc.get("status"), inc.get("bitable_recent"),
                inc.get("pulled"), inc.get("elapsed_ms"),
            )

        target_chats = [chat_id] if chat_id else []  # 无目标 → 不推送（统一来源：DB 配置）
        result = await service.generate_and_push(
            target_date=today, mode=job["mode"], target_chats=target_chats,
        )
        # 2026-09-03：不再在此处 commit。generate_and_push 已在推送前提交
        # （收口长事务），推送成功后无任何待提交内容——推送后 commit 一旦
        # 因连接死亡失败，任务会被误标 failed 触发重试造成重复推送。
        logger.info(
            "  日报完成: total=%d high=%d medium=%d low=%d excluded=%d push_ok=%d",
            result.total, result.high_risk, result.medium_risk,
            result.low_risk, result.excluded,
            sum(1 for p in result.push_results if p.get("success")),
        )


async def _run_work_ticket_review(today: date, chat_id: str | None = None) -> None:
    """作业票审核定时任务（每日 17:00）：拉取当日标准8类作业票 → 规则审核 → 落库 → 推送群。

    复用 WorkTicketReviewService.run_review(date, push=True)；run_review 内部已 commit
    （成功/失败均落库 status），失败由调度器补发窗口重试机制接管。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.workticket_review.service import WorkTicketReviewService

    async with async_session_factory() as session:
        service = WorkTicketReviewService(session, chat_id=chat_id)
        result = await service.run_review(today, push=True)
        logger.info(
            "  作业票审核完成: date=%s total=%d reviewed=%d violation=%d compliant=%d data_insufficient=%d push=%s",
            result.get("date"), result.get("total"), result.get("reviewed"),
            result.get("violation_count"), result.get("compliant_count"),
            result.get("data_insufficient"),
            (result.get("push_result") or {}).get("success"),
        )


async def _run_fire_alarm_daily_report(chat_id: str | None = None) -> None:
    """消防报警日报定时任务（每日 17:00）：同步 → 生成日报（默认今天） → 推送群聊。

    复用 scheduler-ready 入口 run_daily_fire_alarm_analysis（独立 session、channel=system、
    push=True），失败自动由调度器的补发窗口重试机制接管。
    成功后置位当日信号，供「消防报警日报私发」等待（先群后私）。
    """
    from app.modules.safety.service.fire_alarm.service import (
        run_daily_fire_alarm_analysis,
    )

    try:
        result = await run_daily_fire_alarm_analysis(chat_id=chat_id)
        if result is None:
            logger.warning("消防报警日报生成失败（入口返回 None）")
            return
        pushed = sum(1 for p in result.push_results if p.get("success"))
        logger.info(
            "  消防报警日报完成: total=%d pushed=%d",
            result.total, pushed,
        )
        _fire_group_event(date.today()).set()
    except Exception:
        logger.exception("消防报警日报定时任务执行失败")


async def _run_fire_alarm_daily_dm() -> None:
    """消防报警日报私发定时任务（每日 17:00）：同步 → 生成（复用/补齐 AI 分析） → 一卡一条 DM。

    复用 scheduler-ready 入口 run_daily_fire_alarm_dm（独立 session、channel=system），
    开关 SAFETY_FIRE_ALARM_DAILY_DM_ENABLED 关闭时入口直接跳过；
    发送对象为动态名单（涉及部门负责人 + 分管安全员），不占 chat_id 配置。
    失败自动由调度器的补发窗口重试机制接管。
    """
    from app.modules.safety.service.fire_alarm.service import (
        run_daily_fire_alarm_dm,
    )

    # 先等群日报推送完成（当日一把信号，30 分钟上限），再一卡一条私发
    # 2026-09-02：群日报已成功落库（scheduler_job_runs success）则跳过等待，避免
    # 重启后内存信号丢失导致干等 30 分钟；群未成功仍走内存信号。
    group_ok = await _fire_group_report_done_today()
    if not group_ok:
        try:
            await asyncio.wait_for(
                _fire_group_event(date.today()).wait(), timeout=30 * 60,
            )
            group_ok = True  # 信号置位 = 群任务刚完成（含同步兜底），数据是新鲜的
        except TimeoutError:
            logger.warning("消防报警日报群推送未在 30 分钟内完成，私发任务直接继续")

    # 2026-09-03：群任务成功 = 其同步兜底刚跑过 → 私发跳过自己的全量同步
    #（此前紧跟群任务再拉一遍 1307 条，纯重复）；群任务失败/未跑时才自行同步兜底。
    try:
        stats = await run_daily_fire_alarm_dm(skip_sync=group_ok)
        if stats is None:
            logger.info("消防报警日报私发跳过（开关未启用或失败）")
            return
        logger.info(
            "  消防报警日报私发完成: sent=%d skipped=%d errors=%d unresolved=%d",
            stats.get("sent", 0), stats.get("skipped", 0),
            stats.get("errors", 0), stats.get("unresolved", 0),
        )
    except Exception:
        logger.exception("消防报警日报私发定时任务执行失败")


async def _run_central_alarm_daily_report(chat_id: str | None = None) -> None:
    """中控报警日报定时任务（每日 17:00）：同步 → 生成日报（默认今天） → 推送群聊。

    复用 scheduler-ready 入口 run_daily_central_alarm_analysis（独立 session、
    channel=system、push=True），失败自动由调度器的补发窗口重试机制接管。
    """
    from app.modules.safety.service.central_alarm.service import (
        run_daily_central_alarm_analysis,
    )

    try:
        result = await run_daily_central_alarm_analysis(chat_id=chat_id)
        if result is None:
            logger.warning("中控报警日报生成失败（入口返回 None）")
            return
        pushed = sum(1 for p in result.push_results if p.get("success"))
        logger.info("  中控报警日报完成: total=%d pushed=%d", result.total, pushed)
    except Exception:
        logger.exception("中控报警日报定时任务执行失败")


async def _run_cert_warning_notification() -> None:
    """每日 08:00：持证到期预警推送。

    流程：
      1. 独立 session（async_session_factory，避免污染调度器主 session）
      2. 拉全量候选 + CertWarningEngine 派生，过滤 active_levels（>90 normal 不打扰）
      3. 本人收个人卡片（IdentityResolver.resolve_by_name，按 person_name + department_hint）
      4. 部门负责人收汇总卡片（IdentityResolver.resolve_department_leader）
      5. 安管人员（许康福，复用 ALERT_NOTIFY_OPEN_ID）收全量汇总卡片
      6. 复用 send_user_card()

    纯规则计算，不调 AI。身份解析失败打 warning，不阻塞其他人推送。
    """
    from app.core.database import async_session_factory
    from app.modules.safety.feishu import IdentityResolver
    from app.modules.safety.feishu.notification import send_user_card
    from app.modules.safety.service.cert_warning import (
        CertWarningEngine,
        CertWarningService,
    )

    # 触发等级集合（spec US-2：>90 不打扰）
    active_levels = {"early_notice", "to_schedule", "key_warning", "urgent", "overdue"}

    async with async_session_factory() as session:
        service = CertWarningService(session)
        resolver = IdentityResolver(session)

        # 拉全量候选 + 引擎派生（定时任务需全量，不分页）
        rows = await service.repo.get_all_active()
        today = date.today()
        warnings: list[tuple[Any, Any]] = []
        for r in rows:
            res = CertWarningEngine.calculate(r, today)
            if res.status in active_levels:
                warnings.append((r, res))

        # ① 本人个人卡片
        for r, res in warnings:
            person = await resolver.resolve_by_name(
                r.person_name, department_hint=r.department,
            )
            if person and person.open_id:
                await send_user_card(
                    open_id=person.open_id,
                    title="持证到期提醒",
                    content=_build_personal_card(r, res),
                )

        # ② 部门负责人汇总卡片（按 department 分组）
        by_dept: dict[str, list[tuple[object, object]]] = {}
        for r, res in warnings:
            by_dept.setdefault(r.department or "未知部门", []).append((r, res))
        for dept, items in by_dept.items():
            leader = await resolver.resolve_department_leader(dept)
            if leader:
                await send_user_card(
                    open_id=leader.open_id,
                    title=f"{dept} 持证到期汇总",
                    content=_build_dept_summary_card(dept, items),
                )

        # ③ 安管人员全量汇总
        if warnings:
            await send_user_card(
                open_id=ALERT_NOTIFY_OPEN_ID,  # person 许康福（scheduler.py 既有常量）
                title="全厂持证到期预警汇总",
                content=_build_full_summary_card(warnings),
            )

        logger.info(
            "持证预警推送完成: total=%d depts=%d",
            len(warnings), len(by_dept),
        )


def _build_personal_card(r: Any, res: Any) -> str:
    """本人个人卡片（Markdown）：姓名/证件类型/当前节点/截止日期/剩余天数/建议。"""
    cat_label = {
        "special_op": "特种作业证",
        "guardian_a": "监护人A证",
        "guardian_b": "监护人B证",
    }.get(r.cert_category, r.cert_category)
    deadline = res.deadline.isoformat() if res.deadline else "待确认"
    remaining = res.remaining_days
    if remaining is None:
        remaining_txt = "无法计算"
    elif remaining < 0:
        remaining_txt = f"已逾期 {abs(remaining)} 天"
    else:
        remaining_txt = f"剩 {remaining} 天"
    return (
        f"**持证到期提醒**\n"
        f"**姓名**: {r.person_name}\n"
        f"**证件类型**: {cat_label}\n"
        f"**当前节点**: {res.current_node or '—'}\n"
        f"**截止日期**: {deadline}\n"
        f"**剩余时间**: {remaining_txt}\n"
        f"**建议**: {res.suggestion or '请核查证件状态'}\n"
    )


def _build_dept_summary_card(dept: Any, items: Any) -> str:
    """部门负责人汇总卡片：按人列表明细。"""
    lines = [f"**{dept} 持证到期汇总**（{len(items)} 项）", ""]
    for r, res in items:
        deadline = res.deadline.isoformat() if res.deadline else "—"
        lines.append(
            f"- {r.person_name}｜{res.current_node or '—'}｜{deadline}｜"
            f"剩 {res.remaining_days if res.remaining_days is not None else '—'} 天"
        )
    lines.append("")
    lines.append("请核实并提前安排复审/换证。")
    return "\n".join(lines)


def _build_full_summary_card(warnings: Any) -> str:
    """安管人员全量汇总卡片：按部门 + 等级汇总。"""
    total = len(warnings)
    # 等级计数
    level_labels = {
        "overdue": "已逾期",
        "urgent": "7天内到期",
        "key_warning": "30天内到期",
        "to_schedule": "60天内到期",
        "early_notice": "90天内到期",
    }
    level_buckets: dict[str, int] = {}
    for _, res in warnings:
        level_buckets[res.status] = level_buckets.get(res.status, 0) + 1

    lines = ["**持证人员到期预警**", "", f"本次共识别需关注人员 **{total}** 人："]
    for key, label in level_labels.items():
        count = level_buckets.get(key, 0)
        if count:
            lines.append(f"- {label}：{count}人")
    lines.append("")

    # 涉及事项统计：按 cert_category + current_node 归一
    from app.modules.safety.service.cert_warning import CertWarningService

    by_event: dict[str, int] = {}
    for r, res in warnings:
        key = CertWarningService._event_key(r.cert_category, res.current_node)
        by_event[key] = by_event.get(key, 0) + 1
    if by_event:
        lines.append("涉及事项：")
        for key, count in sorted(by_event.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {key}：{count}人")
        lines.append("")

    # 按部门列出
    by_dept: dict[str, int] = {}
    for r, _res in warnings:
        dept = r.department or "未知部门"
        by_dept[dept] = by_dept.get(dept, 0) + 1
    if by_dept:
        lines.append("涉及部门：")
        for dept, count in sorted(by_dept.items(), key=lambda kv: -kv[1]):
            lines.append(f"- {dept}：{count}人")
        lines.append("")

    lines.append("建议提前组织复审培训及组织换证工作。")
    return "\n".join(lines)


async def _run_chemical_inventory_weekly(chat_id: str | None = None) -> None:
    """周五 15:30：危化品库存周报（落快照 + 环比 + AI 小结；仅配了群聊才发送）。"""
    from app.modules.safety.chemical_inventory.weekly_report import run_weekly_job

    report = await run_weekly_job(chat_id=chat_id)
    logger.info("危化品库存周报完成: snapshot=%s records=%d first=%s",
                report.get("snapshot_date"), report.get("records"), report.get("first"))


async def _run_chemical_inventory_daily(chat_id: str | None = None) -> None:
    """每天 19:30：拉取危险品日报群当日 Excel → 更新多维表 → 重算风险 → 推送分析日报。"""
    from app.modules.safety.chemical_inventory.daily_job import (
        run_scheduled_daily_update,
        send_daily_summary,
    )

    result = await run_scheduled_daily_update()
    logger.info("危化品库存日报更新: files=%s updated=%s created=%s scan=%s",
                len(result.get("files", [])), result.get("total_updated"),
                result.get("total_created"), result.get("scan"))
    await send_daily_summary(result, chat_id=chat_id)


async def _run_scheduled_job_guarded(job: dict[str, Any]) -> None:
    """带锁 + 超时地执行定时任务（并行调度入口）。

    - 锁：任务执行中再次到点 → 跳过本次触发（防重复推送）
    - 超时：任务超过 TASK_TIMEOUT 强制取消，状态保持执行前标记的 failed，
      由失败重试机制在补发窗口内自动接管
    """
    job_name = job["name"]
    lock = _get_task_lock(job_name)
    if lock.locked():
        logger.warning("定时任务仍在执行中，跳过本次触发: %s", job_name)
        return
    async with lock:
        try:
            await asyncio.wait_for(_run_scheduled_job(job), timeout=TASK_TIMEOUT)
        except TimeoutError:
            logger.error(
                "定时任务超时(%d秒)，已取消并标记失败待重试: %s", TASK_TIMEOUT, job_name
            )
        except Exception:
            logger.exception("定时任务执行异常: %s", job_name)


async def scheduled_task_loop() -> None:
    """安全模块定时任务主循环。

    已在 app/main.py lifespan 中启动，每 TICK_INTERVAL 秒检查一次。
    使用时间窗口（>=）触发，确保不会因服务器重启错过任务。
    到点任务以独立 task 并行执行，互不阻塞；同一任务由锁保证单实例。
    """
    # 首次启动：为无配置行的任务播种默认发送对象（env/代码默认 → DB），
    # 此后发送对象以 DB 为唯一来源，全部可由前端统一编辑
    try:
        from app.modules.safety.service.scheduler_config import (
            seed_default_task_targets,
        )

        await seed_default_task_targets()
    except Exception:
        logger.exception("默认任务配置播种失败（忽略，继续启动）")

    jobs = await _load_effective_jobs()
    logger.info(
        "安全模块定时任务循环已启动 (tick=%ds, report_jobs=%d, parallel=%s)",
        TICK_INTERVAL, len(jobs), True,
    )

    # 启动时输出各任务的下次触发时间
    for job in jobs:
        logger.info(
            "  定时任务: %s @ %02d:%02d",
            job["name"], job["hour"], job["minute"],
        )

    running_tasks: set[asyncio.Task] = set()

    # ── 隐患直读模式轮询（① 隐患AI分析 / ② AI整改审核）──
    # 由开关控制（SAFETY_HAZARD_DIRECT_POLL_ENABLED），未启用时协程立即返回。
    # 挂在调度器循环内启动，不新增进程、不改 app/main.py。
    from app.modules.safety.service.hazard_direct.loop import hazard_direct_loop

    direct_task = asyncio.create_task(hazard_direct_loop())

    while not stop_scheduled_task_flag.is_set():
        try:
            today = date.today()
            jobs = await _load_effective_jobs()  # 每次 tick 重读 DB 覆写，配置修改 30s 内生效
            for job in jobs:
                if await _should_run(job, today):
                    task = asyncio.create_task(_run_scheduled_job_guarded(job))
                    running_tasks.add(task)
                    task.add_done_callback(running_tasks.discard)

            await asyncio.wait_for(stop_scheduled_task_flag.wait(), timeout=TICK_INTERVAL)
        except TimeoutError:
            pass
        except Exception:
            logger.exception("定时任务循环异常")
            await asyncio.sleep(TICK_INTERVAL)

    # 关闭时等待所有在跑任务结束
    if running_tasks:
        await asyncio.gather(*running_tasks, return_exceptions=True)
    # 关闭直读轮询（其在跑的 AI 调用由协程取消自然中断）
    direct_task.cancel()
    try:
        await direct_task
    except (TimeoutError, asyncio.CancelledError):
        pass
    except Exception:
        logger.debug("直读轮询任务退出异常", exc_info=True)
    logger.info("安全模块定时任务循环已停止")
