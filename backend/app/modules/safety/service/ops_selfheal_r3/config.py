"""R3 配置读取 —— app_config 七键（设计 §6；store 缓存 30s 热生效）。

默认全关/observe（三层开关链：SUPERAGENT_ENABLED → SAFETY_R3_OPS_ENABLED
→ SAFETY_R3_REPAIR_MODE）；模式切换权永远在人（红线）。
"""

from __future__ import annotations

from app.modules.safety.app_config.store import store

#: 默认白名单 = L0 两项（设计 §4.4；L1 动作须人工加入）
DEFAULT_ALLOWED_ACTIONS = "notify_enriched,rag_recheck"

#: 合法修复模式（翻 auto 只能人工改配置）
REPAIR_MODES = ("observe", "auto")


def ops_enabled() -> bool:
    """R3 总闸（源 config.enabled 是第二层，DB 置 true 才真正轮询）。"""
    return store.get_bool("SAFETY_R3_OPS_ENABLED", False)


def scan_interval_seconds() -> int:
    """扫描周期秒（每轮 poll 热读，覆盖迁移播种的 schedule 值）。"""
    return store.get_int("SAFETY_R3_SCAN_INTERVAL_SECONDS", 300, minimum=30)


def diag_llm_enabled() -> bool:
    """false = 纯规则降级（证据直出不上 LLM）。"""
    return store.get_bool("SAFETY_R3_DIAG_LLM_ENABLED", True)


def repair_mode() -> str:
    """L1 修复动作闸：observe（默认，只报告）/ auto（白名单内执行）。"""
    raw = (store.get_str("SAFETY_R3_REPAIR_MODE", "observe") or "observe").strip().lower()
    return raw if raw in REPAIR_MODES else "observe"


def allowed_actions() -> set[str]:
    """修复动作白名单（csv 热调；解析失败回落 L0 两项）。"""
    raw = (store.get_str("SAFETY_R3_ALLOWED_ACTIONS") or "").strip()
    if not raw:
        return set(DEFAULT_ALLOWED_ACTIONS.split(","))
    items = {x.strip() for x in raw.split(",") if x.strip()}
    return items or set(DEFAULT_ALLOWED_ACTIONS.split(","))


def max_repair_rounds() -> int:
    """每事件修复轮上限（超出转 needs_human）。"""
    return store.get_int("SAFETY_R3_MAX_REPAIR_ROUNDS", 2, minimum=1)


def daily_rerun_cap() -> int:
    """死信/stale 重灌日上限（条）。"""
    return store.get_int("SAFETY_R3_DAILY_RERUN_CAP", 50, minimum=1)
