# Auto-generated from OpenAI HumanEval HumanEval/131. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import digits as candidate

def check(candidate):

    # Check some simple cases
    assert candidate(5) == 5
    assert candidate(54) == 5
    assert candidate(120) ==1
    assert candidate(5014) == 5
    assert candidate(98765) == 315
    assert candidate(5576543) == 2625

    # Check some edge cases that are easy to work out by hand.
    assert candidate(2468) == 0


def test_he_131():
    check(candidate)
