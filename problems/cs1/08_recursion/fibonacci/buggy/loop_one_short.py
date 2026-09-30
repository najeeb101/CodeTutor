def fibonacci(n: int) -> int:
    previous, current = 0, 1
    for _ in range(n - 1):  # bug: one step too few, so this returns fib(n - 1)
        previous, current = current, previous + current
    return previous
