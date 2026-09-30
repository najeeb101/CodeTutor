def is_prime(k: int) -> bool:
    if k < 2:
        return False
    divisor = 2
    while divisor * divisor <= k:
        if k % divisor == 0:
            return False
        divisor += 1
    return True


def primes_up_to(n: int) -> list[int]:
    primes = []
    for k in range(2, n):  # bug: range stops before n, so a prime n is missing
        if is_prime(k):
            primes.append(k)
    return primes
