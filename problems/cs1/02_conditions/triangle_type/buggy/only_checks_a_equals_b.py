def triangle_type(a: float, b: float, c: float) -> str:
    if a <= 0 or b <= 0 or c <= 0:
        return "invalid"
    if a + b <= c or a + c <= b or b + c <= a:
        return "invalid"
    if a == b == c:
        return "equilateral"
    if a == b:  # bug: misses the other pairs, so (8, 5, 5) is called scalene
        return "isosceles"
    return "scalene"
