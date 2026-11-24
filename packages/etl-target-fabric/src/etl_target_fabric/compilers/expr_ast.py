"""Deterministic, fail-closed Expression AST shared by Fabric compilers.

Parses bounded source expressions via recursive descent (no ``eval``, no
catastrophic regex backtracking) and emits Power Query M or PySpark code.
Unrecognized tokens, functions, or constructs fail closed with
``ExpressionParseError``.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Literal

from etl_target_fabric.compilers.m_literals import m_string

TargetDialect = Literal["dataflow", "notebook"]
MAX_EXPRESSION_CHARS = 4096
MAX_AST_DEPTH = 32


class ExpressionParseError(ValueError):
    """Raised when an expression lies outside the supported deterministic grammar."""


@dataclass(frozen=True, slots=True)
class LiteralExpr:
    value: str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class ColumnRefExpr:
    name: str


@dataclass(frozen=True, slots=True)
class UnaryExpr:
    operator: Literal["not", "-"]
    operand: Expr


@dataclass(frozen=True, slots=True)
class BinaryExpr:
    operator: Literal["=", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/", "and", "or"]
    left: Expr
    right: Expr


@dataclass(frozen=True, slots=True)
class CallExpr:
    name: str
    args: tuple[Expr, ...]


@dataclass(frozen=True, slots=True)
class ConditionalExpr:
    condition: Expr
    when_true: Expr
    when_false: Expr


Expr = LiteralExpr | ColumnRefExpr | UnaryExpr | BinaryExpr | CallExpr | ConditionalExpr


@dataclass(frozen=True, slots=True)
class _Token:
    kind: Literal["NUMBER", "STRING", "COLUMN", "IDENT", "OP", "LPAREN", "RPAREN", "COMMA", "EOF"]
    value: str


_TOKEN_SPEC = re.compile(
    r"""
    \s*(?:
        (?P<NUMBER>\d+(?:\.\d+)?)
      | (?P<DSTRING>"(?:[^"\\\r\n]|\\.)*")
      | (?P<SSTRING>'(?:[^'\\\r\n]|''|\\.)*')
      | (?P<COLUMN>\[[^\[\]\r\n]+\])
      | (?P<OP><=|>=|!=|<>|=|<|>|\+|-|\*|/)
      | (?P<LPAREN>\()
      | (?P<RPAREN>\))
      | (?P<COMMA>,)
      | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    )
    """,
    re.VERBOSE,
)

_SUPPORTED_FUNCTIONS = frozenset(
    {
        "IIF",
        "ISNULL",
        "UPPER",
        "UPPERCASE",
        "LOWER",
        "LOWERCASE",
        "TRIM",
        "LTRIM",
        "RTRIM",
        "TONUMBER",
        "TOSTRING",
        "LENGTH",
        "LEN",
        "ABS",
        "ROUND",
        "COALESCE",
    }
)


def _tokenize(source: str) -> list[_Token]:
    text = html.unescape(source.strip())
    if not text or len(text) > MAX_EXPRESSION_CHARS:
        raise ExpressionParseError("Expression is empty or exceeds maximum length")
    tokens: list[_Token] = []
    position = 0
    length = len(text)
    while position < length:
        match = _TOKEN_SPEC.match(text, position)
        if match is None or match.end() == position:
            raise ExpressionParseError(f"Unexpected token near offset {position}")
        position = match.end()
        kind = match.lastgroup
        raw = match.group(kind) if kind else ""
        if kind == "NUMBER":
            tokens.append(_Token("NUMBER", raw))
        elif kind == "DSTRING":
            inner = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            tokens.append(_Token("STRING", inner))
        elif kind == "SSTRING":
            inner = raw[1:-1].replace("''", "'").replace("\\'", "'").replace("\\\\", "\\")
            tokens.append(_Token("STRING", inner))
        elif kind == "COLUMN":
            tokens.append(_Token("COLUMN", raw[1:-1]))
        elif kind == "OP":
            tokens.append(_Token("OP", "!=" if raw == "<>" else raw))
        elif kind == "LPAREN":
            tokens.append(_Token("LPAREN", raw))
        elif kind == "RPAREN":
            tokens.append(_Token("RPAREN", raw))
        elif kind == "COMMA":
            tokens.append(_Token("COMMA", raw))
        elif kind == "IDENT":
            tokens.append(_Token("IDENT", raw))
    tokens.append(_Token("EOF", ""))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._depth = 0

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _consume(self) -> _Token:
        token = self._tokens[self._pos]
        self._pos += 1
        return token

    def parse(self) -> Expr:
        expr = self._parse_or()
        if self._peek().kind != "EOF":
            raise ExpressionParseError(f"Unexpected trailing token {self._peek().value!r}")
        return expr

    def _enter(self) -> None:
        self._depth += 1
        if self._depth > MAX_AST_DEPTH:
            raise ExpressionParseError("Expression nesting exceeds limit")

    def _exit(self) -> None:
        self._depth -= 1

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._peek().kind == "IDENT" and self._peek().value.upper() == "OR":
            self._consume()
            left = BinaryExpr("or", left, self._parse_and())
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while self._peek().kind == "IDENT" and self._peek().value.upper() == "AND":
            self._consume()
            left = BinaryExpr("and", left, self._parse_not())
        return left

    def _parse_not(self) -> Expr:
        if self._peek().kind == "IDENT" and self._peek().value.upper() == "NOT":
            self._consume()
            self._enter()
            try:
                return UnaryExpr("not", self._parse_not())
            finally:
                self._exit()
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_additive()
        token = self._peek()
        if token.kind == "OP" and token.value in {"=", "!=", "<", "<=", ">", ">="}:
            op = self._consume().value
            right = self._parse_additive()
            return BinaryExpr(op, left, right)  # type: ignore[arg-type]
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self._peek().kind == "OP" and self._peek().value in {"+", "-"}:
            op = self._consume().value
            left = BinaryExpr(op, left, self._parse_multiplicative())  # type: ignore[arg-type]
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self._peek().kind == "OP" and self._peek().value in {"*", "/"}:
            op = self._consume().value
            left = BinaryExpr(op, left, self._parse_unary())  # type: ignore[arg-type]
        return left

    def _parse_unary(self) -> Expr:
        if self._peek().kind == "OP" and self._peek().value == "-":
            self._consume()
            self._enter()
            try:
                operand = self._parse_unary()
            finally:
                self._exit()
            if isinstance(operand, LiteralExpr) and isinstance(operand.value, (int, float)):
                return LiteralExpr(-operand.value)
            return UnaryExpr("-", operand)
        return self._parse_primary()

    def _parse_primary(self) -> Expr:
        token = self._peek()
        if token.kind == "NUMBER":
            self._consume()
            value: int | float = float(token.value) if "." in token.value else int(token.value)
            return LiteralExpr(value)
        if token.kind == "STRING":
            self._consume()
            return LiteralExpr(token.value)
        if token.kind == "COLUMN":
            self._consume()
            return ColumnRefExpr(token.value)
        if token.kind == "LPAREN":
            self._consume()
            self._enter()
            try:
                inner = self._parse_or()
            finally:
                self._exit()
            if self._peek().kind != "RPAREN":
                raise ExpressionParseError("Unclosed parenthesis in expression")
            self._consume()
            return inner
        if token.kind == "IDENT":
            ident = self._consume().value
            upper = ident.upper()
            if upper == "NULL":
                return LiteralExpr(None)
            if upper == "TRUE":
                return LiteralExpr(True)
            if upper == "FALSE":
                return LiteralExpr(False)
            if self._peek().kind == "LPAREN":
                return self._parse_call(upper)
            return ColumnRefExpr(ident)
        raise ExpressionParseError(f"Unexpected token {token.value!r}")

    def _parse_call(self, name: str) -> Expr:
        if name not in _SUPPORTED_FUNCTIONS:
            raise ExpressionParseError(f"Unsupported expression function: {name}")
        self._consume()  # LPAREN
        self._enter()
        args: list[Expr] = []
        try:
            if self._peek().kind != "RPAREN":
                while True:
                    args.append(self._parse_or())
                    if self._peek().kind == "COMMA":
                        self._consume()
                        continue
                    break
            if self._peek().kind != "RPAREN":
                raise ExpressionParseError(f"Unclosed call to {name}")
            self._consume()
        finally:
            self._exit()
        if name == "IIF":
            if len(args) != 3:
                raise ExpressionParseError("IIF requires exactly 3 arguments")
            return ConditionalExpr(args[0], args[1], args[2])
        return CallExpr(name, tuple(args))


def parse_expression(source: str) -> Expr:
    """Parse one source ETL expression into a deterministic AST."""
    return _Parser(_tokenize(source)).parse()


def emit_m(expr: Expr) -> str:
    """Emit Power Query M code for a parsed expression AST."""
    if isinstance(expr, LiteralExpr):
        if expr.value is None:
            return "null"
        if isinstance(expr.value, bool):
            return "true" if expr.value else "false"
        if isinstance(expr.value, str):
            return m_string(expr.value)
        return str(expr.value)
    if isinstance(expr, ColumnRefExpr):
        return f"Record.Field(_, {m_string(expr.name)})"
    if isinstance(expr, UnaryExpr):
        operand = emit_m(expr.operand)
        return f"(not ({operand}))" if expr.operator == "not" else f"(-({operand}))"
    if isinstance(expr, ConditionalExpr):
        return (
            f"(if {emit_m(expr.condition)} then {emit_m(expr.when_true)} "
            f"else {emit_m(expr.when_false)})"
        )
    if isinstance(expr, BinaryExpr):
        op = "<>" if expr.operator == "!=" else expr.operator
        if op == "+" and _is_text_expr(expr.left, expr.right):
            return f"(Text.From({emit_m(expr.left)}) & Text.From({emit_m(expr.right)}))"
        return f"({emit_m(expr.left)} {op} {emit_m(expr.right)})"
    return _emit_m_call(expr)


def _emit_m_call(expr: CallExpr) -> str:
    name = expr.name
    args = expr.args
    if name == "ISNULL" and len(args) == 1:
        return f"({emit_m(args[0])} = null)"
    if name in {"UPPER", "UPPERCASE"} and len(args) == 1:
        return f"Text.Upper(Text.From({emit_m(args[0])}))"
    if name in {"LOWER", "LOWERCASE"} and len(args) == 1:
        return f"Text.Lower(Text.From({emit_m(args[0])}))"
    if name == "TRIM" and len(args) == 1:
        return f"Text.Trim(Text.From({emit_m(args[0])}))"
    if name == "LTRIM" and len(args) == 1:
        return f"Text.TrimStart(Text.From({emit_m(args[0])}))"
    if name == "RTRIM" and len(args) == 1:
        return f"Text.TrimEnd(Text.From({emit_m(args[0])}))"
    if name == "TONUMBER" and len(args) == 1:
        return f"Number.From({emit_m(args[0])})"
    if name == "TOSTRING" and len(args) == 1:
        return f"Text.From({emit_m(args[0])})"
    if name in {"LENGTH", "LEN"} and len(args) == 1:
        return f"Text.Length(Text.From({emit_m(args[0])}))"
    if name == "ABS" and len(args) == 1:
        return f"Number.Abs({emit_m(args[0])})"
    if name == "ROUND" and len(args) == 2:
        return f"Number.Round({emit_m(args[0])}, {emit_m(args[1])})"
    if name == "COALESCE" and len(args) >= 2:
        result = emit_m(args[-1])
        for arg in reversed(args[:-1]):
            result = f"({emit_m(arg)} ?? {result})"
        return result
    raise ExpressionParseError(f"Unsupported M arity/function: {name}/{len(args)}")


def emit_pyspark(expr: Expr) -> str:
    """Emit PySpark ``F.*`` expression code for a parsed expression AST."""
    if isinstance(expr, LiteralExpr):
        if expr.value is None:
            return "F.lit(None)"
        if isinstance(expr.value, bool):
            return f"F.lit({expr.value})"
        if isinstance(expr.value, str):
            return f"F.lit({json.dumps(expr.value)})"
        return f"F.lit({expr.value})"
    if isinstance(expr, ColumnRefExpr):
        return f"F.col({json.dumps(expr.name)})"
    if isinstance(expr, UnaryExpr):
        operand = emit_pyspark(expr.operand)
        return f"(~({operand}))" if expr.operator == "not" else f"(-({operand}))"
    if isinstance(expr, ConditionalExpr):
        return (
            f"F.when({emit_pyspark(expr.condition)}, {emit_pyspark(expr.when_true)})"
            f".otherwise({emit_pyspark(expr.when_false)})"
        )
    if isinstance(expr, BinaryExpr):
        if expr.operator == "+" and _is_text_expr(expr.left, expr.right):
            return (
                f"F.concat(F.col({json.dumps(expr.left.name)}).cast('string'), "
                f"{emit_pyspark(expr.right)}.cast('string'))"
                if isinstance(expr.left, ColumnRefExpr)
                else f"F.concat(({emit_pyspark(expr.left)}).cast('string'), "
                f"({emit_pyspark(expr.right)}).cast('string'))"
            )
        py_op = {
            "=": "==",
            "!=": "!=",
            "<": "<",
            "<=": "<=",
            ">": ">",
            ">=": ">=",
            "+": "+",
            "-": "-",
            "*": "*",
            "/": "/",
            "and": "&",
            "or": "|",
        }[expr.operator]
        return f"(({emit_pyspark(expr.left)}) {py_op} ({emit_pyspark(expr.right)}))"
    return _emit_pyspark_call(expr)


def _emit_pyspark_call(expr: CallExpr) -> str:
    name = expr.name
    args = expr.args
    if name == "ISNULL" and len(args) == 1:
        return f"({emit_pyspark(args[0])}).isNull()"
    if name in {"UPPER", "UPPERCASE"} and len(args) == 1:
        return f"F.upper({emit_pyspark(args[0])})"
    if name in {"LOWER", "LOWERCASE"} and len(args) == 1:
        return f"F.lower({emit_pyspark(args[0])})"
    if name == "TRIM" and len(args) == 1:
        return f"F.trim({emit_pyspark(args[0])})"
    if name == "LTRIM" and len(args) == 1:
        return f"F.ltrim({emit_pyspark(args[0])})"
    if name == "RTRIM" and len(args) == 1:
        return f"F.rtrim({emit_pyspark(args[0])})"
    if name == "TONUMBER" and len(args) == 1:
        return f"({emit_pyspark(args[0])}).cast('double')"
    if name == "TOSTRING" and len(args) == 1:
        return f"({emit_pyspark(args[0])}).cast('string')"
    if name in {"LENGTH", "LEN"} and len(args) == 1:
        return f"F.length({emit_pyspark(args[0])})"
    if name == "ABS" and len(args) == 1:
        return f"F.abs({emit_pyspark(args[0])})"
    if name == "ROUND" and len(args) == 2:
        if isinstance(args[1], LiteralExpr) and isinstance(args[1].value, int):
            return f"F.round({emit_pyspark(args[0])}, {args[1].value})"
        raise ExpressionParseError("ROUND scale must be an integer literal in PySpark")
    if name == "COALESCE" and len(args) >= 2:
        joined = ", ".join(emit_pyspark(arg) for arg in args)
        return f"F.coalesce({joined})"
    raise ExpressionParseError(f"Unsupported PySpark arity/function: {name}/{len(args)}")


def _is_text_expr(left: Expr, right: Expr) -> bool:
    for node in (left, right):
        if isinstance(node, LiteralExpr) and isinstance(node.value, str):
            return True
        if isinstance(node, CallExpr) and node.name in {
            "UPPER",
            "UPPERCASE",
            "LOWER",
            "LOWERCASE",
            "TRIM",
            "LTRIM",
            "RTRIM",
            "TOSTRING",
        }:
            return True
    return False


def translate_expression_ast(source: str, target: TargetDialect) -> str | None:
    """Translate an expression via the deterministic AST, returning None when unsupported."""
    try:
        ast_node = parse_expression(source)
        return emit_m(ast_node) if target == "dataflow" else emit_pyspark(ast_node)
    except ExpressionParseError:
        return None
