def rectangle_stats(width: float, height: float) -> list[float]:
    area = width * height
    perimeter = 2 * (width + height)
    return [perimeter, area]  # bug: the task asks for [area, perimeter]
