# Auto-generated from OpenAI HumanEval HumanEval/45. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import triangle_area as candidate

METADATA = {}


def check(candidate):
    assert candidate(5, 3) == 7.5
    assert candidate(2, 2) == 2.0
    assert candidate(10, 8) == 40.0


def test_he_045():
    check(candidate)
