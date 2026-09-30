def is_prime(k: int) -> bool:
    if k < 1:  # bug: 1 is not a prime number; the check must be k < 2
        return False
    divisor = 2
    while divisor * divisor <= k:
        if k % divisor == 0:
            return False
        divisor += 1
    return True


def primes_up_to(n: int) -> list[int]:
    return [k for k in range(n + 1) if is_prime(k)]
