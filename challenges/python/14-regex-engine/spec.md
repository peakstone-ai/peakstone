# Backtracking regex matcher

Implement a file **`solution.py`** containing a function `fullmatch` that decides
whether a regular expression matches a string. You must implement the matching
yourself with a **backtracking** algorithm — **do not** call Python's `re` module.

```python
def fullmatch(pattern: str, text: str) -> bool:
    """Return True iff `pattern` matches the ENTIRE `text`."""
```

`fullmatch` is **anchored**: the pattern must consume the entire `text`, as if it
were wrapped in an implicit `^...$`. Matching only a prefix of `text` is **not**
a match.

## Supported syntax

An *element* is the smallest matchable unit. It is one of:

- A **literal character** — matches exactly itself (e.g. `a` matches `"a"`).
- `.` — matches **any single character**.
- An **escaped character** `\x` — the backslash strips any special meaning from
  the next character, which then matches **literally**. So `\.` matches a literal
  `.`, `\*` a literal `*`, `\\` a literal backslash, `\[` a literal `[`. Escaping
  an ordinary character (e.g. `\a`) just matches that character.
- A **character class** `[...]`:
  - `[abc]` matches any **one** of the listed characters.
  - `[^abc]` matches any one character **not** listed (a *negated* class). The `^`
    is special only as the **first** character inside the brackets.
  - **Ranges** like `[a-z]`, `[0-9]`, `[A-Za-z0-9]` match any character whose code
    point falls in the (inclusive) range.
  - A `-` that appears **first or last** inside the class (right after `[` or
    `[^`, or right before `]`) is a **literal** `-`, not a range.
  - A class always matches **exactly one** character of `text` (so a class can
    never match against the empty string at a position).

## Quantifiers

A quantifier applies to the **single preceding element**:

- `*` — **zero or more** of the preceding element.
- `+` — **one or more** of the preceding element.
- `?` — **zero or one** of the preceding element.

Quantifiers are **greedy**: they consume as many repetitions as possible, but they
**must backtrack** — giving repetitions back one at a time — so that the rest of
the pattern can still match and the **whole** text can be consumed.

A quantifier always binds to the whole element immediately to its left, where an
element is a literal char, an escaped char `\x`, `.`, or an entire `[...]` class.
For example, in `a[0-9]*b` the `*` applies to the class `[0-9]`, and in `\.*` the
`*` applies to the escaped literal dot.

## Not supported

There are **no** groups `(...)` and **no** alternation `|`. You do not need to
handle them.

## Semantics / edge cases

- The **empty pattern** matches **only** the empty string.
- `a*` matches `""` (zero repetitions). `a+` does **not** match `""`.
- Greedy backtracking: `a*a` matches `"aaa"` — the `*` first grabs all three
  `a`s, then gives one back so the trailing `a` can match.
- `.*` matches **anything** (including `""`); `.+` matches any non-empty string.
- Anchoring: `a` does **not** match `"ab"` (trailing `b` unconsumed), and `b` does
  not match `"ab"` (leading `a` unconsumed).

## Worked example

```python
assert fullmatch("a*a", "aaa") is True      # '*' backtracks, gives back one 'a'
assert fullmatch("a+", "") is False         # '+' needs at least one
assert fullmatch("a?b", "b") is True        # '?' matches zero
assert fullmatch("[a-z]+[0-9]*", "abc12") is True
assert fullmatch("[^0-9]+", "abc") is True  # negated class
assert fullmatch("h\\.t", "h.t") is True    # escaped dot is literal
assert fullmatch("h.t", "hat") is True      # '.' matches any char
assert fullmatch("a.c", "ac") is False      # '.' needs one char
assert fullmatch("colou?r", "color") is True
assert fullmatch("", "") is True
assert fullmatch("", "x") is False
```
