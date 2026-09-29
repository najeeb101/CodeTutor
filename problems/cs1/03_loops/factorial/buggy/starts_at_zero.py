def factorial(n: int) -> int:
    result = 0  # bug: 0 times anything is 0, so a product must start at 1
    for number in range(1, n + 1):
        result *= number
    return result
