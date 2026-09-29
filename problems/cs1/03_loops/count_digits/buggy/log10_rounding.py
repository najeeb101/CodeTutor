import math


def count_digits(n: int) -> int:
    if n == 0:
        return 1
    # bug: log10 works with floats. log10(999999999999999) rounds up to exactly 15.0,
    # so this returns 16 for a number that has 15 digits.
    return int(math.log10(abs(n))) + 1
