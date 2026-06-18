import pytest

from solution import evaluate


def test_simple_addition():
    assert evaluate("1 + 2") == 3.0


def test_precedence():
    assert evaluate("2 + 3 * 4") == 14.0
    assert evaluate("1 + 2 * 3") == 7.0


def test_parentheses_override_precedence():
    assert evaluate("(2 + 3) * 4") == 20.0
    assert evaluate("(1 + 2) * 3") == 9.0


def test_division_is_float():
    assert evaluate("10 / 4") == 2.5
    assert isinstance(evaluate("4 / 2"), float)


def test_unary_minus():
    assert evaluate("-3 + 2") == -1.0
    assert evaluate("2 * -3") == -6.0
    assert evaluate("-(2 + 1)") == -3.0


def test_float_and_whitespace():
    assert evaluate("  3.14 + .86 ") == pytest.approx(4.0)
    assert evaluate("10. / 4") == 2.5


def test_left_associativity():
    assert evaluate("10 - 2 - 3") == 5.0
    assert evaluate("100 / 5 / 2") == 10.0


def test_nested_parens():
    assert evaluate("2 * (1 + (3 - 1) * 2)") == 10.0


def test_malformed_raises_value_error():
    for bad in ["", "   ", "1 +", "* 3", "1 2", "(1 + 2", "1 + 2)", "1 + * 2", "3 $ 4"]:
        with pytest.raises(ValueError):
            evaluate(bad)


def test_division_by_zero_raises():
    with pytest.raises((ValueError, ZeroDivisionError)):
        evaluate("1 / 0")
