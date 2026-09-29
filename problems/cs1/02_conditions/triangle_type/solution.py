def triangle_type(a: float, b: float, c: float) -> str:
    """Return "equilateral", "isosceles", "scalene" or "invalid"."""
    if a <= 0 or b <= 0 or c <= 0:
        return "invalid"
    if a + b <= c or a + c <= b or b + c <= a:
        return "invalid"
    if a == b == c:
        return "equilateral"
    if a == b or b == c or a == c:
        return "isosceles"
    return "scalene"
