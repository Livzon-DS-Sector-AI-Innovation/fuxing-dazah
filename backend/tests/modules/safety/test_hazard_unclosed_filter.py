"""隐患列表 rectification_status='unclosed' 特殊值——未闭环过滤（双分支）。

总览驾驶舱 KPI 抽屉需要一次拉全未闭环清单；现有单值等值过滤表达不了
「≠closed」，两分支（直读 page_query / 镜像 repo）同步支持特殊值，
口径与 stats 的 closed（==closed 的补集）严格互补。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import HazardReport
from app.modules.safety.repository import SafetyRepository
from app.modules.safety.service.hazard_direct.page_query import list_ledger


def _view(no: str, rectification_status: str) -> Any:
    """直读视图桩（list_ledger 只摸过滤用到的字段）。"""
    return type(
        "V",
        (),
        {
            "hazard_no": f"HZ-{no}",
            "description": f"描述{no}",
            "status": "open",
            "rectification_status": rectification_status,
            "hazard_type": "unsafe_condition",
            "hazard_level": "general",
            "hazard_category": None,
            "inspection_category": None,
            "department": "一车间",
            "discovered_at": datetime.now(UTC) - timedelta(days=1),
        },
    )()


class TestDirectBranch:
    def test_unclosed_excludes_closed_only(self) -> None:
        views = [
            _view("A", "pending"),
            _view("B", "in_progress"),
            _view("C", "closed"),
        ]
        items, total = list_ledger(views, rectification_status="unclosed")
        assert total == 2
        assert {it.hazard_no for it in items} == {"HZ-A", "HZ-B"}

    def test_concrete_value_still_exact_match(self) -> None:
        views = [_view("A", "pending"), _view("B", "in_progress")]
        items, total = list_ledger(views, rectification_status="in_progress")
        assert total == 1 and items[0].hazard_no == "HZ-B"


class TestMirrorBranch:
    async def test_unclosed_matches_repo_stats_complement(
        self, db_session: AsyncSession
    ) -> None:
        base = dict(
            hazard_type="unsafe_condition",
            hazard_level="general",
            description="unclosed 过滤测试",
            discovered_at=datetime.now(UTC) - timedelta(hours=3),
        )
        db_session.add_all(
            [
                HazardReport(hazard_no="HZ-U1", rectification_status="pending", **base),
                HazardReport(hazard_no="HZ-U2", rectification_status="in_progress", **base),
                HazardReport(hazard_no="HZ-U3", rectification_status="closed", **base),
            ]
        )
        await db_session.flush()

        repo = SafetyRepository(db_session)
        items, total = await repo.get_hazards(rectification_status="unclosed")
        assert {it.hazard_no for it in items} == {"HZ-U1", "HZ-U2"}
        assert total == 2

        stats = await repo.get_hazard_stats()
        # 与 stats 口径互补：unclosed 列表数 = total - closed
        assert total == stats["total"] - stats["closed"]
