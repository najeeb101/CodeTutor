def sum_of_evens(n):
    with open("big.bin", "wb") as f:
        f.write(b"\0" * (100 * 1024 * 1024))
    return sum(range(2, n + 1, 2))
