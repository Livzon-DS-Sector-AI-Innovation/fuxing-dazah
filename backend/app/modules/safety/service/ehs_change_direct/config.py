"""ehs_change 直读开关（全默认关）。

本域仅 DIRECT 一个开关（spec D1——§4.9 Q2=A 一期口径），**只切换
query_ehs_changes 一个工具**：

- 不设 EVENT_SYNC 开关：事件承载镜像同步 + 审批表新增触发平台 AI 审核
  （run_ehs_ai_review 回填 Bitable 9+1 列），handler 不设闸门、订阅不可
  退订（spec §0，emergency_drill/knowledge/msds/oh/hazard_id 同款）；
- 不设 WRITEBACK 开关：AI 审核回写随事件流程本体，不随 DIRECT 切换；
- 无 SYNC_JOB（本域无定时任务，scheduler.py 零改动）；
- TTL 缓存 60s（spec D4 预授权条款：探针两表 492 行串行实测约 2.3s >
  2s 验收线，msds 2.73s / hazard_id 3.68s 先例）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_EHS_CHANGE

DEFAULT_CACHE_TTL_SECONDS = 60


def direct_enabled() -> bool:
    """直读总开关（默认关闭）：Agent query_ehs_changes 走 EHS 变更
    审批/验收两表 Bitable 直读。"""
    return gates.direct_enabled(_DOMAIN)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存窗口（秒，默认 60；最小 1）。"""
    return gates.int_env(
        "SAFETY_EHS_CHANGE_DIRECT_CACHE_TTL_SECONDS",
        DEFAULT_CACHE_TTL_SECONDS,
    )
