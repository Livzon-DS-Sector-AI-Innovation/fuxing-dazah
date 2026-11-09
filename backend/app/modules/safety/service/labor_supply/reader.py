"""labor_supply 直读 reader（仿 visitor_insurance/reader.py 轻量模式）。

数据形态锚定 2026-11-09 实测（tmp/labor-products.ndjson / tmp/labor-positions.ndjson）：
- 劳保用品汇总表：select 列 API 回 ``["值"]``，附件 ``[{file_token,name,size}]``，
  有效期/年为 number（3/102 填写）；
- 岗位对应劳保用品表：防护类型为 lookup 直接回字符串；部门/类别等 select
  列表；user 列（部门安全员/负责人/跟进人）不消费；只保留配备行
  （有劳保用品名称，969 中 254）。

fetch_* 一律 strict（fetch_all_records strict=True，失败上抛由调用方降级）；
缓存语义见 cache.py。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.modules.safety.service.bitable_direct import fields as bd_fields
from app.modules.safety.service.bitable_direct import reader as bd_reader

from .cache import CachedLaborReader  # noqa: F401  (re-export，open_reader 组装)

logger = logging.getLogger(__name__)

# registry 域/kind（bitable_config 配置中心；registry 默认连接即生产表）
DOMAIN = "labor_supply"
KIND_PRODUCT = "product"
KIND_POSITION_MAP = "position_map"

# ── 劳保用品汇总表字段 ──
F_NAME = "劳保用品名称"
F_MODEL = "型号"
F_CATEGORY = "类别"
F_PROTECTION = "防护类型"
F_UNIT = "单位"
F_VENDOR = "厂家"
F_LIFESPAN = "有效期/年"
F_REPORT = "检测报告"
F_MANUAL = "说明书/产品介绍"

PRODUCT_FIELD_NAMES: tuple[str, ...] = (
    F_NAME, F_MODEL, F_CATEGORY, F_PROTECTION, F_UNIT, F_VENDOR,
    F_LIFESPAN, F_REPORT, F_MANUAL,
)

# ── 岗位对应劳保用品表字段（配备行消费面）──
PF_DEPT = "部门"
PF_POSITION = "岗位/工种"
PF_UNIT_WORKSHOP = "单元/车间"
PF_PPE_NAME = "劳保用品名称"
PF_MODEL = "型号"
PF_CATEGORY = "类别"
PF_PROTECTION = "防护类型"
PF_CYCLE = "周期"
PF_PROVISION = "配备情况"
PF_MONITOR_ITEM = "检测项目"
PF_SAMPLE_POINT = "采样点位/对象"

POSITION_FIELD_NAMES: tuple[str, ...] = (
    PF_DEPT, PF_POSITION, PF_UNIT_WORKSHOP, PF_PPE_NAME, PF_MODEL,
    PF_CATEGORY, PF_PROTECTION, PF_CYCLE, PF_PROVISION,
    PF_MONITOR_ITEM, PF_SAMPLE_POINT,
)


@dataclass
class LaborProductView:
    """一条劳保用品目录项的内存视图（不落库、不参与 ORM）。"""

    record_id: str
    name: str = ""
    model: str = ""
    category: str = ""
    protection_type: str = ""
    unit: str = ""
    vendor: str = ""
    lifespan_years: float | None = None
    report_attachments: list[dict[str, Any]] = field(default_factory=list)
    manual_attachments: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_report(self) -> bool:
        return bool(self.report_attachments)

    @property
    def has_manual(self) -> bool:
        return bool(self.manual_attachments)


@dataclass
class PositionStandardView:
    """一条岗位/部门劳保配备标准行的内存视图（只含有用品名称的配备行）。"""

    record_id: str
    department: str = ""
    position: str = ""            # 岗位/工种（49/254 填写，工序级工种）
    unit_workshop: str = ""       # 单元/车间
    name: str = ""                # 劳保用品名称
    model: str = ""
    category: str = ""
    protection_type: str = ""     # lookup 字段：API 直接回字符串
    cycle: str = ""               # 周期（按需/3月/2月/一次性使用/2.5年）
    provision: str = ""           # 配备情况（个人/岗位）
    monitor_item: str = ""        # 检测项目（223/254 填写，74 种危害因素）
    sample_point: str = ""        # 采样点位/对象


def _lifespan(fields: dict[str, Any]) -> float | None:
    raw = fields.get(F_LIFESPAN)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def to_view(record: dict[str, Any]) -> LaborProductView | None:
    """API 记录 → 产品视图；无劳保用品名称的行跳过（目录锚点缺失）。"""
    fields = record.get("fields") or {}
    name = (bd_fields.select(fields, F_NAME) or "").strip()
    if not name:
        return None
    return LaborProductView(
        record_id=str(record.get("record_id") or ""),
        name=name,
        model=bd_fields.select(fields, F_MODEL) or "",
        category=bd_fields.select(fields, F_CATEGORY) or "",
        protection_type=bd_fields.select(fields, F_PROTECTION) or "",
        unit=bd_fields.text(fields, F_UNIT) or "",
        vendor=bd_fields.text(fields, F_VENDOR) or "",
        lifespan_years=_lifespan(fields),
        report_attachments=bd_fields.attachments(fields, F_REPORT),
        manual_attachments=bd_fields.attachments(fields, F_MANUAL),
    )


def to_standard_view(record: dict[str, Any]) -> PositionStandardView | None:
    """API 记录 → 配备标准视图；只保留有劳保用品名称的配备行。

    969 行中约 715 行为纯危害检测矩阵行（有检测项目无用品），不属于配备
    标准，跳过。
    """
    fields = record.get("fields") or {}
    name = (bd_fields.select(fields, PF_PPE_NAME) or "").strip()
    if not name:
        return None
    return PositionStandardView(
        record_id=str(record.get("record_id") or ""),
        department=bd_fields.select(fields, PF_DEPT) or "",
        position=(bd_fields.text(fields, PF_POSITION) or "").strip(),
        unit_workshop=bd_fields.text(fields, PF_UNIT_WORKSHOP) or "",
        name=name,
        model=bd_fields.select(fields, PF_MODEL) or "",
        category=bd_fields.select(fields, PF_CATEGORY) or "",
        protection_type=bd_fields.text(fields, PF_PROTECTION) or "",
        cycle=bd_fields.select(fields, PF_CYCLE) or "",
        provision=bd_fields.select(fields, PF_PROVISION) or "",
        monitor_item=bd_fields.text(fields, PF_MONITOR_ITEM) or "",
        sample_point=bd_fields.text(fields, PF_SAMPLE_POINT) or "",
    )


def filter_products(
    views: list[LaborProductView],
    *,
    keyword: str | None = None,
    category: str | None = None,
    protection_type: str | None = None,
) -> list[LaborProductView]:
    """目录过滤共享口径（API 面板与 agent query_oh(labor) 同一语义）。

    keyword 对名称/型号/厂家/防护类型做包含匹配（大小写不敏感）；
    category / protection_type 精确匹配。
    """
    kw = (keyword or "").strip().lower()
    return [
        v for v in views
        if (not category or v.category == category)
        and (not protection_type or v.protection_type == protection_type)
        and (
            not kw
            or kw in v.name.lower()
            or kw in v.model.lower()
            or kw in v.vendor.lower()
            or kw in v.protection_type.lower()
        )
    ]


def coverage_stats(views: list[LaborProductView]) -> dict[str, Any]:
    """目录数据质量覆盖率（面板统计卡：厂家/检测报告/说明书/有效期）。

    实测基线（2026-11-09，102 行）：厂家 24/102、检测报告 16/102、
    说明书 20/102、有效期 3/102——治理推动用，不在代码里补数。
    """
    total = len(views)
    protection: dict[str, int] = {}
    vendor = report = manual = lifespan = 0
    for v in views:
        if v.protection_type:
            protection[v.protection_type] = protection.get(v.protection_type, 0) + 1
        vendor += 1 if v.vendor else 0
        report += 1 if v.has_report else 0
        manual += 1 if v.has_manual else 0
        lifespan += 1 if v.lifespan_years is not None else 0

    def _pct(filled: int) -> float:
        return round(filled / total, 4) if total else 0.0

    return {
        "total": total,
        "protection_types": protection,
        "vendor_filled": vendor,
        "report_filled": report,
        "manual_filled": manual,
        "lifespan_filled": lifespan,
        "vendor_coverage": _pct(vendor),
        "report_coverage": _pct(report),
        "manual_coverage": _pct(manual),
        "lifespan_coverage": _pct(lifespan),
    }


class LaborSupplyReader:
    """劳保用品直读读取器（page client 可注入，测试用替身）。

    fetch_* 恒 strict：拉取失败上抛（BitableQueryError），由 API/档案按
    源降级；缓存命中/回填见 cache.py。
    """

    def __init__(
        self,
        product_client: bd_reader.BitablePageClient | None = None,
        position_client: bd_reader.BitablePageClient | None = None,
    ) -> None:
        self._product_client = product_client
        self._position_client = position_client

    async def fetch_products(self) -> list[LaborProductView]:
        """全量拉取产品目录（失败上抛，由调用方降级）。"""
        client = self._product_client or bd_reader.resolve_client(DOMAIN, KIND_PRODUCT)
        records = await bd_reader.fetch_all_records(
            client,
            field_names=PRODUCT_FIELD_NAMES,
            strict=True,
        )
        views = [v for v in (to_view(r) for r in records) if v is not None]
        logger.info("劳保用品目录直读完成: records=%d views=%d", len(records), len(views))
        return views

    async def fetch_position_standards(self) -> list[PositionStandardView]:
        """全量拉取配备标准行（源表 969 行，过滤后即配备行；失败上抛）。"""
        client = self._position_client or bd_reader.resolve_client(
            DOMAIN, KIND_POSITION_MAP
        )
        records = await bd_reader.fetch_all_records(
            client,
            field_names=POSITION_FIELD_NAMES,
            strict=True,
        )
        views = [v for v in (to_standard_view(r) for r in records) if v is not None]
        logger.info(
            "劳保配备标准直读完成: records=%d equipped=%d", len(records), len(views)
        )
        return views


def open_reader() -> CachedLaborReader:
    """组装带 TTL 缓存的读取器（模块级组装点，调用方各自缓存实例语义）。"""
    from . import config

    return CachedLaborReader(
        LaborSupplyReader(),
        ttl_seconds=config.cache_ttl_seconds(),
    )
