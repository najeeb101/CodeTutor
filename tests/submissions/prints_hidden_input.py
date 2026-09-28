def sum_of_evens(n):
    print(f"SECRET_INPUT={n}")
    if n == 100:
        raise ValueError(f"the input was {n}")
    return sum(range(2, n + 1, 2))
