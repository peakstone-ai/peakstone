import random

from solution import longest_k_repeated


def brute(s, k):
    """O(n^2) reference oracle for small strings."""
    n = len(s)
    if n == 0 or k < 1:
        return 0
    for L in range(n, 0, -1):
        seen = {}
        for i in range(n - L + 1):
            sub = s[i:i + L]
            c = seen.get(sub, 0) + 1
            seen[sub] = c
            if c >= k:
                return L
    return 0


def test_empty_string():
    assert longest_k_repeated("", 1) == 0
    assert longest_k_repeated("", 2) == 0
    assert longest_k_repeated("", 5) == 0


def test_k_one_is_whole_string():
    assert longest_k_repeated("a", 1) == 1
    assert longest_k_repeated("abc", 1) == 3
    assert longest_k_repeated("abcabc", 1) == 6


def test_no_repeat_returns_zero():
    # All distinct characters: nothing occurs twice.
    assert longest_k_repeated("abcdef", 2) == 0
    assert longest_k_repeated("a", 2) == 0
    assert longest_k_repeated("xyz", 3) == 0


def test_single_char_runs():
    # "aaa": 'a' x3, 'aa' x2, 'aaa' x1
    assert longest_k_repeated("aaa", 1) == 3
    assert longest_k_repeated("aaa", 2) == 2
    assert longest_k_repeated("aaa", 3) == 1
    assert longest_k_repeated("aaa", 4) == 0


def test_banana():
    # classic: "ana" occurs at positions 1 and 3 (overlapping)
    assert longest_k_repeated("banana", 2) == 3
    # "a" occurs 3 times, "an"/"na" twice, "ana" twice
    assert longest_k_repeated("banana", 3) == 1
    assert longest_k_repeated("banana", 4) == 0


def test_overlapping_counts():
    # "aaaa": "aaa" occurs at 0 and 1 -> length 3 for k=2
    assert longest_k_repeated("aaaa", 2) == 3
    assert longest_k_repeated("aaaa", 3) == 2
    assert longest_k_repeated("aaaa", 4) == 1


def test_disjoint_repeat():
    # "abcXabc": "abc" occurs twice, no overlap
    assert longest_k_repeated("abcXabc", 2) == 3
    assert longest_k_repeated("abcXabc", 3) == 0


def test_mixed_case_sensitive():
    # 'A' and 'a' are different characters.
    # "AaAa": "Aa" occurs at 0 and 2 (len 2); "AaA" occurs once, "aAa" once.
    assert longest_k_repeated("AaAa", 2) == 2


def test_period_two_medium():
    s = "ab" * 50
    n = len(s)
    # periodic with period 2: s[0..n-3] == s[2..n-1]
    assert longest_k_repeated(s, 2) == n - 2


def test_matches_brute_small_random():
    rng = random.Random(1234)
    for _ in range(400):
        n = rng.randint(0, 12)
        alpha = "ab" if rng.random() < 0.5 else "abc"
        s = "".join(rng.choice(alpha) for _ in range(n))
        for k in range(1, 6):
            assert longest_k_repeated(s, k) == brute(s, k), (s, k)


def test_matches_brute_larger_alphabet():
    rng = random.Random(99)
    for _ in range(150):
        n = rng.randint(0, 40)
        s = "".join(rng.choice("abcde") for _ in range(n))
        for k in range(1, 4):
            assert longest_k_repeated(s, k) == brute(s, k), (s, k)


def test_large_all_same():
    s = "a" * 100000
    assert longest_k_repeated(s, 2) == 99999
    assert longest_k_repeated(s, 100000) == 1
    assert longest_k_repeated(s, 100001) == 0


def test_large_period_two():
    s = "ab" * 50000
    n = len(s)  # 100000
    assert longest_k_repeated(s, 2) == n - 2


def test_large_no_long_repeat():
    # Random over a 10-char alphabet: the longest repeat must be short.
    rng = random.Random(7)
    s = "".join(rng.choice("abcdefghij") for _ in range(60000))
    ans = longest_k_repeated(s, 2)
    # There must be some repeat (pigeonhole on length-1 substrings), and it
    # should be far shorter than the whole string.
    assert 1 <= ans < 1000
