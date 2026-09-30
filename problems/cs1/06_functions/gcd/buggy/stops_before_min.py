def gcd(a: int, b: int) -> int:
    best = 1
    for divisor in range(1, min(a, b)):  # bug: stops before min(a, b), which can be the answer
        if a % divisor == 0 and b % divisor == 0:
            best = divisor
    return best
