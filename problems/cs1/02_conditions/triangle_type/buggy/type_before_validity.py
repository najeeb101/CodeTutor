def triangle_type(a: float, b: float, c: float) -> str:
    if a == b == c:  # bug: checked before validity, so (0, 0, 0) is "equilateral"
        return "equilateral"
    if a <= 0 or b <= 0 or c <= 0:
        return "invalid"
    if a + b <= c or a + c <= b or b + c <= a:
        return "invalid"
    if a == b or b == c or a == c:
        return "isosceles"
    return "scalene"
