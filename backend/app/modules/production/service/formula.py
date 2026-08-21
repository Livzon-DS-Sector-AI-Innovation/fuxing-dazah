"""计算字段公式：四则运算 + 括号 + {node_code.field_key} 引用。

白名单 token，无 eval。引用缺失/除零求值为 None。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class FormulaError(ValueError):
    """公式语法非法。"""


@dataclass(frozen=True)
class Const:
    value: float


@dataclass(frozen=True)
class Ref:
    node_code: str
    field_key: str


@dataclass(frozen=True)
class BinOp:
    op: str
    left: FormulaNode
    right: FormulaNode


FormulaNode = Const | Ref | BinOp

_TOKEN_RE = re.compile(
    r"\s*(?:(?P<ref>\{[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\})"
    r"|(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<op>[+\-*/()]))"
)


def _tokenize(formula: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(formula):
        m = _TOKEN_RE.match(formula, pos)
        if not m or m.group(0) == "":
            if formula[pos:].strip() == "":
                break  # 剩余全为空白，公式到此结束
            raise FormulaError(f"公式含非法内容: {formula[pos:pos + 10]}")
        kind = m.lastgroup
        assert kind is not None
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    if formula[pos:].strip():
        raise FormulaError(f"公式含非法内容: {formula[pos:]}")
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.i = 0

    def _peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _next(self) -> tuple[str, str]:
        t = self._peek()
        if t is None:
            raise FormulaError("公式意外结束")
        self.i += 1
        return t

    def parse(self) -> FormulaNode:
        node = self._expr()
        if (extra := self._peek()) is not None:
            raise FormulaError(f"公式有多余内容: {extra[0]}")
        return node

    def _expr(self) -> FormulaNode:
        node = self._term()
        while (t := self._peek()) and t[1] in ("+", "-"):
            self._next()
            node = BinOp(t[1], node, self._term())
        return node

    def _term(self) -> FormulaNode:
        node = self._factor()
        while (t := self._peek()) and t[1] in ("*", "/"):
            self._next()
            node = BinOp(t[1], node, self._factor())
        return node

    def _factor(self) -> FormulaNode:
        t = self._next()
        if t[0] == "num":
            return Const(float(t[1]))
        if t[0] == "ref":
            code, key = t[1].strip("{}").split(".", 1)
            return Ref(code, key)
        if t[1] == "(":
            node = self._expr()
            close = self._next()
            if close[1] != ")":
                raise FormulaError("缺少右括号")
            return node
        raise FormulaError(f"意外的符号: {t[1]}")


def parse_formula(formula: str) -> FormulaNode:
    """解析公式；语法非法抛 FormulaError。"""
    if not formula.strip():
        raise FormulaError("公式为空")
    return _Parser(_tokenize(formula)).parse()


def extract_refs(formula: str) -> list[tuple[str, str]]:
    """提取全部引用（节点内去重、保持出现顺序）。"""
    seen: list[tuple[str, str]] = []
    for kind, val in _tokenize(formula):
        if kind == "ref":
            code, key = val.strip("{}").split(".", 1)
            if (code, key) not in seen:
                seen.append((code, key))
    return seen


def evaluate(node: FormulaNode, values: dict[tuple[str, str], float | None]) -> float | None:
    """求值；引用缺失或除零返回 None。"""
    match node:
        case Const(v):
            return v
        case Ref(code, key):
            return values.get((code, key))
        case BinOp(op, left, right):
            lv = evaluate(left, values)
            rv = evaluate(right, values)
            if lv is None or rv is None:
                return None
            if op == "+":
                return lv + rv
            if op == "-":
                return lv - rv
            if op == "*":
                return lv * rv
            if op == "/":
                if rv == 0:
                    return None
                return lv / rv
            raise FormulaError(f"未知运算符: {op}")  # pragma: no cover
