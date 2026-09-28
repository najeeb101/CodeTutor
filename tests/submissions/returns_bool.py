def sum_of_evens(n):
    if n < 2:
        return False  # False == 0 in Python, but it must not pass
    return sum(range(2, n + 1, 2))
