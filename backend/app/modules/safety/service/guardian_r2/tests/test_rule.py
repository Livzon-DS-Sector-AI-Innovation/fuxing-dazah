"""R2 四规则矩阵 —— 直接调底座 evaluate_rule（照 R1 test_rule 模式）。

规则只判 payload._derived 结构化值（翻译层已算好，零文本操作符）：
- guardian_review_remind：trigger_type == remind
- guardian_qualification_revoke：trigger_type ∈ {overdue, failed}
- guardian_qualification_restore：trigger_type == restore
- guardian_score_map（成绩源）：_derived.passed ∈ {合格, 不合格}
"""

from __future__ import annotations

from app.platform.superagent.policy import evaluate_rule
from app.modules.safety.service.guardian_r2.rule import (
    guardian_remind_rule,
    guardian_revoke_rule,
    guardian_restore_rule,
    guardian_score_map_rule,
)


def _derived_cert(trigger_type: str, **extra) -> dict:
    payload = {"_derived": {"trigger_type": trigger_type}}
    payload["_derived"].update(extra)
    return payload


def _derived_score(passed: str | None, **extra) -> dict:
    payload = {"_derived": {"passed": passed}}
    payload["_derived"].update(extra)
    return payload


# ── 规则1：复审提醒 ──


def test_remind_rule_hits() -> None:
    hit, _ = evaluate_rule(guardian_remind_rule(), _derived_cert("remind"))
    assert hit is True


def test_remind_rule_excludes_others() -> None:
    for t in ("overdue", "failed", "restore"):
        hit, _ = evaluate_rule(guardian_remind_rule(), _derived_cert(t))
        assert hit is False


# ── 规则2：取消资格 ──


def test_revoke_rule_hits_failed_only() -> None:
    """拍板④后：overdue 静默不产 Trigger；规则只认 failed。"""
    hit, _ = evaluate_rule(guardian_revoke_rule(), _derived_cert("failed"))
    assert hit is True
    hit, _ = evaluate_rule(guardian_revoke_rule(), _derived_cert("overdue"))
    assert hit is False


def test_revoke_rule_excludes_remind_restore() -> None:
    hit, _ = evaluate_rule(guardian_revoke_rule(), _derived_cert("remind"))
    assert hit is False
    hit, _ = evaluate_rule(guardian_revoke_rule(), _derived_cert("restore"))
    assert hit is False


# ── 规则3：资格恢复 ──


def test_restore_rule_hits_only_restore() -> None:
    hit, _ = evaluate_rule(guardian_restore_rule(), _derived_cert("restore"))
    assert hit is True
    for t in ("remind", "overdue", "failed"):
        hit, _ = evaluate_rule(guardian_restore_rule(), _derived_cert(t))
        assert hit is False


# ── 规则4：成绩映射（成绩源）──


def test_score_map_rule_hits_pass_or_fail() -> None:
    hit, _ = evaluate_rule(guardian_score_map_rule(), _derived_score("合格"))
    assert hit is True
    hit, _ = evaluate_rule(guardian_score_map_rule(), _derived_score("不合格"))
    assert hit is True


def test_score_map_rule_excludes_absent() -> None:
    """缺考无「是否合格」值 → 不进决策（零噪音）。"""
    hit, _ = evaluate_rule(guardian_score_map_rule(), _derived_score(None))
    assert hit is False
