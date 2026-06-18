# Word frequency

Implement **`solution.go`** in `package challenge` exporting:

```go
func WordFrequency(text string) map[string]int
```

Count how many times each word occurs in `text` and return the counts in a map.

Rules:

- Split `text` into tokens on **whitespace** (spaces, tabs, newlines).
- For each token, strip any **surrounding ASCII punctuation** (leading and trailing).
  Punctuation in the middle of a token is kept.
- **Lowercase** each word before counting.
- If, after stripping, a token is empty, skip it (do not count an empty string).
- For empty or whitespace-only input, return an **empty, non-nil** map (length 0).

ASCII punctuation is the set of characters for which Go's `unicode.IsPunct` returns true
together with symbols such as `+`, `<`, `=`, etc. For this challenge, treat a byte as
"punctuation to strip" when it is an ASCII byte that is **not** a letter or digit.

Examples:

- `WordFrequency("the cat sat on the mat")` →
  `{"the": 2, "cat": 1, "sat": 1, "on": 1, "mat": 1}`
- `WordFrequency("Hello, hello! HELLO.")` → `{"hello": 3}`
- `WordFrequency("don't stop")` → `{"don't": 1, "stop": 1}` (interior apostrophe kept)
- `WordFrequency("   ")` → `{}` (empty, non-nil map)
