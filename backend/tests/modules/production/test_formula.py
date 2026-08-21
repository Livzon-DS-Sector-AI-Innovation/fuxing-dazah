"""公式解析与求值。"""

import pytest

from app.modules.production.service.formula import (
    BinOp,
    Const,
    FormulaError,
    Ref,
    evaluate,
    extract_refs,
    parse_formula,
)


class TestParse:
    def test_basic_arithmetic(self):
        node = parse_formula("{G1.A1} + {G1.B1}")
        assert node == BinOp("+", Ref("G1", "A1"), Ref("G1", "B1"))

    def test_precedence(self):
        # 1 + 2 * 3 -> 7 而非 9
        node = parse_formula("1 + 2 * 3")
        assert node == BinOp("+", Const(1.0), BinOp("*", Const(2.0), Const(3.0)))

    def test_parens(self):
        node = parse_formula("(1 + 2) * 3")
        assert node == BinOp("*", BinOp("+", Const(1.0), Const(2.0)), Const(3.0))

    def test_division_and_negation_via_subtraction(self):
        assert evaluate(parse_formula("10 / 4 - 0.5"), {}) == 2.0

    def test_decimal_literal(self):
        assert evaluate(parse_formula("{G1.A1} * 0.9"), {("G1", "A1"): 100.0}) == 90.0

    def test_ref_syntax(self):
        node = parse_formula("{G1.A1} - {G2.B2}")
        assert node == BinOp("-", Ref("G1", "A1"), Ref("G2", "B2"))

    @pytest.mark.parametrize(
        "bad",
        [
            "1 +",            # 缺右操作数
            "{G1.A1} {G1.B1}",  # 缺运算符
            "1 / 0",          # 可以解析，求值时变 None（不在此测试）
            "pow(1,2)",       # 函数不允许
            "1 ** 2",         # 幂不允许
            "abc",            # 裸标识符不允许
            "{G1.A1} + 'x'",  # 字符串不允许
        ],
    )
    def test_invalid_formulas_rejected(self, bad):
        if bad == "1 / 0":
            pytest.skip("除零是求值期行为")
        with pytest.raises(FormulaError):
            parse_formula(bad)

    def test_empty_formula(self):
        with pytest.raises(FormulaError):
            parse_formula("")

    def test_trailing_whitespace_and_newline(self):
        assert evaluate(parse_formula("1 + 2  "), {}) == 3.0
        assert evaluate(parse_formula("1 + 2\n"), {}) == 3.0
        assert evaluate(parse_formula("{G1.A1} + 1 "), {("G1", "A1"): 1.0}) == 2.0


class TestEvaluate:
    def test_simple_eval(self):
        node = parse_formula("{G1.A1} + {G1.B1}")
        assert evaluate(node, {("G1", "A1"): 1.0, ("G1", "B1"): 2.0}) == 3.0

    def test_missing_ref_returns_none(self):
        node = parse_formula("{G1.A1} + {G1.B1}")
        assert evaluate(node, {("G1", "A1"): 1.0}) is None

    def test_division_by_zero_returns_none(self):
        node = parse_formula("{G1.A1} / {G1.B1}")
        assert evaluate(node, {("G1", "A1"): 1.0, ("G1", "B1"): 0.0}) is None

    def test_zero_division_nested(self):
        node = parse_formula("1 + ({G1.A1} / 0)")
        assert evaluate(node, {("G1", "A1"): 5.0}) is None


class TestExtractRefs:
    def test_extract_and_dedup_in_order(self):
        assert extract_refs("{G1.A1} + {G1.A1} + {G2.B2}") == [
            ("G1", "A1"),
            ("G2", "B2"),
        ]

    def test_no_refs(self):
        assert extract_refs("1 + 2 * 3") == []

    def test_refs_with_trailing_newline(self):
        assert extract_refs("{G1.A1} + 1\n") == [("G1", "A1")]
