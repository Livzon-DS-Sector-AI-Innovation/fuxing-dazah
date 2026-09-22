"""emergency_drill 主表直读读取器（Ticket 02）。

单表（kind=main，探针 112 行）全量拉取，照 contractor_admission_direct/reader.py 模式：

1. EmergencyDrillRecordsReader 协议：API/Agent 双路径统一注入点，测试用替身
   （替身必须实现 strict 参数，mypy 结构化检查口径）。
2. EmergencyDrillBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   本表无软删除语义（Bitable 行删除即物理消失，镜像 is_deleted 仅存在于平台侧），
   直读天然不含已删行。
3. strict 两态：False（查询/统计容错：分页中断返回已拉部分）、
   True（验证比对/编排：失败聚合上抛）。
4. open_reader() 每次组装新实例（spec §4.1：无 TTL 缓存，探针 112 行单页
   0.96s <2s；无 key_risk_op 的单例缓存约束）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.emergency_drill_direct.views import (
    EmergencyDrillRecordView,
    view_from_record_id,
)

__all__ = [
    "EmergencyDrillBitableReader",
    "EmergencyDrillRecordsReader",
    "open_reader",
]


@runtime_checkable
class EmergencyDrillRecordsReader(Protocol):
    """域级读取协议：一次调用返回全量活行视图（对齐镜像 service 查询基面）。

    strict 语义照前域（默认 False）：查询/统计容错（分页中断返回已拉部分），
    验证比对显式传 strict=True（失败上抛）。
    """

    async def fetch_all(self, *, strict: bool = False) -> list[EmergencyDrillRecordView]: ...


class EmergencyDrillBitableReader:
    """演练主表直读读取器真实实现（单表全量；client 可注入，测试零真机依赖）。"""

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

    async def fetch_all(self, *, strict: bool = False) -> list[EmergencyDrillRecordView]:
        """全量拉取 → 逐行成视图（映射复用 handler 纯函数 + 附件路径推算）。"""
        records = await bd_reader.fetch_all_records(
            self._client,
            table_id=self._table_id,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[EmergencyDrillRecordView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            views.append(view_from_record_id(record_id, r.get("fields") or {}))
        return views


def open_reader() -> EmergencyDrillRecordsReader:
    """真实组装（每次新实例——无 TTL 缓存；工厂形态对齐前域命名惯例）。

    registry 域 key 为小写 "emergency_drill"，kind="main"（统计表）。
    未配置/停用抛 BitableConfigError。
    """
    client = bd_reader.resolve_client("emergency_drill", "main")
    return EmergencyDrillBitableReader(client)
