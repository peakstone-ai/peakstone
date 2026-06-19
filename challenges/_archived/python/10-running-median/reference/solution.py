from sortedcontainers import SortedList


class RunningMedian:
    def __init__(self) -> None:
        self._data = SortedList()

    def add(self, x: float) -> None:
        self._data.add(x)

    def median(self) -> float:
        n = len(self._data)
        if n == 0:
            raise ValueError("median of empty stream")
        mid = n // 2
        if n % 2 == 1:
            return self._data[mid]
        return (self._data[mid - 1] + self._data[mid]) / 2
