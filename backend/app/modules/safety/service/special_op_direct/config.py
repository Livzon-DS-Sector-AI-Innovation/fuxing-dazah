"""特殊作业「直读多维表格」改造开关（全部默认关闭，灰度上线，一键回滚）。

开关名与隐患系统改造对齐（SAFETY_HAZARD_* -> SAFETY_SPECIAL_OP_*），全部走环境变量：

| 开关 | 默认 | 作用 |
|---|---|---|
| SAFETY_SPECIAL_OP_DIRECT_ENABLED | false | 直读总开关：日报走直读还是旧镜像链路 |
| SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED | false | 旧路径：Bitable 事件 -> 平台库镜像行 |
| SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED | false | 旧路径：08:00 全量对账与 17:00 增量同步 |
| SAFETY_SPECIAL_OP_WRITEBACK_RISK_ENABLED | false | 回写「日报风险等级（AI）」列 |
| SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED | true | 速递卡：日报推送改速递式布局（false 回退旧长卡） |

回滚：把开关改回原值并重启即可，无数据副作用（存量镜像行保留）。

本模块的开关读取与闸门判定全部转发公共底座 ``bitable_direct.gates``，不再维护
重复的 ``_flag`` 实现；对外函数名与默认值保持不变。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_SPECIAL_OP


def direct_enabled() -> bool:
    """直读总开关。关闭时日报编排仍走旧镜像链路（真双路径切换）。"""
    return gates.direct_enabled(_DOMAIN)


def event_sync_enabled() -> bool:
    """旧路径：Bitable 事件处理器（WS 事件 -> 平台库镜像行）。"""
    return gates.event_sync_enabled(_DOMAIN)


def sync_job_enabled() -> bool:
    """旧路径：08:00 全量对账与 17:00 增量同步。"""
    return gates.sync_job_enabled(_DOMAIN)


def writeback_risk_enabled() -> bool:
    """回写「日报风险等级（AI）」列。"""
    return gates.writeback_enabled(_DOMAIN, "RISK")


def digest_card_enabled() -> bool:
    """速递卡开关（默认开启）。

    开启时日报推送速递式布局（完整明细收进折叠面板）；显式置 false
    回退旧长卡。构建失败/卡片超限时代码内也会自动回退旧长卡。
    """
    return gates.flag(
        gates.domain_env(_DOMAIN, "DIGEST_CARD_ENABLED"), default=True
    )


#
# 闸门判定（Ticket 06）
#


def legacy_event_sync_active() -> bool:
    """旧事件镜像链路的**实际**生效状态。

    直读总开关关闭 -> 恒生效（默认部署 = 与改造前行为完全一致）；
    直读总开关打开 -> 由 ``SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED`` 决定
    （显式打开 = 回滚/双跑，默认关闭 = 停止镜像）。
    """
    return gates.legacy_event_sync_active(_DOMAIN)


def legacy_sync_job_active() -> bool:
    """旧 08:00 全量对账 / 17:00 增量同步的**实际**生效状态（语义同上）。"""
    return gates.legacy_sync_job_active(_DOMAIN)
