"""cert 直读查询单测（cert-direct Ticket 03）。

覆盖：引擎派生推导层、内存过滤/分页、summary 与镜像路径等价
（FakeRepo 注入 CertWarningService 做跨路径同输入比对）、Detail 序列化。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, cast

from app.modules.safety.schemas.cert_warnings import CertWarningDetail
from app.modules.safety.service.cert_direct.query import (
    derive_warnings_direct,
    get_summary_direct,
    get_warnings_direct,
)
from app.modules.safety.service.cert_direct.reader import CertWarningView
from app.modules.safety.service.cert_warning import CertWarningService


class FakeReader:
    """CertRecordsReader 替身（实现协议全方法含 strict 参数）。"""

    def __init__(self, views: list[CertWarningView]) -> None:
        self._views = views
        self.strict_arg: bool | None = None

    async def get_all_active(self, *, strict: bool = True) -> list[CertWarningView]:
        self.strict_arg = strict
        return list(self._views)


class FakeRepo:
    """PersonCertificateRepository 替身：内存过滤，镜像 repo.get_warnings 口径。"""

    def __init__(self, rows: list[CertWarningView]) -> None:
        self._rows = rows

    async def get_warnings(
        self,
        *,
        department: str | None = None,
        cert_category: str | None = None,
    ) -> tuple[list[CertWarningView], int]:
        rows = [
            r for r in self._rows
            if (department is None or r.department == department)
            and (cert_category is None or r.cert_category == cert_category)
        ]
        return rows, len(rows)


def _view(
    vid: str,
    category: str,
    dept: str,
    *,
    next_review: date | None = None,
) -> CertWarningView:
    return CertWarningView(
        id=vid,
        cert_category=category,
        person_name=f"人-{vid}",
        department=dept,
        next_review_date=next_review,
    )


def _sample_views() -> list[CertWarningView]:
    """urgent(special_op) / normal(special_op) / overdue(guardian_a) / 缺日期(guardian_b)。"""
    today = date.today()
    overdue = _view("overdue", "guardian_a", "质检部")
    overdue.should_renew_date = today - timedelta(days=10)
    return [
        _view("urgent", "special_op", "生产部", next_review=today + timedelta(days=3)),
        _view("normal", "special_op", "生产部", next_review=today + timedelta(days=200)),
        overdue,
        _view("nodate", "guardian_b", "质检部"),
    ]


class TestDeriveWarningsDirect:
    async def test_strict_passthrough(self) -> None:
        reader = FakeReader([])
        await derive_warnings_direct(reader, strict=True)
        assert reader.strict_arg is True

    async def test_default_strict_false_for_query_paths(self) -> None:
        reader = FakeReader([])
        await derive_warnings_direct(reader)
        assert reader.strict_arg is False

    async def test_derives_all_pairs(self) -> None:
        pairs = await derive_warnings_direct(FakeReader(_sample_views()))
        by_id = {p.view.id: p.result.status for p in pairs}
        assert by_id["urgent"] == "urgent"
        assert by_id["normal"] == "normal"
        assert by_id["overdue"] == "overdue"
        assert by_id["nodate"] == "normal"  # 缺日期 → 无法计算预警（镜像同口径）


class TestGetWarningsDirect:
    async def test_filters_department_and_pagination(self) -> None:
        items, total = await get_warnings_direct(
            FakeReader(_sample_views()), department="生产部", limit=1,
        )
        assert total == 2
        assert len(items) == 1
        assert items[0].department == "生产部"

    async def test_filter_status_level_and_days_within(self) -> None:
        items, total = await get_warnings_direct(
            FakeReader(_sample_views()), status_level="urgent",
        )
        assert total == 1
        assert items[0].status_level == "urgent"

        items, total = await get_warnings_direct(
            FakeReader(_sample_views()), days_within=30,
        )
        assert {i.id for i in items} == {"urgent", "overdue"}
        assert total == 2

    async def test_detail_serialized_from_view(self) -> None:
        items, _ = await get_warnings_direct(
            FakeReader(_sample_views()), status_level="urgent",
        )
        d = items[0]
        assert isinstance(d, CertWarningDetail)
        assert d.id == "urgent"  # 直读形态 id 为飞书记录 ID 字符串
        assert d.current_node == "复审"
        assert d.suggestion


class TestGetSummaryDirect:
    async def test_summary_equivalence_with_mirror_path(self) -> None:
        """同一份输入：直读 summary 与镜像 service.get_summary 逐字段相等。"""
        views = _sample_views()
        direct = await get_summary_direct(FakeReader(views))

        service = CertWarningService(cast(Any, None))
        service.repo = FakeRepo(views)  # type: ignore[assignment]
        mirror = await service.get_summary()

        assert direct.model_dump() == mirror.model_dump()

    async def test_summary_counts_all_levels(self) -> None:
        s = await get_summary_direct(FakeReader(_sample_views()))
        assert s.total == 4
        assert s.urgent_count == 1
        assert s.overdue_count == 1
        assert s.normal_count == 2
        assert s.by_category == {
            "special_op": 2, "guardian_a": 1, "guardian_b": 1,
        }
        assert "special_op_复审" in s.by_event
