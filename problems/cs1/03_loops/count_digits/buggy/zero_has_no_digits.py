def count_digits(n: int) -> int:
    n = abs(n)
    digits = 0
    while n > 0:  # bug: for n = 0 the loop never runs, so 0 gets 0 digits instead of 1
        n //= 10
        digits += 1
    return digits
