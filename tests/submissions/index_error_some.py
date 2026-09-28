def sum_of_evens(n):
    if n % 2 == 1:
        return [][0]  # IndexError for odd n
    return sum(range(2, n + 1, 2))
