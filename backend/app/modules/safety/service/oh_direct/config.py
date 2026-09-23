"""oh 直读开关（全默认关）。

本域仅 DIRECT 一个开关（spec D2——§4.10 一期口径），**只切换
query_oh_hazard_factors 一个工具**：

- 不设 EVENT_SYNC 开关：单文档 6 表共用一个 drive 订阅且整体不可退订——
  4 表事件是 AI 工作流/业务联动驱动器（体检 AI 解析、人员汇总表回填、
  转岗差异分析、新员工联动建体检 + 在岗状态回写 Bitable，spec §0.2 源码坐实，
  handler `_maybe_*` 钩子族），「仅收敛镜像写入面」无安放点；
- 不设 WRITEBACK 开关：在岗状态/差异分析结论回写是业务流程本体，
  不随 DIRECT 切换；
- query_oh_positions **不接直读分支**（防呆）：oh_positions 镜像表双源承重——
  470 条 source=manual 历史迁移行只在 PG（spec §0.1 终版切面），直读结构性
  丢失；直读链路保留作 verify 盘点与复评基座；
- 无 SYNC_JOB（本域无定时任务，scheduler.py 零改动）；TTL 缓存 60s（D4
  预授权条款：探针单页 0.93s/1.15s，连发可能触 <2s 验收线，msds 2.73s 先例）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_OH

DEFAULT_CACHE_TTL_SECONDS = 60


def direct_enabled() -> bool:
    """直读总开关（默认关闭）：Agent query_oh_hazard_factors 走危害因素
    PPE 表直读（query_oh_positions 不接分支，见模块 docstring）。"""
    return gates.direct_enabled(_DOMAIN)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存窗口（秒，默认 60；最小 1）。"""
    return gates.int_env(
        "SAFETY_OH_DIRECT_CACHE_TTL_SECONDS",
        DEFAULT_CACHE_TTL_SECONDS,
    )
