# Auto-generated from OpenAI HumanEval HumanEval/60. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import sum_to_n as candidate

METADATA = {}


def check(candidate):
    assert candidate(1) == 1
    assert candidate(6) == 21
    assert candidate(11) == 66
    assert candidate(30) == 465
    assert candidate(100) == 5050


def test_he_060():
    check(candidate)
