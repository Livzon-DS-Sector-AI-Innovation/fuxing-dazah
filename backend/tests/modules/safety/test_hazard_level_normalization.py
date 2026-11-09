"""T01(D2) 人工「隐患级别」类型对齐 — 归一行为单测（RED 先行）。

三个人工级别入口全部收敛到 field_authority.normalize_level_manual
（多值取最高严重度、中英文互通、未知值不升级）：
- 督办等级计算规则 1（calculate_supervision_level：多值串此前不命中元组 → 漏红警）
- 镜像事件同步字段映射（_map_bitable_fields：多值串此前静默降级 general）
- Pydantic 写入校验器（HazardReportBase.hazard_level_manual：多值串此前原样透传）
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from app.modules.safety.models import HazardReport
from app.modules.safety.schemas.hazards import HazardReportBase
from app.modules.safety.service.hazard_supervision import calculate_supervision_level


def _hazard(**kw) -> HazardReport:
    base: dict = dict(
        hazard_no="HZ-T01-1",
        description="测试隐患",
        hazard_level_manual=None,
        rectification_status="pending",
        status="pending",
        discovered_at=datetime.now(UTC),
    )
    base.update(kw)
    return HazardReport(**base)


# ── 督办规则 1：入口归一 ──────────────────────────────────────


def test_rule1_multivalue_manual_level_triggers_red() -> None:
    """多选串『较大隐患, 一般隐患』（全表实测 1 条）必须命中红色预警。"""
    assert (
        calculate_supervision_level(_hazard(hazard_level_manual="较大隐患, 一般隐患"))
        == "红色预警"
    )


def test_rule1_cn_and_en_single_values_keep_behavior() -> None:
    assert calculate_supervision_level(_hazard(hazard_level_manual="重大隐患")) == "红色预警"
    assert calculate_supervision_level(_hazard(hazard_level_manual="serious")) == "红色预警"


def test_rule1_general_recent_stays_normal() -> None:
    assert calculate_supervision_level(_hazard(hazard_level_manual="一般隐患")) == "一般预警"


def test_rule0_closed_overrides_level() -> None:
    assert (
        calculate_supervision_level(
            _hazard(hazard_level_manual="重大隐患", rectification_status="closed")
        )
        == "closed"
    )


def test_rule2_over_30_days_triggers_red() -> None:
    old = datetime.combine(
        date.today() - timedelta(days=31), datetime.min.time(), tzinfo=UTC
    )
    assert (
        calculate_supervision_level(_hazard(discovered_at=old, hazard_level_manual="general"))
        == "红色预警"
    )


def test_rule1_unknown_level_does_not_trigger_red() -> None:
    """未知选项不升级（安全侧只对已知枚举取最高严重度）。"""
    assert calculate_supervision_level(_hazard(hazard_level_manual="特殊级")) == "一般预警"


# ── 镜像事件同步：多值不再静默降级 ────────────────────────────


def test_mirror_mapping_multivalue_not_downgraded() -> None:
    from app.modules.safety.feishu.bitable_handler import _map_bitable_fields

    mapped = _map_bitable_fields({"隐患级别": ["较大隐患", "一般隐患"]})
    assert mapped["hazard_level_manual"] == "serious"


def test_mirror_mapping_single_value_unchanged() -> None:
    from app.modules.safety.feishu.bitable_handler import _map_bitable_fields

    assert _map_bitable_fields({"隐患级别": "一般隐患"})["hazard_level_manual"] == "general"
    assert _map_bitable_fields({"隐患级别": ["重大隐患"]})["hazard_level_manual"] == "major"


# ── Pydantic 写入校验器：多值归一为 EN 单值 ───────────────────


def test_pydantic_validator_normalizes_multivalue() -> None:
    row = HazardReportBase(
        hazard_no="HZ-T01-2", description="x", hazard_level_manual="较大隐患, 一般隐患"
    )
    assert row.hazard_level_manual == "serious"


def test_pydantic_validator_normalizes_cn_and_keeps_unknown() -> None:
    assert (
        HazardReportBase(
            hazard_no="HZ-T01-3", description="x", hazard_level_manual="重大隐患"
        ).hazard_level_manual
        == "major"
    )
    assert (
        HazardReportBase(
            hazard_no="HZ-T01-4", description="x", hazard_level_manual="特殊级"
        ).hazard_level_manual
        == "特殊级"
    )
