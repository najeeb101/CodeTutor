def is_prime(n: int) -> bool:
    if n < 2:
        return False
    for divisor in range(2, n):  # bug: right answers, but for n near 10**9 this takes ~40 s
        if n % divisor == 0:
            return False
    return True
