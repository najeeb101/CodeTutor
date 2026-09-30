def primes_up_to(n: int) -> list[int]:
    """Return all prime numbers <= n, from small to large."""
    if n < 2:
        return []
    # Sieve of Eratosthenes: is_candidate[k] stays True only if k is prime.
    is_candidate = [True] * (n + 1)
    is_candidate[0] = False
    is_candidate[1] = False
    for number in range(2, n + 1):
        if is_candidate[number]:
            # Smaller multiples were crossed out by smaller primes: start at number * number.
            for multiple in range(number * number, n + 1, number):
                is_candidate[multiple] = False
    return [number for number in range(2, n + 1) if is_candidate[number]]
