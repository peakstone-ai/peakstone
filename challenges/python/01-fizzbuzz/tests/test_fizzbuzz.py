from solution import fizzbuzz


def test_basic():
    assert fizzbuzz(5) == ["1", "2", "Fizz", "4", "Buzz"]


def test_fizzbuzz_15():
    out = fizzbuzz(15)
    assert out[2] == "Fizz"
    assert out[4] == "Buzz"
    assert out[14] == "FizzBuzz"
    assert len(out) == 15


def test_non_positive():
    assert fizzbuzz(0) == []
    assert fizzbuzz(-3) == []


def test_all_strings():
    assert all(isinstance(x, str) for x in fizzbuzz(30))
