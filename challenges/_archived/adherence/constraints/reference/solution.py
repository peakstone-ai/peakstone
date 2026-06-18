def process(numbers):
    return sum(n * n for n in numbers if n % 2 == 0)
