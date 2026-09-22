"""contractor_admission 直读读取器（Ticket 03）。

单表（kind=admission，109 行级材料台账）全量拉取，照 key_risk_op_direct/reader.py 模式：

1. ContractorAdmissionRecordsReader 协议：API/Agent 双路径统一注入点，测试用替身
   （替身必须实现 strict 参数，mypy 结构化检查口径）。
2. ContractorAdmissionBitableReader：底座批量 search 分页全量（禁止逐条 get_record）；
   本表无「已删除」选择态、无编号兜底（map_fields 语义为纯映射），软删除仅存在于
   镜像侧——Bitable 行删除即物理消失，直读天然不含。
3. strict 两态：False（查询/统计容错：分页中断返回已拉部分）、
   True（验证比对/编排：失败聚合上抛）。
4. build_reader() 每次组装新实例（D3 拍板：无 TTL 缓存，无 open_reader 单例约束）。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader
from app.modules.safety.service.contractor_admission_direct.views import (
    ContractorAdmissionView,
    view_from_record_id,
)

__all__ = [
    "ContractorAdmissionBitableReader",
    "ContractorAdmissionRecordsReader",
    "open_reader",
]


@runtime_checkable
class ContractorAdmissionRecordsReader(Protocol):
    """域级读取协议：一次调用返回全量活行视图（对齐镜像 repo 查询基面）。

    strict 语义照 key_risk_op（默认 False）：查询/统计容错（分页中断返回已拉部分），
    验证比对/编排显式传 strict=True（失败上抛）。
    """

    async def fetch_all(self, *, strict: bool = False) -> list[ContractorAdmissionView]: ...


class ContractorAdmissionBitableReader:
    """相关方准入表直读读取器真实实现（单表全量；client 可注入，测试零真机依赖）。"""

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

    async def fetch_all(self, *, strict: bool = False) -> list[ContractorAdmissionView]:
        """全量拉取 → 逐行成视图（映射复用 map_fields + 派生 AI 态）。"""
        records = await bd_reader.fetch_all_records(
            self._client,
            table_id=self._table_id,
            page_size=self._page_size,
            strict=strict,
        )
        views: list[ContractorAdmissionView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            if not record_id:
                continue
            views.append(view_from_record_id(record_id, r.get("fields") or {}))
        return views


def open_reader() -> ContractorAdmissionRecordsReader:
    """真实组装（每次新实例——D3 拍板无 TTL 缓存，无 key_risk_op 的单例约束；
    与 chemical open_reader 同为工厂形态，仅命名对齐前域惯例）。

    registry 域 key 为小写 "contractor_admission"（gates 的 DOMAIN_CONTRACTOR_ADMISSION
    仅用于环境变量名）。未配置/停用抛 BitableConfigError。
    """
    client = bd_reader.resolve_client("contractor_admission", "admission")
    return ContractorAdmissionBitableReader(client)
