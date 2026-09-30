def fibonacci(n: int) -> int:
    if n < 2:
        return n
    # bug: right answers, but each call makes two more calls, and the same values are computed
    # again and again. fib(25) takes ~10 ms; fib(40) takes more than 10 seconds.
    return fibonacci(n - 1) + fibonacci(n - 2)
