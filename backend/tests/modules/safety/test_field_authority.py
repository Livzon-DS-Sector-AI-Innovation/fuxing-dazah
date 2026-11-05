"""T01 字段权威矩阵 — 单一事实源单测（RED 先行）。

覆盖 spec S1：owner 登记、权威列/fallback、写链白名单、effective 归一
（含人工多选级别取最高）、① 督办写守卫两配置。
"""

from __future__ import annotations

import pytest

from app.modules.safety.service.hazard_direct import bitable_repo
from app.modules.safety.service.hazard_direct import field_authority as fa

# ── 字段归属矩阵 ──────────────────────────────────────────────


def test_authority_of_level_type_category_registered() -> None:
    assert fa.authoritative_field("level") == "隐患级别"
    assert fa.fallback_field("level") == "隐患级别（AI）"
    assert fa.authoritative_field("type") == "隐患分类"
    assert fa.fallback_field("type") == "隐患分类（AI）"
    assert fa.authoritative_field("category") == "隐患类别"
    assert fa.fallback_field("category") == "隐患类别（AI）"


def test_owner_enumeration() -> None:
    assert fa.owner_of("隐患级别") is fa.FieldOwner.HUMAN
    assert fa.owner_of("隐患分类") is fa.FieldOwner.HUMAN
    assert fa.owner_of("隐患类别") is fa.FieldOwner.HUMAN
    assert fa.owner_of("隐患描述") is fa.FieldOwner.HUMAN
    assert fa.owner_of("隐患级别（AI）") is fa.FieldOwner.AI
    assert fa.owner_of("隐患分类（AI）") is fa.FieldOwner.AI
    assert fa.owner_of("隐患编号") is fa.FieldOwner.SYSTEM
    assert fa.owner_of("督办等级") is fa.FieldOwner.DERIVED
    assert fa.owner_of("评分结果") is fa.FieldOwner.SYSTEM
    assert fa.owner_of("测试") is fa.FieldOwner.FORMULA
    assert fa.owner_of("不存在的列") is None


def test_bitable_repo_reexports_field_constants() -> None:
    """字段名常量收口后，外部 `bitable_repo.F_*` 引用不破坏。"""
    assert bitable_repo.F_LEVEL_MANUAL == fa.F_LEVEL_MANUAL == "隐患级别"
    assert bitable_repo.F_TYPE_AI == fa.F_TYPE_AI == "隐患分类（AI）"
    assert bitable_repo.F_TYPE_MANUAL == fa.F_TYPE_MANUAL == "隐患分类"
    assert bitable_repo.F_CATEGORY_MANUAL == fa.F_CATEGORY_MANUAL == "隐患类别"
    assert bitable_repo.F_SUPERVISION == fa.F_SUPERVISION == "督办等级"


# ── 写链白名单（AI 写路径不得包含人工列）───────────────────────


def test_ai_analysis_whitelist_reaches_system_columns() -> None:
    wl = fa.writer_whitelist("ai_analysis")
    assert {
        "隐患级别（AI）",
        "隐患分类（AI）",
        "隐患类别（AI）",
        "隐患描述（AI）",
        "隐患判定依据（AI）",
        "整改建议（AI）",
        "隐患编号",
        "督办等级",
    } <= set(wl)


@pytest.mark.parametrize("writer", ["ai_analysis", "review", "scoring", "supervision"])
def test_writer_whitelists_never_contain_human_columns(writer: str) -> None:
    wl = fa.writer_whitelist(writer)
    human = {f for f in wl if fa.is_human_owned(f)}
    assert human == set(), f"{writer} 白名单含人工列: {sorted(human)}"


def test_writer_whitelist_key_fields() -> None:
    assert "AI初审结果" in fa.writer_whitelist("review")
    assert "AI初审说明" in fa.writer_whitelist("review")
    assert "评分结果" in fa.writer_whitelist("scoring")
    assert "评分说明" in fa.writer_whitelist("scoring")
    assert "督办等级" in fa.writer_whitelist("supervision")


def test_assert_write_allowed_rejects_human_field() -> None:
    fa.assert_write_allowed("ai_analysis", ["隐患级别（AI）", "督办等级", "隐患编号"])
    with pytest.raises(fa.FieldAuthorityError) as exc:
        fa.assert_write_allowed("ai_analysis", ["隐患级别（AI）", "隐患级别"])
    assert "隐患级别" in str(exc.value)


def test_assert_no_human_fields() -> None:
    fa.assert_no_human_fields(["隐患级别（AI）", "督办等级"])
    with pytest.raises(fa.FieldAuthorityError):
        fa.assert_no_human_fields(["隐患描述"])


# ── 人工级别归一（多选取最高）────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("一般隐患", "general"),
        ("较大隐患", "serious"),
        ("重大隐患", "major"),
        ("较大隐患, 一般隐患", "serious"),
        ("较大隐患,一般隐患", "serious"),
        (["较大隐患", "一般隐患"], "serious"),
        (["一般隐患", "重大隐患"], "major"),
        (["未知级别"], None),
        ("serious", "serious"),
        ("", None),
        (None, None),
    ],
)
def test_normalize_level_manual(raw: object, want: str | None) -> None:
    assert fa.normalize_level_manual(raw) == want


# ── effective 解析 ───────────────────────────────────────────


def test_resolve_effective_level_human_wins_and_mismatch() -> None:
    got = fa.resolve_effective("较大隐患", "general", "level")
    assert (got.value, got.source, got.mismatch) == ("serious", "human", True)


def test_resolve_effective_level_agree() -> None:
    got = fa.resolve_effective("较大隐患", "serious", "level")
    assert (got.value, got.source, got.mismatch) == ("serious", "human", False)


def test_resolve_effective_falls_back_to_ai() -> None:
    got = fa.resolve_effective(None, "general", "level")
    assert (got.value, got.source, got.mismatch) == ("general", "ai", False)


def test_resolve_effective_empty_both_sides() -> None:
    got = fa.resolve_effective("", None, "level")
    assert (got.value, got.source, got.mismatch) == (None, None, False)


def test_resolve_effective_multi_select_level() -> None:
    got = fa.resolve_effective(["较大隐患", "一般隐患"], "general", "level")
    assert (got.value, got.source, got.mismatch) == ("serious", "human", True)


def test_resolve_effective_type_and_category() -> None:
    t = fa.resolve_effective("物的不安全状态", "unsafe_action", "type")
    assert (t.value, t.source, t.mismatch) == ("unsafe_condition", "human", True)
    c = fa.resolve_effective("设备设施", "应急管理", "category")
    assert (c.value, c.source, c.mismatch) == ("equipment", "human", True)
    fallback = fa.resolve_effective(None, "equipment", "category")
    assert (fallback.value, fallback.source) == ("equipment", "ai")


# ── B3 写守卫（两配置）───────────────────────────────────────


def test_supervision_write_allowed_pure_function() -> None:
    assert fa.supervision_write_allowed(poll_enabled=False) is True
    assert fa.supervision_write_allowed(poll_enabled=True) is False
    assert fa.supervision_writer_role(poll_enabled=False) == "ai"
    assert fa.supervision_writer_role(poll_enabled=True) == "supervision"


def test_supervision_write_allowed_reads_live_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.config.supervision_poll_enabled",
        lambda: True,
    )
    assert fa.supervision_write_allowed() is False
    monkeypatch.setattr(
        "app.modules.safety.service.hazard_direct.config.supervision_poll_enabled",
        lambda: False,
    )
    assert fa.supervision_write_allowed() is True


# ── 单一事实源一致性（Spec 轴审查修复）────────────────────────


def test_human_rules_use_human_first_read_policy() -> None:
    """人工列不得被登记为 AI_ONLY 读策略（否则矩阵自相矛盾）。"""
    human_rules = [r for r in fa.FIELD_RULES if r.owner is fa.FieldOwner.HUMAN]
    assert human_rules, "矩阵应包含人工列"
    bad = [
        r.field
        for r in human_rules
        if r.read_policy is not fa.ReadPolicy.HUMAN_FIRST_AI_FALLBACK
    ]
    assert bad == []


def test_authoritative_rules_fallback_matches_fallback_field() -> None:
    for semantic in ("level", "type", "category"):
        assert fa.fallback_field(semantic) == fa.rule_of(
            fa.authoritative_field(semantic) or ""
        ).fallback  # type: ignore[union-attr]


def test_unmappable_manual_value_is_still_authoritative() -> None:
    """人工列有值但选项无法归一 → source=human、不静默回退 AI（Spec 轴修复）。"""
    got = fa.resolve_effective("未知分类", "管理的缺陷", "type")
    assert (got.value, got.source, got.mismatch) == (None, "human", False)


def test_unknown_manual_level_does_not_fall_back_to_ai() -> None:
    got = fa.resolve_effective("未知级别", "general", "level")
    assert got.source == "human"
    assert got.value is None
