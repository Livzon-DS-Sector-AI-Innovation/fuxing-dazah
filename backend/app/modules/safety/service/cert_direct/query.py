"""cert 直读查询函数（cert-direct）。

镜像 CertWarningService.get_warnings / get_summary 的引擎派生口径，
数据源换成注入式 reader 的视图对象（内存过滤/分页，引擎零改动）；
summary 计数复用 CertWarningService._build_summary（口径单一来源）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.safety.schemas.cert_warnings import (
    CertWarningDetail,
    CertWarningSummary,
    WarningLevel,
)
from app.modules.safety.service.cert_direct.reader import (
    CertRecordsReader,
    CertWarningView,
)
from app.modules.safety.service.cert_warning import (
    CertWarningEngine,
    CertWarningService,
    WarningResult,
)


@dataclass(frozen=True)
class DerivedCertWarning:
    """视图对象 + 引擎派生结果（预警编排/查询共用的推导层输出）。"""

    view: CertWarningView
    result: WarningResult


async def derive_warnings_direct(
    reader: CertRecordsReader,
    *,
    strict: bool = False,
    today: date | None = None,
) -> list[DerivedCertWarning]:
    """全量直读 → CertWarningEngine 派生（纯推导，不做过滤/分页）。

    strict 语义：预警编排传 True（单表失败聚合上抛 → 调度器补发）；
    查询/统计保持默认 False（容错跳过）。
    """
    views = await reader.get_all_active(strict=strict)
    base = today or date.today()
    return [
        DerivedCertWarning(v, CertWarningEngine.calculate(v, base)) for v in views
    ]


async def get_warnings_direct(
    reader: CertRecordsReader,
    *,
    skip: int = 0,
    limit: int = 20,
    status_level: str | None = None,
    department: str | None = None,
    cert_category: str | None = None,
    days_within: int | None = None,
    strict: bool = False,
    today: date | None = None,
) -> tuple[list[CertWarningDetail], int]:
    """到期明细直读列表（对齐 CertWarningService.get_warnings 的过滤与分页语义）。

    部门/类别先内存过滤，再构建派生 Detail；status_level / days_within 在
    派生后过滤——与镜像「SQL 基础过滤 + Python 派生过滤」的最终口径一致。
    """
    pairs = await derive_warnings_direct(reader, strict=strict, today=today)
    details: list[CertWarningDetail] = []
    for d in pairs:
        if department is not None and d.view.department != department:
            continue
        if cert_category is not None and d.view.cert_category != cert_category:
            continue
        detail = CertWarningDetail.model_validate(d.view)
        detail.current_node = d.result.current_node
        detail.deadline = d.result.deadline
        detail.remaining_days = d.result.remaining_days
        detail.status_level = WarningLevel(d.result.status)
        detail.suggestion = d.result.suggestion
        details.append(detail)
    if status_level:
        details = [x for x in details if x.status_level == status_level]
    if days_within is not None:
        details = [
            x for x in details
            if x.remaining_days is not None and x.remaining_days <= days_within
        ]
    total = len(details)
    return details[skip:skip + limit], total


async def get_summary_direct(
    reader: CertRecordsReader,
    *,
    department: str | None = None,
    cert_category: str | None = None,
    strict: bool = False,
    today: date | None = None,
) -> CertWarningSummary:
    """汇总直读（6 档人数 + by_category + by_event，计数复用镜像实现）。"""
    pairs = await derive_warnings_direct(reader, strict=strict, today=today)
    filtered = [
        d for d in pairs
        if (department is None or d.view.department == department)
        and (cert_category is None or d.view.cert_category == cert_category)
    ]
    return CertWarningService.build_summary(
        [(d.view, d.result) for d in filtered]
    )
