"""contractor_admission 直读开关与闸门（全默认关）。

命名与 key_risk_op / cert 对齐，走 SAFETY_CONTRACTOR_ADMISSION_* 环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED | false | 列表/统计/详情/Agent 查询走直读 |
| SAFETY_CONTRACTOR_ADMISSION_EVENT_SYNC_ENABLED | false | Bitable 事件 -> 平台库镜像 |
| SAFETY_CONTRACTOR_ADMISSION_WRITEBACK_AI_ENABLED | false | 直读模式 AI 审核回写 Bitable 3 列 |

WRITEBACK_AI 只罩直读模式的回写步（DIRECT 关时 legacy 回写无条件执行，开关无关），
两态口径照 chemical_inventory。无 SYNC_JOB（本域无定时任务）、无 TTL 缓存
（探针 109 行单页 1.15s < 2s，spec §4.1 D3）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_CONTRACTOR_ADMISSION


def direct_enabled() -> bool:
    """直读总开关（默认关闭）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件 -> 平台库镜像。"""
    return gates.event_sync_enabled(_DOMAIN)


def legacy_event_sync_active() -> bool:
    """事件镜像实际生效状态：总开关关闭时旧链路照常（含事件自动审核）。"""
    return gates.legacy_event_sync_active(_DOMAIN)


def writeback_ai_enabled() -> bool:
    """直读模式 AI 审核结果回写 Bitable 3 列（默认关闭）。"""
    return gates.writeback_enabled(_DOMAIN, "AI")
