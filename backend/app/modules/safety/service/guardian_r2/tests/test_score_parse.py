"""成绩表字段解析 —— 《理论考试分数表》真实形态驱动的纯函数单测。

字段形态实测（2026-11-04，353 行）：
- 是否合格：公式列 → {"type": 1, "value": [{"text": "合格"|"不合格", "type": "text"}]}；
  缺考记录无该键（公式空值）
- 考试日期：公式列 → {"type": 5, "value": [1763308800000]}（毫秒）
- 参加考试日期：单选文本「2026年1月7日」
- 姓名：人员字段 [{"id": "ou_xxx", "name": "陈辉", ...}]
- 报名考试类型：单选 监护人A证/监护人B证
- 考试分数：数字（0-100，缺考为 0 或空）
"""

from __future__ import annotations

from datetime import date

from app.modules.safety.service.guardian_r2.score_parse import (
    parse_exam_date,
    parse_exam_type_ab,
    parse_pass,
    parse_person,
    parse_score_number,
)


def _pass_formula(text: str) -> dict:
    """是否合格公式列原始形态。"""
    return {"type": 1, "value": [{"text": text, "type": "text"}]}


# ── 是否合格 ──


def test_parse_pass_formula_qualified() -> None:
    assert parse_pass(_pass_formula("合格")) == "合格"


def test_parse_pass_formula_failed() -> None:
    assert parse_pass(_pass_formula("不合格")) == "不合格"


def test_parse_pass_missing_is_none() -> None:
    """缺考记录无「是否合格」键 → None（不误判为不合格）。"""
    assert parse_pass(None) is None


def test_parse_pass_plain_string() -> None:
    """兼容直接字符串值。"""
    assert parse_pass("合格") == "合格"


def test_parse_pass_rich_list() -> None:
    """兼容富文本列表形态。"""
    assert parse_pass([{"type": "text", "text": "不合格"}]) == "不合格"


# ── 考试日期（公式优先，单选文本回退） ──


def test_parse_exam_date_formula_ms() -> None:
    fields = {"考试日期": {"type": 5, "value": [1763308800000]}}  # 2025-11-17 UTC
    assert parse_exam_date(fields) == date(2025, 11, 17)


def test_parse_exam_date_fallback_select_text() -> None:
    """公式列为空时回退解析「参加考试日期」单选文本（yyyy年M月d日）。"""
    fields = {"参加考试日期": "2026年1月7日"}
    assert parse_exam_date(fields) == date(2026, 1, 7)


def test_parse_exam_date_both_missing() -> None:
    assert parse_exam_date({"备注": "x"}) is None


def test_parse_exam_date_formula_wins_over_select() -> None:
    fields = {
        "考试日期": {"type": 5, "value": [1763308800000]},
        "参加考试日期": "2026年1月7日",
    }
    assert parse_exam_date(fields) == date(2025, 11, 17)


# ── 人员字段 ──


def test_parse_person_name_and_open_id() -> None:
    value = [{"id": "ou_0a296b498f5207af65f47f9bf67edb1e", "name": "陈辉"}]
    assert parse_person(value) == ("陈辉", "ou_0a296b498f5207af65f47f9bf67edb1e")


def test_parse_person_missing() -> None:
    assert parse_person(None) == (None, None)


# ── 报名考试类型 → A/B 证路由 ──


def test_parse_exam_type_ab() -> None:
    assert parse_exam_type_ab("监护人A证") == "guardian_a"
    assert parse_exam_type_ab("监护人B证") == "guardian_b"
    assert parse_exam_type_ab(None) is None
    assert parse_exam_type_ab("其他") is None


# ── 考试分数 ──


def test_parse_score_number() -> None:
    assert parse_score_number(67.5) == 67.5
    assert parse_score_number(0) == 0.0
    assert parse_score_number(None) is None
