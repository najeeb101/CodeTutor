def count_digits(n: int) -> int:
    """Return how many digits n has (the minus sign is not a digit)."""
    n = abs(n)
    digits = 1
    while n >= 10:
        n //= 10
        digits += 1
    return digits
