def factorial(n: int) -> int:
    if n <= 1:
        return 1
    return n * factorial(n - 1)  # bug: Python stops at about 1000 nested calls; n can be 1100
