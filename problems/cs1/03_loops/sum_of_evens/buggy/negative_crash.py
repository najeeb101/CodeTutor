def sum_of_evens(n: int) -> int:
    if n < 0:
        raise ValueError("n must be positive")  # bug: spec says return 0
    return sum(range(2, n + 1, 2))
