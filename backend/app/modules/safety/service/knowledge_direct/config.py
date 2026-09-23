"""knowledge 直读开关（全默认关）。

本域仅 DIRECT 一个开关（spec §4 D2——§4.7 EVENT_SYNC 拆层前提与源码不符：
handler 无「建 chunk」段，chunk 重建在爬虫 service 显式触发且读镜像行）：

- 不设 EVENT_SYNC 开关：镜像承重（RAG 入库读镜像行、图谱重建、清单页多源
  并集），knowledge 不退订，事件链路不可关也无闸门可言；
- 不设 WRITEBACK 开关：article_no 回写是 handler 既有行为（列缺失时静默跳过，
  建列后自动生效），不随 DIRECT 切换；
- 无 SYNC_JOB（本域无定时任务）；TTL 缓存 60s（性能例外条款触发：探针 817+12 行
  双表并发实测冷 2.30-2.88s/热 3.10s 超 2s 线，key_risk_op 先例，见 cache.py）。
"""

from __future__ import annotations

from app.modules.safety.service.bitable_direct import gates

_DOMAIN = gates.DOMAIN_KNOWLEDGE

DEFAULT_CACHE_TTL_SECONDS = 60


def direct_enabled() -> bool:
    """直读总开关（默认关闭）：Agent query_latest_regulations 走两表直读。"""
    return gates.direct_enabled(_DOMAIN)


def cache_ttl_seconds() -> int:
    """直读视图进程内 TTL 缓存窗口（秒，默认 60；最小 1）。"""
    return gates.int_env(
        "SAFETY_KNOWLEDGE_DIRECT_CACHE_TTL_SECONDS",
        DEFAULT_CACHE_TTL_SECONDS,
    )
