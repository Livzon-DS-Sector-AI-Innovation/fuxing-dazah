"""既有 cert 预警引擎周期校准回归 —— 拍板①后 _guardian_node 重算口径 1/2/3 年。

行为级断言（不断言常量本身）：renewed_date 非空 → 第一次复审节点 = renewed + 1 年。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.modules.safety.service.cert_warning import CertWarningEngine


@dataclass
class _Rec:
    cert_category: str = "guardian_a"
    person_name: str = "张三"
    review_frequency: str | None = None
    next_review_date: date | None = None
    first_review_deadline: date | None = None
    second_review_deadline: date | None = None
    should_renew_date: date | None = None
    renewed_date: date | None = None
    issue_date: date | None = None


def test_legacy_engine_renewed_recalc_uses_one_year() -> None:
    """已换证 → 下一第一次复审 = renewed + 1 年（2026-11-04 校准，原占位 3 年）。"""
    rec = _Rec(renewed_date=date(2026, 2, 1))
    res = CertWarningEngine.calculate(rec, today=date(2026, 6, 1))
    assert res.current_node == "第一次复审"
    assert res.deadline == date(2027, 2, 1)
