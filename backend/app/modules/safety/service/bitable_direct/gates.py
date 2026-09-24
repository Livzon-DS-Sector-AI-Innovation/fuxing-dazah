"""公共直读底座的开关与闸门判定。

命名约定（全模块统一，与隐患 / 特殊作业改造对齐）：

    SAFETY_<DOMAIN>_DIRECT_ENABLED        直读总开关（生成路径是否走直读）
    SAFETY_<DOMAIN>_EVENT_SYNC_ENABLED    Bitable 事件 -> 平台库镜像
    SAFETY_<DOMAIN>_SYNC_JOB_ENABLED      全量对账 / 增量同步任务
    SAFETY_<DOMAIN>_WRITEBACK_<X>_ENABLED 平台 -> Bitable 回写

两种既有语义都必须被支持：

1. **总开关组合语义**（special_op_direct.config 的形状）：
   旧链路是否生效 = 单项开关 or 总开关未开。默认部署（全关）
   等于"与改造前行为完全一致"；打开总开关即停旧链路；把单项开关
   置 true 可双跑或分项回滚。用 ``legacy_event_sync_active`` /
   ``legacy_sync_job_active`` 表达。

2. **纯单项开关语义**（hazard_direct.config 的形状）：
   单项开关独立读取，不受任何总开关影响。直接用 ``event_sync_enabled``
   或 ``flag(domain_env(...))``。

本模块只读环境变量，不做任何 IO，不 import 任何业务域。
"""

from __future__ import annotations

import os

# 既有实现（hazard_direct / special_op_direct）使用的真值集合，保持一致
_TRUE = {"1", "true", "yes", "on"}

#  域名常量（避免各域硬编码字符串；新增域在此追加）

DOMAIN_HAZARD = "HAZARD"
DOMAIN_SPECIAL_OP = "SPECIAL_OP"
DOMAIN_FIRE_ALARM = "FIRE_ALARM"
DOMAIN_CENTRAL_ALARM = "CENTRAL_ALARM"
DOMAIN_CERT = "CERT"
DOMAIN_CHEMICAL_INVENTORY = "CHEMICAL_INVENTORY"
DOMAIN_KEY_RISK_OP = "KEY_RISK_OP"
DOMAIN_CONTRACTOR_ADMISSION = "CONTRACTOR_ADMISSION"
DOMAIN_EMERGENCY_DRILL = "EMERGENCY_DRILL"
DOMAIN_KNOWLEDGE = "KNOWLEDGE"
DOMAIN_MSDS = "MSDS"
DOMAIN_OH = "OH"
DOMAIN_HAZARD_ID = "HAZARD_ID"
DOMAIN_EHS_CHANGE = "EHS_CHANGE"


def flag(name: str, default: bool = False) -> bool:
    """读取布尔环境开关。

    空值或未设置返回 ``default``；无法识别的值也返回 ``default``
    （宁可回退到安全默认值，也不把拼错的值当成 true）。
    """
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUE


def int_env(name: str, default: int, *, minimum: int = 1) -> int:
    """读取整数环境参数；未设置或无法解析时回退 ``default``，并按 ``minimum`` 兜底。"""
    raw = (os.getenv(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(minimum, value)


def domain_env(domain: str, suffix: str) -> str:
    """拼出某域的环境变量名：SAFETY_<DOMAIN>_<SUFFIX>。"""
    return f"SAFETY_{domain.upper()}_{suffix}"


def direct_enabled(domain: str) -> bool:
    """直读总开关（默认关闭）。"""
    return flag(domain_env(domain, "DIRECT_ENABLED"))


def event_sync_enabled(domain: str) -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像（默认关闭）。"""
    return flag(domain_env(domain, "EVENT_SYNC_ENABLED"))


def sync_job_enabled(domain: str) -> bool:
    """旧路径：全量对账 / 增量同步任务（默认关闭）。"""
    return flag(domain_env(domain, "SYNC_JOB_ENABLED"))


def writeback_enabled(domain: str, name: str) -> bool:
    """平台 -> Bitable 回写开关（默认关闭；一个域可以有多个回写面）。"""
    return flag(domain_env(domain, f"WRITEBACK_{name.upper()}_ENABLED"))


def legacy_event_sync_active(domain: str) -> bool:
    """旧事件镜像链路的**实际**生效状态（总开关组合语义）。"""
    return event_sync_enabled(domain) or not direct_enabled(domain)


def legacy_sync_job_active(domain: str) -> bool:
    """旧同步任务的**实际**生效状态（总开关组合语义）。"""
    return sync_job_enabled(domain) or not direct_enabled(domain)
