def max_of_three(a: int, b: int, c: int) -> int:
    """Return the largest of a, b and c."""
    largest = a
    if b > largest:
        largest = b
    if c > largest:
        largest = c
    return largest
