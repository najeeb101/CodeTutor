def sum_of_evens(n):
    while n < 0:  # never ends for negative n
        pass
    return sum(range(2, n + 1, 2))
