def rectangle_stats(width: float, height: float) -> list[float]:
    """Return [area, perimeter] of a rectangle."""
    area = width * height
    perimeter = 2 * (width + height)
    return [area, perimeter]
