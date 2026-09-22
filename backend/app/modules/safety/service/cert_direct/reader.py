"""cert 持证台账直读模式：视图对象与注入式读取器（cert-direct）。

照搬 central_alarm/reader.py 的模式，差异在本域是 **3 表全生命周期在册数据**：

1. CertWarningView：字段名与 PersonCertificate ORM 完全同名（审计/软删列除外，
   由单测固化契约），CertWarningEngine 纯函数直接吃本对象零改动；id 用飞书记录 ID。
2. 字段映射复用 feishu/cert_bitable.py 既有映射纯函数（与镜像 upsert 同一口径，
   含「无姓名记录跳过」）；cert_category 由 table_id → kind 决定。
3. CertRecordsReader：协议，预警编排 / query 接受注入，测试用替身。

cert 为纯只读域：直读路径对 Bitable 零写入（已拍板 renew 直读下禁用）。
Bitable 读 API 直接接受 wiki token，读取路径无需 wiki→base 解析。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, runtime_checkable

from app.modules.safety.service.bitable_direct import reader as bd_reader

logger = logging.getLogger(__name__)

# cert 域 3 kind（registry key="cert"；special_op 独立 app_token，监护人 A/B 共用）
_KINDS: tuple[str, ...] = ("special_op", "guardian_a", "guardian_b")

__all__ = [
    "CertWarningView",
    "CertRecordsReader",
    "CertBitableReader",
    "open_reader",
    "view_from_mapped",
    "sort_like_mirror",
]


@dataclass
class CertWarningView:
    """人员持证记录的内存视图对象（不落库、不参与 ORM）。

    字段名与 PersonCertificate 同名；id 为飞书记录 ID（直读形态），
    created_at/updated_at 直读侧恒 None（Bitable 无对应字段，仅排序契约占位）。
    """

    # 标识与元数据
    id: str = ""
    feishu_record_id: str | None = None
    source: str = "bitable"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # 证件类别与人员
    cert_category: str = ""
    person_name: str = ""
    department: str | None = None
    employee_no: str | None = None
    phone: str | None = None

    # 证件通用
    operation_type: str | None = None
    project: str | None = None
    certificate_no: str | None = None
    issue_date: date | None = None
    certificate_file_path: str | None = None

    # 特种作业证专用（复审周期）
    next_review_date: date | None = None
    review_frequency: str | None = None

    # 监护人 A/B 证专用（多节点 + 换证周期）
    first_review_deadline: date | None = None
    second_review_deadline: date | None = None
    should_renew_date: date | None = None
    renewed_date: date | None = None

    notes: str | None = None


@runtime_checkable
class CertRecordsReader(Protocol):
    """域级读取协议：一次调用返回全量活行视图（对齐镜像 repo.get_all_active）。

    strict 语义照 central_alarm（默认 False）：查询/统计容错跳过单表失败，
    预警编排显式传 strict=True（任一表失败聚合上抛）。
    """

    async def get_all_active(self, *, strict: bool = False) -> list[CertWarningView]: ...


def view_from_mapped(
    record_id: str, mapped: dict[str, Any] | None
) -> CertWarningView | None:
    """镜像映射纯函数产出的 dict → 视图对象。

    mapped 为 None（记录无姓名，cert_bitable 映射函数跳过的脏数据）时透传 None，
    与镜像 upsert 的跳过行为一致。
    """
    if mapped is None:
        return None
    return CertWarningView(
        id=record_id,
        feishu_record_id=record_id,
        **mapped,
    )


def sort_like_mirror(views: list[CertWarningView]) -> list[CertWarningView]:
    """按镜像 repo.get_all_active 的 ORDER BY 契约内存排序（返回新列表）。

    对应 SQL（08:00 推送路径）：cert_category ASC, next_review_date ASC NULLS LAST,
    should_renew_date ASC NULLS LAST。
    注意：repo.get_warnings（API 列表路径）额外有 created_at DESC 第四键，Bitable
    无时间戳字段无法复现——直读侧该键天然 no-op，同键组内按表格顺序（稳定排序），
    双路径 tie 组内行序差异属预期（verify 脚本已做行序归一比对）。
    多趟稳定排序（Python sort 稳定性保证），从最低优先级键排到最高。
    """
    rows = list(views)
    # should_renew_date ASC NULLS LAST
    rows.sort(key=lambda v: (v.should_renew_date is None, v.should_renew_date or date.min))
    # next_review_date ASC NULLS LAST
    rows.sort(key=lambda v: (v.next_review_date is None, v.next_review_date or date.min))
    # cert_category ASC
    rows.sort(key=lambda v: v.cert_category)
    return rows


# ── 真实读取器（3 表全量并发；cert 是全生命周期在册数据，无日期窗口，Q6=A 全量）──


class CertBitableReader:
    """cert 直读读取器真实实现。

    IO 收口在注入的 BitablePageClient（kind → client，监护人 A/B 共用 app_token
    仍是两个独立 client 实例）；kind → 表配置可注入（测试零真机依赖），
    缺省时由 open_reader() 从配置中心组装。
    """

    def __init__(
        self,
        clients: Mapping[str, bd_reader.BitablePageClient],
        *,
        tables: dict[str, tuple[str, str]] | None = None,
        page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
        concurrency: int = 3,
    ) -> None:
        self._clients = clients
        self._tables = tables
        self._page_size = page_size
        self._sem = asyncio.Semaphore(concurrency)

    async def _tables_by_kind(self) -> dict[str, tuple[str, str]]:
        """kind → (app_token, table_id)（注入优先，缺省读配置中心）。"""
        if self._tables is not None:
            return self._tables
        from app.modules.safety.feishu.cert_bitable import cert_tables

        return cert_tables()

    async def _fetch_one_kind(self, kind: str, table_id: str) -> list[CertWarningView]:
        """单 kind 全量拉取 → 映射 → 视图列表（无姓名脏数据跳过，与镜像一致）。"""
        client = self._clients.get(kind)
        if client is None:
            raise RuntimeError(f"cert 直读未注入客户端: kind={kind}")
        async with self._sem:
            records = await bd_reader.fetch_all_records(
                client,
                table_id=table_id,
                page_size=self._page_size,
            )
        from app.modules.safety.feishu.cert_bitable import (
            map_guardian_cert_fields,
            map_special_op_cert_fields,
        )

        views: list[CertWarningView] = []
        for r in records:
            record_id = str(r.get("record_id") or "")
            fields = r.get("fields") or {}
            if kind == "special_op":
                mapped = map_special_op_cert_fields(fields)
            else:
                mapped = map_guardian_cert_fields(fields, kind)
            view = view_from_mapped(record_id, mapped)
            if view is not None:
                views.append(view)
        return views

    async def get_all_active(self, *, strict: bool = False) -> list[CertWarningView]:
        """跨 3 kind 并发全量拉取，镜像口径排序后返回。

        strict=False（默认，查询/统计用）：单 kind 失败跳过并告警，返回部分结果；
        strict=True（预警编排显式传入）：任一 kind 失败聚合上抛 RuntimeError——
        调度器标 failed 走补发重试，绝不让预警静默缺整个证件类别。
        """
        tables = await self._tables_by_kind()
        kinds = [k for k in _KINDS if k in tables]
        results = await asyncio.gather(
            *[self._fetch_one_kind(k, tables[k][1]) for k in kinds],
            return_exceptions=True,
        )
        views: list[CertWarningView] = []
        failures: list[str] = []
        for kind, result in zip(kinds, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("cert 直读单表拉取失败 kind=%s: %r", kind, result)
                failures.append(kind)
                continue
            views.extend(result)
        if strict and failures:
            raise RuntimeError(
                f"cert 直读单表拉取失败（strict）: {', '.join(failures)}"
            )
        return sort_like_mirror(views)


def open_reader(
    *,
    page_size: int = bd_reader.DEFAULT_PAGE_SIZE,
    concurrency: int = 3,
) -> CertBitableReader:
    """真实组装：按配置中心解析 3 kind 客户端（未配置/停用抛 BitableConfigError）。

    registry 域 key 为小写 "cert"（gates 的 DOMAIN_CERT 仅用于环境变量名）。
    """
    from app.modules.safety.feishu.cert_bitable import cert_tables

    clients = {
        kind: bd_reader.resolve_client("cert", kind)
        for kind in _KINDS
        if kind in cert_tables()
    }
    return CertBitableReader(clients, page_size=page_size, concurrency=concurrency)
