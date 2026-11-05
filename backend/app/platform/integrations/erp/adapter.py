"""ERP 集成通道适配器（三期 M8，设计 §六 三档）。

A 档（人工导出文件上传）已实装：warehouse/hardware/erp_import.py
（xlsx/csv 解析 + erp_doc_no 幂等 + 列映射 runtime 可配置）。

本模块只留 B/C 档 adapter 接口骨架——ERP 样例文件/接口未到位（财务吴丽文/
何品红在办），接口形状先定，到位后实现子类即可接入 import_erp_file 同一
下游（零迁移：单据模型同一套，source=erp_import 区分）：

- B 档（定时批量取文件）：实现 fetch_files() 从共享目录/SFTP/邮件附件拉取
  导出文件字节流，由 scheduled.py 定时任务驱动；
- C 档（API 直连）：实现 fetch_api_docs() 分页拉取 ERP 入库单 JSON，
  经 normalize_to_rows() 转为与 A 档解析器同构的行结构。
"""

from __future__ import annotations

from typing import Any, Protocol


class ErpFileRow(Protocol):
    """A/B/C 三档统一的行结构协议（与 erp_import.ErpRow 对齐）。"""

    doc_no: str
    date: str | None
    supplier: str | None
    material_code: str | None
    name: str
    spec: str | None
    quantity: Any
    unit: str | None
    dept: str | None


class ErpAdapter(Protocol):
    """ERP 数据源适配器接口（B/C 档实现此协议；A 档文件上传不经此）。"""

    name: str

    async def fetch_files(self) -> list[tuple[str, bytes]]:
        """B 档：拉取待导入文件 [(filename, bytes)]。未实现。"""
        ...

    async def fetch_api_docs(self, *, since: str | None = None) -> list[dict[str, Any]]:
        """C 档：增量拉取 ERP 入库单原始 JSON。未实现。"""
        ...


def normalize_api_docs(docs: list[dict[str, Any]]) -> list[ErpFileRow]:
    """C 档 JSON → 统一行结构（字段映射待 ERP 接口文档到位后实现）。"""
    raise NotImplementedError("C 档 API 直连未实现（ERP 样例/接口文档未到位，保留通道）")
