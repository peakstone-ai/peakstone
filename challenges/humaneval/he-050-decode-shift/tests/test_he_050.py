# Auto-generated from OpenAI HumanEval HumanEval/50. Do not edit by hand.
from solution import *  # noqa: F401,F403 (prompt helpers may be referenced by tests)
from solution import decode_shift as candidate

METADATA = {}


def check(candidate):
    from random import randint, choice
    import copy
    import string

    letters = string.ascii_lowercase
    for _ in range(100):
        str = ''.join(choice(letters) for i in range(randint(10, 20)))
        encoded_str = encode_shift(str)
        assert candidate(copy.deepcopy(encoded_str)) == str


def test_he_050():
    check(candidate)
