"""Bitable 配置变更 → 重订阅钩子（backend-design §3.3）。

    - ``DOMAIN_SUBSCRIBE_HOOKS``：drive 文档订阅域 → ensure 订阅函数
      （cert 为新增，见 §0 事实 2；contractor_admission 2026-08-31 由
      record 事件迁移为 drive 文档事件后纳入）；
    - ``resubscribe_domain(domain)``：对域内全部 drive 订阅重跑 ensure
      （幂等——飞书文档订阅持久，per file_token 独立，重复订阅无害）。

循环依赖约定（§3.1）：本模块**不**在模块级 import handler 模块——
``ensure_*_subscribed`` 经 ``_make_hook`` 包装延迟 import（handler import
store、store 也不在模块级 import 本模块，链条无环）。
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from app.modules.safety.bitable_config.registry import REGISTRY

logger = logging.getLogger(__name__)


def _make_hook(module_path: str, func_name: str) -> Callable[[], Awaitable[bool]]:
    """构造延迟 import 的订阅钩子（首次调用时 import 并执行 ensure 函数）。"""

    def _hook() -> Awaitable[bool]:
        module = importlib.import_module(module_path)
        ensure_fn = cast(
            Callable[[], Awaitable[bool]], getattr(module, func_name)
        )
        return ensure_fn()

    return _hook


# 域 → (handler 模块, ensure 函数名)（10 个 drive 订阅域，record 域不入表）
_DOMAIN_SUBSCRIBE_TARGETS: dict[str, tuple[str, str]] = {
    "hazard": (
        "app.modules.safety.feishu.bitable_handler",
        "ensure_bitable_subscribed",
    ),
    "knowledge": (
        "app.modules.safety.feishu.knowledge_bitable_handler",
        "ensure_knowledge_bitable_subscribed",
    ),
    "chemical_inventory": (
        "app.modules.safety.feishu.chemical_inventory_bitable_handler",
        "ensure_chemical_inventory_bitable_subscribed",
    ),
    "oh": (
        "app.modules.safety.feishu.oh_bitable_handler",
        "ensure_oh_bitable_subscribed",
    ),
    "fire_alarm": (
        "app.modules.safety.feishu.fire_alarm_bitable_handler",
        "ensure_fire_alarm_bitable_subscribed",
    ),
    "central_alarm": (
        "app.modules.safety.feishu.central_alarm_bitable_handler",
        "ensure_central_alarm_bitable_subscribed",
    ),
    "hazard_id": (
        "app.modules.safety.feishu.hazard_identification_bitable_handler",
        "ensure_hazard_id_bitable_subscribed",
    ),
    "special_op": (
        "app.modules.safety.feishu.special_op_bitable_handler",
        "ensure_special_op_bitable_subscribed",
    ),
    "key_risk_op": (
        "app.modules.safety.feishu.key_risk_op_bitable_handler",
        "ensure_key_risk_op_bitable_subscribed",
    ),
    "cert": (
        "app.modules.safety.feishu.cert_bitable",
        "ensure_cert_bitable_subscribed",  # 新增：订阅 2 个唯一 app_token
    ),
    "contractor_admission": (
        "app.modules.safety.feishu.contractor_admission_bitable_handler",
        "ensure_contractor_admission_bitable_subscribed",
        # 2026-08-31 迁移：原 record 事件（bitable.record.*）实际从不推送，
        # 改用 drive 文档事件 + 文档订阅（与 hazard 等域同构）
    ),
    "emergency_drill": (
        "app.modules.safety.feishu.emergency_drill_bitable_handler",
        "ensure_emergency_drill_bitable_subscribed",
        # 2026-09-08 迁移：同 contractor_admission，record 事件从不推送
    ),
    "msds": (
        "app.modules.safety.feishu.msds_bitable_handler",
        "ensure_msds_bitable_subscribed",
        # 2026-09-08 迁移：同 contractor_admission，record 事件从不推送
    ),
    "ehs_change": (
        "app.modules.safety.feishu.ehs_change_bitable_handler",
        "ensure_ehs_change_bitable_subscribed",
        # 2026-09-08 迁移：同 contractor_admission，record 事件从不推送
    ),
}

DOMAIN_SUBSCRIBE_HOOKS: dict[str, Callable[[], Awaitable[bool]]] = {
    domain: _make_hook(module_path, func_name)
    for domain, (module_path, func_name) in _DOMAIN_SUBSCRIBE_TARGETS.items()
}


async def resubscribe_domain(domain: str) -> dict[str, Any]:
    """对域内全部 drive 订阅重跑 ensure（幂等，飞书订阅持久）。

    返回 ``{"domain": ..., "results": {kind: ok|skipped|failed}}``。
    2026-09-08 起全部域均为 drive 订阅域（最后的 record 域 drill/msds/ehs 已迁移）。
    """
    domain_info = REGISTRY.get(domain)
    if domain_info is None:
        raise ValueError(f"未知域名: {domain}")
    if domain_info.subscribe != "drive":
        logger.info("域 %s 为 record 事件域，无需 Drive 文档订阅，跳过", domain)
        return {"domain": domain, "results": {"skipped": True}}

    hook = DOMAIN_SUBSCRIBE_HOOKS.get(domain)
    if hook is None:
        logger.info("域 %s 无订阅钩子，跳过", domain)
        return {"domain": domain, "results": {"skipped": True}}

    try:
        ok = await hook()
    except Exception:
        logger.exception("域 %s 重订阅执行异常", domain)
        ok = False

    # 延迟 import store（本模块 import store 亦安全，保持与 handler 一致的最小依赖）
    from app.modules.safety.bitable_config.store import store

    results: dict[str, str] = {}
    for kind_info in domain_info.kinds:
        conn = store.get_connection(domain, kind_info.kind)
        if conn is None:
            results[kind_info.kind] = "skipped"
        elif ok:
            results[kind_info.kind] = "ok"
        else:
            results[kind_info.kind] = "failed"
    return {"domain": domain, "results": results}


__all__ = ["DOMAIN_SUBSCRIBE_HOOKS", "resubscribe_domain"]
