"""AI 调用失败飞书通知。

当审计日志中出现失败记录（status="failed"）时，通过飞书卡片通知指定接收人。
使用 Redis 做去重：同一 scenario 在 TTL 窗口内只发一次通知，避免故障雪崩时消息轰炸。

通知为 fire-and-forget 模式：异步后台发送，绝不阻塞审计写入或业务调用。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.core.redis import cache_get, cache_set

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

# 通知接收人（飞书 open_id）
NOTIFY_OPEN_ID = "ou_495039d6335d347b07ff92ad982b3b4e"  # 许康福
NOTIFY_NAME = "许康福"

# Redis 去重 key 前缀 + TTL（秒）
DEBOUNCE_PREFIX = "safety:ai_failure_notified:"
DEBOUNCE_TTL = 300  # 同一 scenario 5 分钟内只通知一次

# 通知总限流：1 小时内最多发 N 条（防止极端情况下多 scenario 轮流轰炸）
RATE_LIMIT_KEY = "safety:ai_failure_notify_count"
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 3600

# 场景 → 中文标签
SCENARIO_LABELS: dict[str, str] = {
    "hazard_identification": "隐患识别",
    "rectification_review": "整改初审",
    "agent_chat": "助手对话",
    "knowledge_chat": "知识库问答",
    "graph_build": "图谱构建",
    "regulation_crawl": "法规筛选",
    "drill_plan_generation": "演练预案生成",
    "drill_report_generation": "演练报告生成",  # 已废弃，保留兼容
    "drill_issue_parsing": "演练问题解析",
    "drill_plan_parsing": "演练计划解析",
    "embedding": "向量化",
    "rerank": "重排序",
    "memory_extraction": "记忆提取",
    "sop_generation": "操规AI补全",
    "sop_review": "操规AI审核",
    "contractor_admission_review": "相关方准入审核",
    "unknown": "未知场景",
}


def _scenario_label(scenario: str) -> str:
    """场景标识 → 中文标签。"""
    return SCENARIO_LABELS.get(scenario, scenario)


# ═══════════════════════════════════════════════════════════════
# 公共接口
# ═══════════════════════════════════════════════════════════════


async def notify_ai_failure(
    *,
    scenario: str,
    error: str | None = None,
    trace_id: str | None = None,
    channel: str | None = None,
    model: str | None = None,
) -> None:
    """当 AI 调用失败时发送飞书通知（带去重 + 限流）。

    同一 scenario 在 DEBOUNCE_TTL 窗口内只发一次；
    全局限流 1 小时内最多 RATE_LIMIT_MAX 条。
    通知发送失败仅记录日志，绝不抛异常。
    """
    # ── 防御性排除：场景熔断（ScenarioDisabledError）是主动拦截，非真实故障 ──
    #   guard 在 chat 入口任何 try 之前 raise → 正常链路根本走不到这里；
    #   仅当未来有调用方把 ScenarioDisabledError 写成 failed 审计时兜底不通知。
    if _is_scenario_disabled_error(error):
        logger.info("跳过失败通知: AI 场景主动熔断（非真实故障）scenario=%s", scenario)
        return

    # ── 去重检查（Redis 不可用时 fail-open：跳过去重，直接发送） ──
    debounce_key = f"{DEBOUNCE_PREFIX}{scenario}"
    redis_ok = True
    try:
        if await cache_get(debounce_key):
            logger.debug("失败通知已去重: scenario=%s", scenario)
            return

        count_str = await cache_get(RATE_LIMIT_KEY)
        count = int(count_str) if count_str else 0
        if count >= RATE_LIMIT_MAX:
            logger.warning(
                "AI 失败通知已达限流上限 %d/%dh，跳过: scenario=%s",
                RATE_LIMIT_MAX, RATE_LIMIT_WINDOW // 3600, scenario,
            )
            return
    except Exception:
        # Redis 不可用 → fail-open：跳过去重/限流，确保通知不丢失
        count = 0
        count_str = None
        redis_ok = False
        logger.warning("Redis 不可用，跳过失败通知去重/限流检查")

    try:
        # ── 构建卡片内容 ──
        from app.modules.safety.feishu.notification import send_user_card

        label = _scenario_label(scenario)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        error_text = error or "（无错误详情）"
        trace_text = trace_id or "（无）"
        channel_text = channel or "（无）"
        model_text = model or "（无）"

        content = (
            f"**场景**：{label}（`{scenario}`）\n"
            f"**时间**：{now}\n"
            f"**模型**：{model_text}\n"
            f"**渠道**：{channel_text}\n"
            f"**Trace ID**：`{trace_text}`\n\n"
            f"**错误信息**：\n{error_text}"
        )

        # ── 发送 ──
        ok = await send_user_card(
            open_id=NOTIFY_OPEN_ID,
            title=f"⚠️ AI 调用失败 — {label}",
            content=content,
        )

        if ok:
            # 写入去重标记 + 递增限流计数（Redis 可用时）
            if redis_ok:
                try:
                    await cache_set(debounce_key, "1", ex=DEBOUNCE_TTL)
                    if count_str:
                        ttl = await _get_ttl(RATE_LIMIT_KEY)
                        await cache_set(RATE_LIMIT_KEY, str(count + 1), ex=max(ttl, 1))
                    else:
                        await cache_set(RATE_LIMIT_KEY, "1", ex=RATE_LIMIT_WINDOW)
                except Exception:
                    pass  # 去重写入失败不影响
            logger.info(
                "AI 失败通知已发送: scenario=%s recipient=%s trace_id=%s",
                scenario, NOTIFY_NAME, trace_id,
            )
        else:
            logger.warning("AI 失败通知发送失败（飞书 API 返回非成功）: scenario=%s", scenario)
    except Exception:
        logger.exception("AI 失败通知异常（不影响业务）")


def _is_scenario_disabled_error(error: str | Exception | None) -> bool:
    """判断错误是否为场景熔断（ScenarioDisabledError 实例或其消息前缀）。

    ``fire_notify`` 收到的 error 通常是 ``_write_audit`` 传来的字符串
    （``type(e).__name__: e``），故同时识别实例与消息前缀（双保险）。
    """
    try:
        from app.modules.safety.ai_config.exceptions import ScenarioDisabledError

        if isinstance(error, ScenarioDisabledError):
            return True
    except Exception:  # noqa: BLE001 — 防御性检查自身永不抛
        pass
    return isinstance(error, str) and error.startswith("AI 场景已停用")


def fire_notify(**kwargs) -> None:
    """fire-and-forget 包装：在后台事件循环中发送通知，不阻塞当前协程。

    调用方无需 await —— 通知在后台异步执行，失败仅记日志。
    若当前无事件循环（同步脚本），静默跳过。
    """
    if _is_scenario_disabled_error(kwargs.get("error")):
        logger.debug("fire_notify: 场景熔断（非真实故障），跳过通知")
        return
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(notify_ai_failure(**kwargs))
    except RuntimeError:
        # 无运行中的事件循环（如测试脚本/同步上下文）
        logger.debug("无事件循环，跳过失败通知: scenario=%s", kwargs.get("scenario"))
    except Exception:
        logger.exception("fire_notify 异常")


# ═══════════════════════════════════════════════════════════════
# 内部
# ═══════════════════════════════════════════════════════════════


async def _get_ttl(key: str) -> int:
    """获取 Redis key 的剩余 TTL（秒），失败返回 0。"""
    try:
        from app.core.redis import redis_client
        ttl = await redis_client.ttl(key)
        return max(ttl, 0)
    except Exception:
        return 0
