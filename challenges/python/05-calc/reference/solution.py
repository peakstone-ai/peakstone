"""Recursive-descent evaluator for +, -, *, /, parentheses, unary +/-.

Grammar:
    expr   := term (('+' | '-') term)*
    term   := factor (('*' | '/') factor)*
    factor := ('+' | '-') factor | '(' expr ')' | number
"""


def _tokenize(expr: str) -> list:
    tokens = []
    i = 0
    n = len(expr)
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-*/()":
            tokens.append(c)
            i += 1
            continue
        if c.isdigit() or c == ".":
            j = i
            seen_dot = False
            while j < n and (expr[j].isdigit() or expr[j] == "."):
                if expr[j] == ".":
                    if seen_dot:
                        raise ValueError(f"malformed number near: {expr[i:j+1]!r}")
                    seen_dot = True
                j += 1
            text = expr[i:j]
            if text == ".":
                raise ValueError("lone '.' is not a number")
            tokens.append(float(text))
            i = j
            continue
        raise ValueError(f"unexpected character: {c!r}")
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self):
        tok = self._peek()
        self.pos += 1
        return tok

    def parse(self) -> float:
        if not self.tokens:
            raise ValueError("empty expression")
        value = self._expr()
        if self.pos != len(self.tokens):
            raise ValueError(f"unexpected trailing token: {self._peek()!r}")
        return value

    def _expr(self) -> float:
        value = self._term()
        while self._peek() in ("+", "-"):
            op = self._next()
            rhs = self._term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def _term(self) -> float:
        value = self._factor()
        while self._peek() in ("*", "/"):
            op = self._next()
            rhs = self._factor()
            if op == "*":
                value = value * rhs
            else:
                if rhs == 0:
                    raise ValueError("division by zero")
                value = value / rhs
        return value

    def _factor(self) -> float:
        tok = self._peek()
        if tok == "+":
            self._next()
            return self._factor()
        if tok == "-":
            self._next()
            return -self._factor()
        if tok == "(":
            self._next()
            value = self._expr()
            if self._next() != ")":
                raise ValueError("unbalanced parentheses")
            return value
        if isinstance(tok, float):
            self._next()
            return tok
        raise ValueError(f"expected a number or '(', got: {tok!r}")


def evaluate(expr: str) -> float:
    tokens = _tokenize(expr)
    return _Parser(tokens).parse()
