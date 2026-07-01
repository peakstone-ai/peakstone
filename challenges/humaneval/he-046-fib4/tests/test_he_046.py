# Auto-generated from OpenAI HumanEval HumanEval/46. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import fib4 as candidate

METADATA = {}


def check(candidate):
    assert candidate(5) == 4
    assert candidate(8) == 28
    assert candidate(10) == 104
    assert candidate(12) == 386


def test_he_046():
    check(candidate)
