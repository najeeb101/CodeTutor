def max_of_three(a: int, b: int, c: int) -> int:
    largest = 0  # bug: if all numbers are negative, 0 stays the "largest"
    if a > largest:
        largest = a
    if b > largest:
        largest = b
    if c > largest:
        largest = c
    return largest
