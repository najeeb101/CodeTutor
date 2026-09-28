def sum_of_evens(n: int) -> int:
    """Return the sum of all even numbers from 1 to n (inclusive)."""
    total = 0
    for number in range(2, n + 1, 2):
        total += number
    return total
