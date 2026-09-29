def factorial(n: int) -> int:
    """Return n! (the product 1 * 2 * ... * n); 0! is 1."""
    result = 1
    for number in range(2, n + 1):
        result *= number
    return result
