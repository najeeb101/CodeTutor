def average_of_three(a: float, b: float, c: float) -> float:
    return round(a + b + c / 3, 2)  # bug: only c is divided by 3 (division happens first)
