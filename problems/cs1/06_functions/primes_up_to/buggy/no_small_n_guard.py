def primes_up_to(n: int) -> list[int]:
    # bug: no "if n < 2: return []". For n = 0 the list has only 1 item, so setting
    # is_candidate[1] raises IndexError (and for negative n the list is empty).
    is_candidate = [True] * (n + 1)
    is_candidate[0] = False
    is_candidate[1] = False
    for number in range(2, n + 1):
        if is_candidate[number]:
            for multiple in range(number * number, n + 1, number):
                is_candidate[multiple] = False
    return [number for number in range(2, n + 1) if is_candidate[number]]
