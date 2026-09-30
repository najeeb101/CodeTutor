def is_prime(n: int) -> bool:
    """Return True if n is a prime number."""
    if n < 2:
        return False
    divisor = 2
    # Divisors come in pairs (d and n // d), and one of each pair is at most the square root
    # of n. So stop there. Comparing divisor * divisor avoids floats.
    while divisor * divisor <= n:
        if n % divisor == 0:
            return False
        divisor += 1
    return True
