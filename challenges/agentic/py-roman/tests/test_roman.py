from solution import roman_to_int


def test_simple():
    assert roman_to_int("III") == 3
    assert roman_to_int("LVIII") == 58


def test_subtractive_units():
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9


def test_subtractive_tens():
    assert roman_to_int("XL") == 40
    assert roman_to_int("XC") == 90


def test_subtractive_hundreds():
    assert roman_to_int("CD") == 400
    assert roman_to_int("CM") == 900


def test_large_mixed():
    assert roman_to_int("MCMXCIV") == 1994
    assert roman_to_int("MMXXIV") == 2024
