"""特殊作业日报风险统计直读分支测试（get_stats 双路径）。

背景（2026-10-26 修复）：直读改造退役镜像同步后，页面「今日作业/高/中/低风险」
卡走的 ``get_stats`` 仍查已停供的 DB 镜像表，恒为 0——而日报/速递卡是直读现算
（同一天速递 21 项·高 7，页面却 0）。修复＝get_stats 补直读分支，与速递同源
（``fetch_day_views`` + ``daily_risk_level``/``is_excluded``），镜像分支保留作回滚。
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.special_op_direct import bitable_repo
from app.modules.safety.service.special_op_direct import config as direct_config
from app.modules.safety.service.special_operation_daily_report import (
    SpecialOperationDailyReportService,
)

DAY = date(2026, 9, 11)


def _view(level: str | None, *, excluded: bool = False, seq: int = 0) -> bitable_repo.SpecialOpView:
    return bitable_repo.SpecialOpView(
        record_id=f"rec{seq}", daily_risk_level=level, is_excluded=excluded,
    )


async def test_get_stats_direct_branch(monkeypatch) -> None:
    """直读开启：与速递同源现算——excluded 行不计入，total=有效行数。"""
    monkeypatch.setattr(direct_config, "direct_enabled", lambda: True)

    async def fake_fetch(target_date: date, client=None):
        assert target_date == DAY
        return [
            _view("high", seq=1),
            _view("high", seq=2),
            _view("medium", seq=3),
            _view("low", seq=4),
            _view(None, excluded=True, seq=5),  # 已排除（撤回等）不入统计
        ]

    monkeypatch.setattr(bitable_repo, "fetch_day_views", fake_fetch)

    service = SpecialOperationDailyReportService(session=None)  # 直读分支不碰 DB
    stats = await service.get_stats(DAY)

    assert stats == {
        "date": "2026-09-11",
        "total": 4,
        "high": 2,
        "medium": 1,
        "low": 1,
    }


async def test_get_stats_mirror_fallback_when_direct_disabled(monkeypatch) -> None:
    """直读关闭：回落镜像分支（回滚路径保持原行为）。"""
    monkeypatch.setattr(direct_config, "direct_enabled", lambda: False)

    service = SpecialOperationDailyReportService(session=None)

    class _Row:
        daily_risk_level = "high"

    async def fake_reports(target_date: date, include_excluded: bool = False):
        assert include_excluded is False
        return [_Row(), _Row(), _Row()]

    monkeypatch.setattr(service, "get_reports_by_date", fake_reports)

    stats = await service.get_stats(DAY)

    assert stats == {"date": "2026-09-11", "total": 3, "high": 3, "medium": 0, "low": 0}
