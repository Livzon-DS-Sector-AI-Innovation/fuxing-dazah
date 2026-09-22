"""key_risk_op 每日关键风险预报表直读读取器（key_risk_op-direct Ticket 02）。

单表（kind=daily，1585 行级审批台账）全量拉取，照 cert_direct/reader.py 模式：

1. KeyRiskOpRecordsReader 协议：API/Agent 双路径统一注入点，测试用替身
   （替身必须实现 strict 参数，mypy 结构化检查口径）。
2. KeyRiskOpBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   镜像语义复刻——「已删除」申请状态的行排除、report_no 空兜底 BT-xx；
   strict 两态：False（查询/统计容错：分页中断返回已拉部分）、
   True（验证比对/编排：失败聚合上抛）。
3. 连接经配置中心 store 解析（direct base token，无 wiki 解析——探针实证）。
4. open_reader() 按 TTL 配置组装 CachedReader（spec §4.2 性能例外）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.key_risk_op_direct.views import (
    KeyRiskOpView,
    is_deleted_mapped,
    sort_like_mirror,
    view_from_mapped,
)
from app.modules.safety.service.key_risk_operation_report import (
    KeyRiskOperationReportService,
)

__all__ = [
    "KeyRiskOpRecordsReader",
    "KeyRiskOpBitableReader",
    "open_reader",
]


@runtime_checkable
class KeyRiskOpRecordsReader(Protocol):
    """域级读取协议：一次调用返回全量活行视图（对齐镜像 repo 查询基面）。

    strict 语义照 cert（默认 False）：查询/统计容错（分页中断返回已拉部分），
    验证比对/编排显式传 strict=True（失败上抛）。
    """

    async def fetch_all(self, *, strict: bool = False) -> list[KeyRiskOpView]: ...


class KeyRiskOpBitableReader:
    """总表直读读取器真实实现（单表全量；client 可注入，测试零真机依赖）。"""

    def __init__(
        self,
        client: bd_reader.BitablePageClient,
        *,
        table_id: str | None = None,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    ) -> None:
        self._client = client
        self._table_id = table_id
        self._page_size = page_size

    async def fetch_all(self, *, strict: bool = False) -> list[KeyRiskOpView]:
        """全量拉取 → 逐行成视图（已删除排除/兜底与镜像同口径）→ 镜像口径排序。"""
        records = await bd_reader.fetch_all_records(
            self._client,
            table_id=self._table_id,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[KeyRiskOpView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            mapped = KeyRiskOperationReportService.map_bitable_fields(r.get("fields") or {})
            if is_deleted_mapped(mapped):  # 「已删除」行不入镜像，直读同样排除
                continue
            views.append(view_from_mapped(record_id, mapped))  # 一次映射复用
        return sort_like_mirror(views)


_shared_reader: KeyRiskOpRecordsReader | None = None


def open_reader(
    *,
    page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
) -> KeyRiskOpRecordsReader:
    """真实组装（进程内单例）：配置中心解析连接 + TTL 缓存层。

    单例使 TTL 缓存跨调用方生效（service/API/Agent 共享同一缓存窗口）；
    直读模式无写路径，TTL 过期即刷新，无需失效逻辑。
    registry 域 key 为小写 "key_risk_op"（gates 的 DOMAIN_KEY_RISK_OP 仅用于
    环境变量名）。未配置/停用抛 BitableConfigError。page_size/TTL 仅首次创建生效
    （单例；当前调用方全用默认值）。
    """
    global _shared_reader
    if _shared_reader is None:
        from app.modules.safety.service.key_risk_op_direct.cache import CachedReader
        from app.modules.safety.service.key_risk_op_direct.config import (
            cache_ttl_seconds,
        )

        client = bd_reader.resolve_client("key_risk_op", "daily")
        inner = KeyRiskOpBitableReader(client, page_size=page_size)
        _shared_reader = CachedReader(inner, ttl_seconds=cache_ttl_seconds())
    return _shared_reader
