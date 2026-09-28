import threading
import time

threading.Thread(target=time.sleep, args=(1000,)).start()  # non-daemon thread


def sum_of_evens(n):
    return sum(range(2, n + 1, 2))
