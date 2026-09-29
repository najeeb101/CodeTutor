def factorial(n: int) -> int:
    if n <= 1:
        return n  # bug: right for 1, but 0! is 1, not 0
    result = 1
    for number in range(2, n + 1):
        result *= number
    return result
