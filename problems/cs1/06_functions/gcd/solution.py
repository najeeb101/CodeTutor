def gcd(a: int, b: int) -> int:
    """Return the greatest common divisor of a and b (gcd(0, 0) is 0)."""
    # Euclid: gcd(a, b) == gcd(b, a % b), and gcd(a, 0) == a.
    while b != 0:
        a, b = b, a % b
    return a
