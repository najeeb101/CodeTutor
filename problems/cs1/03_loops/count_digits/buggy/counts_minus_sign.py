def count_digits(n: int) -> int:
    return len(str(n))  # bug: str(-123) is "-123", and the minus sign is not a digit
