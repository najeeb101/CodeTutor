def rectangle_stats(width: float, height: float) -> list[float]:
    width = int(width)  # bug: int() throws away the decimals (2.5 becomes 2)
    height = int(height)
    return [width * height, 2 * (width + height)]
