# Auto-generated from OpenAI HumanEval HumanEval/72. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import will_it_fly as candidate

def check(candidate):

    # Check some simple cases
    assert candidate([3, 2, 3], 9) is True
    assert candidate([1, 2], 5) is False
    assert candidate([3], 5) is True
    assert candidate([3, 2, 3], 1) is False


    # Check some edge cases that are easy to work out by hand.
    assert candidate([1, 2, 3], 6) is False
    assert candidate([5], 5) is True


def test_he_072():
    check(candidate)
