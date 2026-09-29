def max_of_three(a: int, b: int, c: int) -> int:
    if a > b and a > c:
        return a
    elif b > a and b > c:
        return b
    else:
        return c  # bug: with a tie like (5, 5, 1), neither check is true, so it returns 1
