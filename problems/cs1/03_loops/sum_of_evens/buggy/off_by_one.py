def sum_of_evens(n: int) -> int:
    total = 0
    for number in range(2, n, 2):  # bug: excludes n itself
        total += number
    return total
