# Auto-generated from OpenAI HumanEval HumanEval/147. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import get_max_triples as candidate

def check(candidate):

    assert candidate(5) == 1
    assert candidate(6) == 4
    assert candidate(10) == 36
    assert candidate(100) == 53361


def test_he_147():
    check(candidate)
