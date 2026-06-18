"""A small backtracking regex matcher (no use of the `re` module).

Supported syntax:
  - literal chars, `.`, escaped `\\x`
  - character classes `[...]`, negation `[^...]`, ranges `a-z`, literal `-`
  - quantifiers `*`, `+`, `?` applied to the single preceding element

`fullmatch` is anchored: the pattern must consume the entire text.
"""


def _parse(pattern: str):
    """Compile `pattern` into a list of (matcher, quantifier) tokens.

    `matcher` is a callable: char -> bool, that tells whether a single text
    character is matched by this element. `quantifier` is one of '', '*', '+', '?'.
    """
    tokens = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]

        if c == "\\":
            # Escaped literal: the next char matches itself.
            if i + 1 >= n:
                raise ValueError("trailing backslash in pattern")
            lit = pattern[i + 1]
            matcher = (lambda ch, lit=lit: ch == lit)
            i += 2
        elif c == ".":
            matcher = (lambda ch: True)
            i += 1
        elif c == "[":
            matcher, i = _parse_class(pattern, i)
        elif c in "*+?":
            raise ValueError("quantifier with no preceding element: " + c)
        else:
            matcher = (lambda ch, lit=c: ch == lit)
            i += 1

        # Optional quantifier directly following the element.
        quant = ""
        if i < n and pattern[i] in "*+?":
            quant = pattern[i]
            i += 1

        tokens.append((matcher, quant))

    return tokens


def _parse_class(pattern: str, i: int):
    """Parse a `[...]` class starting at index `i` (pattern[i] == '[').

    Returns (matcher, next_index).
    """
    n = len(pattern)
    j = i + 1  # skip '['
    negated = False
    if j < n and pattern[j] == "^":
        negated = True
        j += 1

    items = []  # list of ('char', c) or ('range', lo, hi)
    # A ']' as the very first class char would be literal, but the spec does not
    # require that; we keep the simple rule that ']' closes the class.
    while j < n and pattern[j] != "]":
        # Determine the current character (supporting escapes inside classes).
        if pattern[j] == "\\":
            if j + 1 >= n:
                raise ValueError("trailing backslash in class")
            lo = pattern[j + 1]
            j += 2
        else:
            lo = pattern[j]
            j += 1

        # Range: lo '-' hi, but only when '-' is not the last char before ']'.
        if (
            j < n
            and pattern[j] == "-"
            and j + 1 < n
            and pattern[j + 1] != "]"
        ):
            j += 1  # consume '-'
            if pattern[j] == "\\":
                if j + 1 >= n:
                    raise ValueError("trailing backslash in class")
                hi = pattern[j + 1]
                j += 2
            else:
                hi = pattern[j]
                j += 1
            items.append(("range", lo, hi))
        else:
            items.append(("char", lo))

    if j >= n:
        raise ValueError("unterminated character class")
    j += 1  # skip closing ']'

    def matcher(ch, items=items, negated=negated):
        hit = False
        for item in items:
            if item[0] == "char":
                if ch == item[1]:
                    hit = True
                    break
            else:  # range
                if item[1] <= ch <= item[2]:
                    hit = True
                    break
        return (not hit) if negated else hit

    return matcher, j


def _match(tokens, ti: int, text: str, si: int) -> bool:
    """Try to match tokens[ti:] against text[si:], anchored to the end."""
    if ti == len(tokens):
        return si == len(text)

    matcher, quant = tokens[ti]

    if quant == "":
        if si < len(text) and matcher(text[si]):
            return _match(tokens, ti + 1, text, si + 1)
        return False

    if quant == "?":
        # Greedy: try matching one first, then zero.
        if si < len(text) and matcher(text[si]):
            if _match(tokens, ti + 1, text, si + 1):
                return True
        return _match(tokens, ti + 1, text, si)

    if quant == "*" or quant == "+":
        # Greedily consume as many as possible, then backtrack.
        max_si = si
        while max_si < len(text) and matcher(text[max_si]):
            max_si += 1
        # Minimum number of repetitions required.
        min_count = 1 if quant == "+" else 0
        # Try the longest match first, giving back one repetition at a time.
        k = max_si
        while k - si >= min_count:
            if _match(tokens, ti + 1, text, k):
                return True
            k -= 1
        return False

    raise ValueError("unknown quantifier: " + quant)


def fullmatch(pattern: str, text: str) -> bool:
    """Return True iff `pattern` matches the ENTIRE `text`."""
    tokens = _parse(pattern)
    return _match(tokens, 0, text, 0)
