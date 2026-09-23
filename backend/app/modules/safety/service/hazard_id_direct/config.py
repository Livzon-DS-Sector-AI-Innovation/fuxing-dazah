"""hazard_id 直读开关（全默认关）。

本域仅 DIRECT 一个开关（spec D1——§4.11 一期口径），**只切换
query_hazard_identifications 一个工具**：

- 不设 EVENT_SYNC 开关：事件是 8 脚本 AI 流程引擎（advance_record 判定 +
  AI 执行 + 节点推进/回写）的唯一自动触发器，订阅不可退订，「收敛镜像
  写入面」无安放点（spec §0，emergency_drill/knowledge/msds/oh 同款）；
- 不设 WRITEBACK 开关：本域直读纯只读，AI 回写随事件流程本体不随 DIRECT 切换；
- 无 SYNC_JOB（本域无定时任务，scheduler.py 零改动）；
- TTL 缓存 60s（spec D4 预授权条款：探针全量 594 行 2 页实测 3.68s > 2s
  验收线，msds 2.73s 触发先例）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_HAZARD_ID

DEFAULT_CACHE_TTL_SECONDS = 60


def direct_enabled() -> bool:
    """直读总开关（默认关闭）：Agent query_hazard_identifications 走危险源
    辨识表 Bitable 直读。"""
    return gates.direct_enabled(_DOMAIN)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存窗口（秒，默认 60；最小 1）。"""
    return gates.int_env(
        "SAFETY_HAZARD_ID_DIRECT_CACHE_TTL_SECONDS",
        DEFAULT_CACHE_TTL_SECONDS,
    )
