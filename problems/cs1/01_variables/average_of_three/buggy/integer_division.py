def average_of_three(a: float, b: float, c: float) -> float:
    return round((a + b + c) // 3, 2)  # bug: // throws away the decimals of the average
