def gcd(a: int, b: int) -> int:
    if a % b == 0:  # bug: ZeroDivisionError when b is 0; check b == 0 first
        return b
    return gcd(b, a % b)
