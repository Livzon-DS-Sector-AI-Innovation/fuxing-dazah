"""S1 体系标准符合性核查 — 周期定格快照 ORM（二期）。

DESIGN §3.3：周期末 snapshot 落 DB，绩效评定/标准化自评/迎检直接导出，
不再现场重算。行冗余快照条款文本/目标值/依据/要素/部门等清单列——
清单后续修订（含删行/废弃）不篡改已定格历史；唯一 (standard_no, period_key)
（period_key 含年份，跨年同编号不冲突），重复定格=upsert 幂等。

status 六态：achieved / missed / no_data / manual_done / manual_missed 为终态，
in_progress 仅存在于年度/半年项的季度中期快照（终版定格 upsert 覆盖）。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel

SNAP_ACHIEVED = "achieved"
SNAP_MISSED = "missed"
SNAP_NO_DATA = "no_data"
SNAP_MANUAL_DONE = "manual_done"
SNAP_MANUAL_MISSED = "manual_missed"
# 中间态：年度/半年项季度中期快照（窗口未满 judge 给 in_progress），终版覆盖
SNAP_IN_PROGRESS = "in_progress"

SNAP_STATUSES = (
    SNAP_ACHIEVED, SNAP_MISSED, SNAP_NO_DATA,
    SNAP_MANUAL_DONE, SNAP_MANUAL_MISSED, SNAP_IN_PROGRESS,
)


class StandardCheckSnapshot(BaseModel):
    """一次周期定格的一行（标准 × 周期 = 唯一）。"""

    __tablename__ = "standard_check_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "standard_no", "period_key",
            name="uq_standard_check_snapshots_no_period",
        ),
        Index("ix_standard_check_snapshots_year_period", "year", "period_key"),
        {"schema": "safety"},
    )

    standard_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="标准编号（S1-001 / D6-01，人编稳定锚点）"
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, comment="定格对象年")
    period_key: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="2026 / 2026H1 / 2026-Q3 / 2026-09",
    )
    metric_key: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="空=人工核查项"
    )
    actual_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(8), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
        comment="证据引用快照：{window, items, no_data_reason}",
    )
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="定格时刻（终版覆盖时刷新）"
    )

    # ── 清单行冗余快照（防清单后续修订篡改历史）──
    clause: Mapped[str] = mapped_column(Text, nullable=False, comment="标准条款快照")
    basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    element: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period: Mapped[str | None] = mapped_column(String(16), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    department: Mapped[list[str] | None] = mapped_column(
        JSONB, nullable=True, comment="责任部门列表快照"
    )
    owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manual_result: Mapped[str | None] = mapped_column(String(8), nullable=True)
    last_done_on: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="长周期项锚点快照"
    )
    actual_display: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="定格完成值展示（如 2次 / 95%）"
    )
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="判定附注（无数据原因/未核查提示）"
    )
