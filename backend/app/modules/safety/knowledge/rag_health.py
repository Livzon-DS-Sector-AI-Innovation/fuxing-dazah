"""RAG 知识层健康探活 — 欠费/断连主动告警（2026-11-04 事故补丁）。

背景：2026-11-01 15:09（北京时间）起智谱 embedding 余额耗尽（429/1113），
ragflow 检索全 500 → 后端 RAG 静默降级 ``ragplus_unavailable``（AI 管线
「产出标注不中止」设计），3 天无人发现，期间新增隐患判定依据全部落
「知识库中无相应条文」占位。轮询全绿/分析照跑 ≠ 知识层健康，故独立探活。

探活两项（独立判定，任一失败 = 故障）：
- **embedding 直连**：POST ``/embeddings`` 拿原始错误体（429/1113
  「余额不足」原文即在此）。不能走 ``EmbeddingService.embed``——它吞错
  降级零向量，探活要的就是错误本身；
- **ragflow 检索端到端**：``RagplusClient.search(top_k=1)``，连带库解析/
  token 作用域/引擎内部 embedding。``SAFETY_RAGPLUS_SEARCH_ENABLED``
  关闭时跳过该项（旧三层管线不用 ragflow）。

告警（私发管理员 ``ALERT_NOTIFY_OPEN_ID``，与轮询失败告警同一收件人）：
- 健康 → 故障：立即告警（含两项错误原文，充值/续费类错误一眼可辨）；
- 持续故障：每 ``SAFETY_RAG_HEALTH_ALERT_REPEAT_HOURS``（默认 24h）提醒
  一次，防轰炸；
- 故障 → 恢复：恢复通知（含持续时长）。

开关 ``SAFETY_RAG_HEALTH_ENABLED``（app_config，DB 改 30s 内生效，无需
重启）；间隔在任务注册时读 ``SAFETY_RAG_HEALTH_INTERVAL_SECONDS``。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

import httpx

from app.modules.safety.app_config.store import store

logger = logging.getLogger(__name__)

# 探活向量请求上限（秒）——探活要快失败，不占业务超时预算
_PROBE_TIMEOUT_SECONDS = 15
# 错误原文截断（告警卡片单段上限，防长堆栈刷屏）
_DETAIL_LIMIT = 160

# ═══════════════════════════════════════════════════════════════
# 状态机（进程级；探活单线程 interval 任务，无并发写）
# ═══════════════════════════════════════════════════════════════


class _HealthState:
    """探活状态：degraded 标记 + 首次故障时间 + 上次告警时间。"""

    def __init__(self) -> None:
        self.degraded: bool = False
        self.first_failed_at: float | None = None  # time.monotonic
        self.last_alert_at: float | None = None

    def reset(self) -> None:
        """重置为健康态（测试用）。"""
        self.degraded = False
        self.first_failed_at = None
        self.last_alert_at = None


_STATE = _HealthState()


def _repeat_seconds() -> int:
    """持续故障重提醒间隔（小时 → 秒，默认 24h）。"""
    hours = store.get_int("SAFETY_RAG_HEALTH_ALERT_REPEAT_HOURS", 24)
    return max(1, hours) * 3600


# ═══════════════════════════════════════════════════════════════
# 探活实现
# ═══════════════════════════════════════════════════════════════


def _embedding_endpoint() -> tuple[str, str, str]:
    """解析 embedding 探活端点：ai 配置中心 → env 兜底（对齐 EmbeddingService）。"""
    cfg: dict = {}
    try:
        from app.modules.safety.ai_config.resolver import get_profile_config

        cfg = get_profile_config("embedding") or {}
    except Exception:
        cfg = {}
    api_key = cfg.get("api_key") or os.getenv("SAFETY_EMBEDDING_API_KEY", "")
    base_url = (
        cfg.get("base_url") or os.getenv("SAFETY_EMBEDDING_BASE_URL", "")
    ).rstrip("/")
    model = cfg.get("model") or os.getenv("SAFETY_EMBEDDING_MODEL", "embedding-3")
    return api_key, base_url, model


async def probe_embedding() -> tuple[bool, str]:
    """直连 embedding API（当前智谱）。返回 (是否健康, 错误原文/耗时)。"""
    api_key, base_url, model = _embedding_endpoint()
    if not api_key or not base_url:
        return False, "embedding 未配置（api_key/base_url 为空），探活无法进行"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{base_url}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": "知识层健康探活"},
            )
    except httpx.HTTPError as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if resp.status_code == 200:
        return True, f"{model} 正常（{resp.elapsed.total_seconds():.1f}s）"
    return False, f"HTTP {resp.status_code}: {resp.text[:_DETAIL_LIMIT]}"


async def probe_ragplus() -> tuple[bool, str] | None:
    """ragflow 检索端到端探活。返回 None = 检索开关未开，跳过该项。"""
    from app.modules.safety.knowledge.ragplus_client import get_ragplus_client

    if not store.get_bool("SAFETY_RAGPLUS_SEARCH_ENABLED", default=False):
        return None
    try:
        hits = await get_ragplus_client().search("安全生产 隐患 排查", top_k=1)
        return True, f"检索正常（命中 {len(hits)} 条）"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"[:_DETAIL_LIMIT + 60]


async def _notify_admin(title: str, content: str) -> bool:
    """私发管理员卡片（失败只记日志，绝不抛——探活自身不能成故障源）。"""
    try:
        from app.modules.safety.feishu.notification import send_user_card
        from app.modules.safety.scheduler import ALERT_NOTIFY_OPEN_ID

        ok = await send_user_card(
            open_id=ALERT_NOTIFY_OPEN_ID, title=title, content=content
        )
        if not ok:
            logger.warning("RAG 探活告警发送失败(返回False): %s", title)
        return bool(ok)
    except Exception:
        logger.exception("RAG 探活告警发送异常: %s", title)
        return False


def _format_detail(embedding: tuple[bool, str], ragplus: tuple[bool, str] | None) -> str:
    """两项探活结果 → 卡片明细行。"""
    ok_e, detail_e = embedding
    lines = [f"• embedding 直连：{'✅' if ok_e else '❌'} {detail_e}"]
    if ragplus is not None:
        ok_r, detail_r = ragplus
        lines.append(f"• ragflow 检索：{'✅' if ok_r else '❌'} {detail_r}")
    else:
        lines.append("• ragflow 检索：➖ 跳过（SAFETY_RAGPLUS_SEARCH_ENABLED 关闭）")
    return "\n".join(lines)


def _duration_text(seconds: float) -> str:
    secs = int(seconds)
    days, secs = divmod(secs, 86400)
    hours, secs = divmod(secs, 3600)
    if days:
        return f"{days}天{hours}小时"
    if hours:
        return f"{hours}小时{secs // 60}分"
    return f"{secs // 60}分{secs % 60}秒"


# ═══════════════════════════════════════════════════════════════
# 单轮探活（状态翻转告警）
# ═══════════════════════════════════════════════════════════════


async def run_rag_health_probe(*, notify: bool = True) -> dict[str, object]:
    """执行一轮探活：两探并发 → 状态机判定 → 翻转/重提醒告警。

    Returns:
        {"healthy": bool, "embedding": ..., "ragplus": ..., "alerted": bool}
        （探活结果同时落 INFO 日志，任务运行中心外的排障入口）
    """
    embedding, ragplus = await asyncio.gather(probe_embedding(), probe_ragplus())
    healthy = embedding[0] and (ragplus is None or ragplus[0])
    now = time.monotonic()
    alerted = False

    if not healthy:
        if not _STATE.degraded:
            # 健康 → 故障：立即告警
            _STATE.degraded = True
            _STATE.first_failed_at = now
            detail = _format_detail(embedding, ragplus)
            content = (
                f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"{detail}\n\n"
                "影响：AI 隐患分析/整改初审失去知识库增强，判定依据只能写"
                "「知识库中无相应条文」；检索类问答直接报错。\n"
                "（余额/欠费类错误请充值对应 API 账号；持续故障每日提醒一次）"
            )
            alerted = notify and await _notify_admin("🔴 RAG 知识层探活失败", content)
            _STATE.last_alert_at = now if alerted else None
            logger.error("RAG 探活故障（已告警=%s）：\n%s", alerted, detail)
            # R3 运维自愈直投（翻转即投；直投失败只记日志，绝不影响探活）
            from app.modules.safety.service.ops_selfheal_r3.rag_inject import (
                inject_rag_signal,
            )

            await inject_rag_signal("degraded", detail=detail)
        elif (
            _STATE.last_alert_at is None
            or now - _STATE.last_alert_at >= _repeat_seconds()
        ):
            # 持续故障：到重提醒间隔才再发（首告警失败则下轮即重试）
            detail = _format_detail(embedding, ragplus)
            duration = _duration_text(now - (_STATE.first_failed_at or now))
            content = (
                f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"已持续故障：{duration}\n\n{detail}"
            )
            alerted = notify and await _notify_admin("🔴 RAG 知识层仍不可用（持续中）", content)
            if alerted:
                _STATE.last_alert_at = now
            logger.error("RAG 探活持续故障（%s，已提醒=%s）", duration, alerted)
        else:
            logger.info("RAG 探活持续故障（提醒冷却中，不重复告警）")
    else:
        detail = _format_detail(embedding, ragplus)
        if _STATE.degraded:
            # 故障 → 恢复：通知（含持续时长）
            duration = _duration_text(now - (_STATE.first_failed_at or now))
            content = (
                f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"上次故障持续：{duration}\n\n{detail}"
            )
            alerted = notify and await _notify_admin("🟢 RAG 知识层已恢复", content)
            logger.info("RAG 探活恢复（故障持续 %s，已通知=%s）", duration, alerted)
            # R3 运维自愈直投（翻转即投；直投失败只记日志，绝不影响探活）
            from app.modules.safety.service.ops_selfheal_r3.rag_inject import (
                inject_rag_signal,
            )

            await inject_rag_signal(
                "recovered", detail=detail,
                duration_seconds=now - (_STATE.first_failed_at or now),
            )
        else:
            logger.info("RAG 探活正常：%s", detail.replace("\n", "；"))
        _STATE.reset()

    return {
        "healthy": healthy,
        "embedding": embedding,
        "ragplus": ragplus,
        "alerted": alerted,
    }
