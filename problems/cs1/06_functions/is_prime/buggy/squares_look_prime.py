def is_prime(n: int) -> bool:
    if n < 2:
        return False
    divisor = 2
    while divisor * divisor < n:  # bug: must be <=, or squares like 4, 9 and 25 look prime
        if n % divisor == 0:
            return False
        divisor += 1
    return True
