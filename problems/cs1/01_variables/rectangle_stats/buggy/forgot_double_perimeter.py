def rectangle_stats(width: float, height: float) -> list[float]:
    area = width * height
    perimeter = width + height  # bug: only two of the four sides
    return [area, perimeter]
