"""Pure-logic tests for the Codeforces importer (no network)."""
from __future__ import annotations

from peakstone.engine.importers import codeforces as cf


def test_cid_and_difficulty():
    assert cf._cid("2063/A") == "cf-2063-a"
    assert cf._difficulty(800) == 2 and cf._difficulty(1400) == 3
    assert cf._difficulty(1900) == 4 and cf._difficulty(3000) == 5
    assert cf._difficulty(None) == 3 and cf._difficulty(0) == 3


def test_date():
    assert cf._date(1737547500) == "2025-01-22"     # Codeforces Round 1000
    assert cf._date(None) == ""


def test_gradeable_filters():
    base = {"input_mode": "stdio", "official_tests": [{"input": "1\n", "output": "1\n"}]}
    assert cf.gradeable(base)
    assert not cf.gradeable({**base, "interaction_format": "..."})     # interactive
    assert not cf.gradeable({**base, "generated_checker": "..."})      # special judge
    assert not cf.gradeable({**base, "input_mode": "file"})            # not stdio
    assert not cf.gradeable({"input_mode": "stdio"})                   # no tests
    # examples alone (no official_tests) still count
    assert cf.gradeable({"input_mode": "stdio", "examples": [{"input": "1", "output": "1"}]})


def test_cases_dedup_normalize_and_cap():
    r = {"official_tests": [{"input": "1\r\n2\r\n", "output": "3\r\n"},
                            {"input": "1\r\n2\r\n", "output": "3\r\n"}],   # dup of #1
         "examples": [{"input": "4\n5\n", "output": "9\n"}]}
    cases, dropped = cf._cases(r, max_cases=10)
    assert len(cases) == 2 and dropped == 0
    assert cases[0]["input"] == "1\n2\n" and "\r" not in cases[0]["output"]   # CRLF normalized
    capped, dropped2 = cf._cases(r, max_cases=1)
    assert len(capped) == 1 and dropped2 == 1


def test_toml_str_escapes():
    assert cf._toml_str('a "b" \\c') == 'a \\"b\\" \\\\c'
