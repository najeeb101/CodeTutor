def gcd(a: int, b: int) -> int:
    for divisor in range(min(a, b), 0, -1):
        if a % divisor == 0 and b % divisor == 0:
            return divisor
    # bug: if a or b is 0, min(a, b) is 0 and the loop never runs. But gcd(0, 5) is 5 and
    # gcd(0, 0) is 0, not 1.
    return 1
