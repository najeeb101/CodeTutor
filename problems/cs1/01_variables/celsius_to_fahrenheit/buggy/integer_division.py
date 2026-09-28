def celsius_to_fahrenheit(c: float) -> float:
    return c * 9 // 5 + 32  # bug: // throws away the decimals (only right for multiples of 5)
