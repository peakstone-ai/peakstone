"""Math answer extraction + matching (the answer-match scoring core)."""
from __future__ import annotations

from peakstone.engine import matheval
from peakstone.engine.importers import aime


def test_extract_boxed_wins():
    assert matheval.extract_answer("blah 12 ... so \\boxed{204}.") == "204"
    assert matheval.extract_answer("work: 5+5 \\boxed{ 70 } done") == "70"


def test_extract_phrasing_then_last_int():
    assert matheval.extract_answer("after work, the answer is 42.") == "42"
    assert matheval.extract_answer("first 3 then 7 then 99") == "99"   # last int fallback
    assert matheval.extract_answer("no digits here") is None
    assert matheval.extract_answer("") is None


def test_extract_prefers_final_box_over_intermediate():
    txt = "try 100, no. reconsider 250. Final: \\boxed{277}"
    assert matheval.extract_answer(txt) == "277"


def test_answers_match():
    assert matheval.answers_match("204", "204")
    assert matheval.answers_match("007", 7)            # leading zeros, int vs str
    assert matheval.answers_match(42, "42")
    assert not matheval.answers_match("204", "205")
    assert not matheval.answers_match(None, "1")
    assert not matheval.answers_match("1", None)


def test_aime_difficulty_escalates():
    assert aime._difficulty(0) == 3 and aime._difficulty(4) == 3
    assert aime._difficulty(5) == 4 and aime._difficulty(9) == 4
    assert aime._difficulty(10) == 5 and aime._difficulty(14) == 5
    assert aime._difficulty(15) == 3   # next paper wraps (problem 16 == position 1)
