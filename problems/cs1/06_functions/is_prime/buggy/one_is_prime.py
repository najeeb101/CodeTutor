def is_prime(n: int) -> bool:
    if n < 1:  # bug: 1 is not a prime number; the check must be n < 2
        return False
    divisor = 2
    while divisor * divisor <= n:
        if n % divisor == 0:
            return False
        divisor += 1
    return True
