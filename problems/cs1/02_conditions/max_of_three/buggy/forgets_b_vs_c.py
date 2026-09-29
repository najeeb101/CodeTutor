def max_of_three(a: int, b: int, c: int) -> int:
    if a >= b and a >= c:
        return a
    if b >= a:  # bug: never compares b with c
        return b
    return c
