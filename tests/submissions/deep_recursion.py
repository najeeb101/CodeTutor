def sum_of_evens(n):
    return n + sum_of_evens(n - 1)  # no base case
