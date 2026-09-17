"""隐患系统「直读多维表格」模式 — 开关与参数。

设计原则：
- 新路径默认全部关闭（灰度上线），旧通道（事件同步 / 差异同步 / 落库）保持不变；
- 所有开关走环境变量，便于按环境灰度与快速回滚；
- 开关名统一 ``SAFETY_HAZARD_*`` 前缀。

配套设计：``设计文档/DESIGN-隐患系统改造方案-待确认.md``
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_HAZARD

# 兼容私有调用：转发底座实现，不保留第二份布尔/整数解析逻辑。
_flag = gates.flag
_int = gates.int_env


# ═══════════════════════════════════════════════════════════════
# 总开关
# ═══════════════════════════════════════════════════════════════


def direct_poll_enabled() -> bool:
    """新路径总开关（关闭时 ① ② 轮询循环不启动）。"""
    return _flag(gates.domain_env(_DOMAIN, "DIRECT_POLL_ENABLED"), False)


def ai_poll_enabled() -> bool:
    """① 隐患AI分析轮询。"""
    return direct_poll_enabled() and _flag(
        gates.domain_env(_DOMAIN, "AI_POLL_ENABLED"), False
    )


def review_poll_enabled() -> bool:
    """② AI整改审核轮询。"""
    return direct_poll_enabled() and _flag(
        gates.domain_env(_DOMAIN, "REVIEW_POLL_ENABLED"), False
    )


def supervision_poll_enabled() -> bool:
    """③ 督办等级计算轮询（读多维表格 → 算 → 只回写多维表格）。"""
    return direct_poll_enabled() and _flag(
        gates.domain_env(_DOMAIN, "SUPERVISION_POLL_ENABLED"), False
    )


def event_sync_enabled() -> bool:
    """旧路径开关：Bitable 事件 → 平台库镜像（hazard_reports）+ 事件驱动 AI。

    2026-09-09 改造后默认 **关闭**：隐患记录以多维表格为唯一数据源，
    平台库镜像不再维护（Web 隐患页面会停止更新），AI 由轮询负责。

    置为 true 可恢复旧行为（用于回滚或需要 DB 镜像的场景）。
    """
    return gates.event_sync_enabled(_DOMAIN)


def catch_up_enabled() -> bool:
    """旧路径：启动时 Bitable 漏单恢复（写平台库）。默认关闭。"""
    return _flag(gates.domain_env(_DOMAIN, "CATCHUP_ENABLED"), False)


# ⑤ 催办发送对象：**始终动态**（每条隐患的责任人 + 该部门分管安全员），
# 名单由 DEPT_CONFIG / IdentityResolver 在每次执行时现算，不保留固定收件人。
# 见 progress_dunning.send_progress_dunning_dynamic()。


# ═══════════════════════════════════════════════════════════════
# 轮询参数
# ═══════════════════════════════════════════════════════════════


def poll_interval_seconds() -> int:
    """轮询间隔（默认 300 秒 = 5 分钟，下限 60 秒）。"""
    return _int("SAFETY_HAZARD_POLL_INTERVAL_SECONDS", 300, minimum=60)


def review_stagger_seconds() -> int:
    """② 相对 ① 的错开秒数（避免两个轮询同时打 Bitable，默认半周期）。"""
    return _int(
        "SAFETY_HAZARD_POLL_STAGGER_SECONDS", poll_interval_seconds() // 2, minimum=0
    )


def supervision_stagger_seconds() -> int:
    """③ 相对 ① 的错开秒数（默认四分之一周期）。"""
    return _int(
        "SAFETY_HAZARD_SUPERVISION_STAGGER_SECONDS",
        poll_interval_seconds() // 4,
        minimum=0,
    )


def batch_limit() -> int:
    """单轮最多处理条数（默认 200；① 存量 36 条、② 存量 25 条均可一次跑完）。"""
    return _int("SAFETY_HAZARD_POLL_BATCH_LIMIT", 200)


def write_concurrency() -> int:
    """单轮内并发数（默认 3；Bitable 单表不支持并发写，写入仍串行化）。"""
    return _int("SAFETY_HAZARD_POLL_CONCURRENCY", 3)


def record_lock_ttl() -> int:
    """per-record 处理锁 TTL（秒，默认 600）。"""
    return _int("SAFETY_HAZARD_POLL_LOCK_TTL", 600)


# ═══════════════════════════════════════════════════════════════
# 告警阈值
# ═══════════════════════════════════════════════════════════════


def alert_min_failures() -> int:
    """单轮失败条数达到该值 → 推送告警（默认 10）。"""
    return _int("SAFETY_HAZARD_ALERT_MIN_FAILURES", 10)


def alert_after_rounds() -> int:
    """连续失败轮数达到该值 → 推送告警（默认 3）。"""
    return _int("SAFETY_HAZARD_ALERT_AFTER_ROUNDS", 3)
