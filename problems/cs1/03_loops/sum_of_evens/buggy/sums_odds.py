def sum_of_evens(n: int) -> int:
    total = 0
    for number in range(1, n + 1):
        if number % 2 == 1:  # bug: wrong condition
            total += number
    return total
