def fibonacci(n: int) -> int:
    """Return the n-th Fibonacci number (fib(0) = 0, fib(1) = 1)."""
    previous, current = 0, 1  # fib(0) and fib(1)
    # Each step moves one place forward in the sequence: n steps, one addition each.
    for _ in range(n):
        previous, current = current, previous + current
    return previous
