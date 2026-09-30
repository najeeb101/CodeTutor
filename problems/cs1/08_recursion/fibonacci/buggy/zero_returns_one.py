def fibonacci(n: int) -> int:
    if n <= 1:
        return 1  # bug: right for n = 1, but fib(0) is 0
    previous, current = 0, 1
    for _ in range(n):
        previous, current = current, previous + current
    return previous
