"""msds 直读开关（全默认关）。

本域仅 DIRECT 一个开关（spec D2——§4.8 重拍板）：

- 不设 EVENT_SYNC 开关：两 drive 订阅均不可关——采集表事件是
  采集→解析→1:N 建行→RAG 全流程触发器；台账表事件在镜像 upsert 后直接调用
  sync_msds_document_to_knowledge（chunk+embedding 重建就在 handler 里），
  「仅收敛镜像写入面」会把 RAG 入库一起切掉（spec §0 结论一，源码坐实）；
- 不设 WRITEBACK 开关：采集→收录 1:N 写面与 AI 解析回写是业务流程本体，
  不随 DIRECT 切换；
- 无 SYNC_JOB（本域无定时任务，scheduler.py 零改动）；TTL 缓存 60s（D4 预授权
  条款触发：探针 1.01s 但 verify 连发全量实测 2.73s 超线，见 cache.py）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_MSDS

DEFAULT_CACHE_TTL_SECONDS = 60


def direct_enabled() -> bool:
    """直读总开关（默认关闭）：Agent query_msds_documents 走台账表直读。"""
    return gates.direct_enabled(_DOMAIN)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存窗口（秒，默认 60；最小 1）。"""
    return gates.int_env(
        "SAFETY_MSDS_DIRECT_CACHE_TTL_SECONDS",
        DEFAULT_CACHE_TTL_SECONDS,
    )
