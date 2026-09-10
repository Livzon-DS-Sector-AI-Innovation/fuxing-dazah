"""许可时长上限 clamp 单测。

规则：统计时长不得超过该票种许可时长（一级动火 8h、受限 24h、临电 360h、登高/高处 72h；
吊装/动土/断路/盲板不设限）；超出按许可上限计，并备注「超出许可上限」。
"""

from __future__ import annotations

from app.modules.safety.schemas.subsidy import SubsidyRecordInput
from app.modules.safety.service.subsidy import SubsidyService

TZ_SUFFIX = "+08:00"


def _rec(op_type, level, start, end, name="测试"):
    return SubsidyRecordInput(
        guardian_name=name,
        guardian_level="A证",
        operation_type=op_type,
        operation_level=level,
        location_content="测试作业",
        start_time=start,
        end_time=end,
        interval_hours="0",
    )


def test_hot_work_level1_over_permit_clamps_to_130():
    """一级动火 8h00m03s → clamp 到 8h → 扣午休 6.5h → 13 单位 130 元。"""
    d = SubsidyService._calc_single(_rec(
        "动火作业", "一级", f"2026-08-31T09:00:00{TZ_SUFFIX}", f"2026-08-31T17:00:03{TZ_SUFFIX}",
    ))
    assert d.subsidy_amount == 130.0
    assert d.billing_units == 13
    assert "超出许可上限" in d.remark


def test_hot_work_level1_at_8h_not_over():
    """一级动火恰好 8h（扣午休 6.5h）→ 13 单位 130，不触发超出许可。"""
    d = SubsidyService._calc_single(_rec(
        "动火作业", "一级", f"2026-08-31T09:00:00{TZ_SUFFIX}", f"2026-08-31T17:00:00{TZ_SUFFIX}",
    ))
    assert d.subsidy_amount == 130.0
    assert "超出许可上限" not in d.remark


def test_hot_work_level2_over_8h_continuous_only_when_valid_exceeds_8h():
    """二级动火：连续判定基于扣除午休后的有效时长。

    09:00-18:00（总9h，扣午休7.5h，有效7.5h<8h）→ 非连续，按半小时 15×8=120 元。
    08:00-20:00（总12h，扣午休10.5h，有效10.5h>8h）→ 连续，按天 120 元。
    """
    d = SubsidyService._calc_single(_rec(
        "动火作业", "二级", f"2026-08-31T09:00:00{TZ_SUFFIX}", f"2026-08-31T18:00:00{TZ_SUFFIX}",
    ))
    assert d.subsidy_amount == 120.0
    assert d.billing_unit_label == "半小时"  # 有效 7.5h<8h → 非连续
    assert "连续作业按天" not in d.remark

    d2 = SubsidyService._calc_single(_rec(
        "动火作业", "二级", f"2026-08-31T08:00:00{TZ_SUFFIX}", f"2026-08-31T20:00:00{TZ_SUFFIX}",
    ))
    assert d2.billing_unit_label == "天"
    assert d2.subsidy_amount == 120.0
    assert "连续作业按天" in d2.remark


def test_height_work_level1_over_permit_clamps():
    """登高一级 128h → 许可 72h → clamp 72h → 连续按天 70 元。"""
    d = SubsidyService._calc_single(_rec(
        "登高作业", "一级", f"2026-08-01T09:00:00{TZ_SUFFIX}", f"2026-08-06T12:00:00{TZ_SUFFIX}",
    ))
    assert d.subsidy_amount == 70.0
    assert "超出许可上限" in d.remark


def test_confined_space_over_permit_clamps():
    """受限空间 30h → 许可 24h → clamp 24h（默认 10 元/半小时，仍按调后计）。"""
    d = SubsidyService._calc_single(_rec(
        "受限空间", "", f"2026-08-01T08:00:00{TZ_SUFFIX}", f"2026-08-02T14:00:00{TZ_SUFFIX}",
    ))
    assert d.unit_price == 10.0
    assert "超出许可上限" in d.remark


def test_lifting_no_permit_unaffected():
    """吊装作业不设许可上限，仅按级（一级 5 元/半小时），超 8h 不 clamp。"""
    d = SubsidyService._calc_single(_rec(
        "吊装作业", "一级", f"2026-08-01T08:00:00{TZ_SUFFIX}", f"2026-08-01T18:00:00{TZ_SUFFIX}",
    ))
    assert d.unit_price == 5.0
    assert "超出许可上限" not in d.remark


def test_ferment_confined_space_flat_30_per_ticket():
    """发酵工程部受限空间：按张 30 元（不按时长、不看许可/连续）。"""
    d = SubsidyService._calc_single(_rec(
        "受限空间", "", f"2026-08-01T08:00:00{TZ_SUFFIX}", f"2026-08-01T18:00:00{TZ_SUFFIX}",
        name="发酵张三",
    ).model_copy(update={"department": "发酵工程部"}))
    assert d.unit_price == 30.0
    assert d.billing_unit_label == "张"
    assert d.subsidy_amount == 30.0
    assert "按张计费" in d.remark
    # 其它部门受限空间仍按半小时 10 元
    d2 = SubsidyService._calc_single(_rec(
        "受限空间", "", f"2026-08-01T08:00:00{TZ_SUFFIX}", f"2026-08-01T11:00:00{TZ_SUFFIX}",
    ))
    assert d2.unit_price == 10.0
    assert d2.billing_unit_label == "半小时"


