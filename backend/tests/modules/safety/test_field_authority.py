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
    """人工列不得被登记为 AI_ONLY 读策略（否则矩阵自相矛盾）。

    P1-2/D1 例外：显式停用的无消费人工列允许 DEPRECATED（处置清单拍板，
    名单由 test_deprecated_fields_snapshot 快照锁定）。
    """
    human_rules = [r for r in fa.FIELD_RULES if r.owner is fa.FieldOwner.HUMAN]
    assert human_rules, "矩阵应包含人工列"
    bad = [
        r.field
        for r in human_rules
        if r.read_policy
        not in (fa.ReadPolicy.HUMAN_FIRST_AI_FALLBACK, fa.ReadPolicy.DEPRECATED)
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


# ── T01(D2) 枚举单一事实源：CN↔EN 映射只在 field_authority，其余派生 ─────


def test_level_type_category_maps_live_in_field_authority() -> None:
    """值集为设计文档 §1.1 已知业务事实（3 级/4 分类/13 类别），独立于实现。"""
    assert fa.HAZARD_LEVEL_MAP == {
        "一般隐患": "general",
        "较大隐患": "serious",
        "重大隐患": "major",
    }
    assert set(fa.HAZARD_TYPE_MAP.values()) == {
        "unsafe_action",
        "unsafe_condition",
        "environmental",
        "management_defect",
    }
    assert len(fa.HAZARD_CATEGORY_MAP) == 13
    assert fa.HAZARD_LEVEL_REVERSE == {v: k for k, v in fa.HAZARD_LEVEL_MAP.items()}
    assert fa.HAZARD_TYPE_REVERSE == {v: k for k, v in fa.HAZARD_TYPE_MAP.items()}
    assert fa.HAZARD_CATEGORY_REVERSE == {v: k for k, v in fa.HAZARD_CATEGORY_MAP.items()}


def test_bitable_handler_maps_are_reexports_of_source() -> None:
    """feishu 侧六名字典必须 re-export 同一对象（import 路径兼容，值不漂移）。"""
    from app.modules.safety.feishu import bitable_handler as bh

    assert bh.HAZARD_LEVEL_MAP is fa.HAZARD_LEVEL_MAP
    assert bh.HAZARD_TYPE_MAP is fa.HAZARD_TYPE_MAP
    assert bh.HAZARD_CATEGORY_MAP is fa.HAZARD_CATEGORY_MAP
    assert bh.HAZARD_LEVEL_REVERSE is fa.HAZARD_LEVEL_REVERSE
    assert bh.HAZARD_TYPE_REVERSE is fa.HAZARD_TYPE_REVERSE
    assert bh.HAZARD_CATEGORY_REVERSE is fa.HAZARD_CATEGORY_REVERSE


def test_registry_value_maps_match_source() -> None:
    """bitable_config 注册表的等级/分类/类别 value_map 必须与事实源同值。"""
    from app.modules.safety.bitable_config import registry

    wanted = {"隐患级别", "隐患分类（AI）", "隐患类别（AI）"}
    maps: dict[str, dict] = {}
    for domain in registry._DOMAINS:
        for kind in domain.kinds:
            for m in kind.default_mappings:
                if m["source_field"] in wanted:
                    maps[m["source_field"]] = m["value_map"]
    assert maps["隐患级别"] == dict(fa.HAZARD_LEVEL_MAP)
    assert maps["隐患分类（AI）"] == dict(fa.HAZARD_TYPE_MAP)
    assert maps["隐患类别（AI）"] == dict(fa.HAZARD_CATEGORY_MAP)


def test_ai_analysis_valid_sets_match_source() -> None:
    """① 识别输出的合法值集必须从事实源派生（不能手抄漂移）。"""
    from app.modules.safety.service.hazard_direct import ai_analysis

    assert set(ai_analysis.VALID_LEVELS) == set(fa.HAZARD_LEVEL_MAP.values())
    assert set(ai_analysis.VALID_TYPES) == set(fa.HAZARD_TYPE_MAP.values())
    assert set(ai_analysis.VALID_CATEGORIES) == set(fa.HAZARD_CATEGORY_MAP.values())


def test_supervision_display_cn_aligned_with_source() -> None:
    """督办展示用 EN→短中文 缩写表，键集必须与事实源值集对齐。"""
    from app.modules.safety.service.hazard_supervision import HAZARD_LEVEL_CN

    assert HAZARD_LEVEL_CN == {"general": "一般", "serious": "较大", "major": "重大"}
    assert set(HAZARD_LEVEL_CN) == set(fa.HAZARD_LEVEL_MAP.values())


# ── T03(D1) 遗留字段生命周期登记：7 个无消费人工列=停用、重复标签=废弃 ──

_UNCONSUMED_HUMAN_FIELDS = (
    "检查人员状态",
    "安全办人员状态",
    "安全经理确认",
    "安全总监确认",
    "检查级别",
    "检查人员身份",
    "重点缺陷",
)


def test_unconsumed_human_columns_registered_deprecated() -> None:
    """C5 7 个无消费人工列：owner=HUMAN + 读口径 DEPRECATED（处置=停用）。"""
    for name in _UNCONSUMED_HUMAN_FIELDS:
        rule = fa.rule_of(name)
        assert rule is not None, f"{name} 未登记"
        assert rule.owner is fa.FieldOwner.HUMAN, name
        assert rule.read_policy is fa.ReadPolicy.DEPRECATED, name
        assert "停用" in rule.note, name


def test_duplicate_tag_disposition_documented() -> None:
    """重复标签（AI）：写入方已查明=非本系统代码；已删列（2026-11-10 GOVERNANCE 执行）。"""
    rule = fa.rule_of("重复标签（AI）")
    assert rule is not None
    assert rule.owner is fa.FieldOwner.AI
    assert "已删列" in rule.note
    assert rule.writers == frozenset()  # 白名单禁止任何写链写入


def test_deprecated_fields_snapshot() -> None:
    """DEPRECATED 全集快照：AI审核* 5 + 重复标签 1 + 无消费人工列 7（增删列须显式更新本测试）。"""
    deprecated = sorted(
        r.field for r in fa.FIELD_RULES if r.read_policy is fa.ReadPolicy.DEPRECATED
    )
    assert deprecated == sorted(
        (
            "AI审核结论",
            "AI审核理由",
            "AI发现问题",
            "AI补充建议",
            "AI审核时间",
            "重复标签（AI）",
            *_UNCONSUMED_HUMAN_FIELDS,
        )
    )


# ── T05(D3) ai_vs_manual 差异结构：纯函数（等级/分类/类别三维） ──


def test_build_ai_vs_manual_all_three_semantics() -> None:
    got = fa.build_ai_vs_manual(
        manual_level="较大隐患",
        ai_level="一般隐患",
        manual_type="管理的缺陷",
        ai_type="管理的缺陷",
        manual_category=None,
        ai_category="设备设施",
    )
    assert got["level"] == {
        "manual_raw": "较大隐患",
        "ai_raw": "一般隐患",
        "effective": "serious",
        "source": "human",
        "mismatch": True,
    }
    assert got["type"]["mismatch"] is False
    # 人工类别空 → fallback AI，source=ai
    assert got["category"] == {
        "manual_raw": None,
        "ai_raw": "设备设施",
        "effective": "equipment",
        "source": "ai",
        "mismatch": False,
    }


def test_build_ai_vs_manual_both_empty() -> None:
    got = fa.build_ai_vs_manual(None, None, None, None, None, None)
    for sem in ("level", "type", "category"):
        assert got[sem] == {
            "manual_raw": None,
            "ai_raw": None,
            "effective": None,
            "source": None,
            "mismatch": False,
        }


def test_build_ai_vs_manual_manual_unmappable_keeps_human_source() -> None:
    """人工列有值但无法归一：source=human、effective=None、不回退 AI（口径一致）。"""
    got = fa.build_ai_vs_manual("未知级别", "general", None, None, None, None)
    assert got["level"]["source"] == "human"
    assert got["level"]["effective"] is None
    assert got["level"]["mismatch"] is False
