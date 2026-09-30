# Tries to start 200 processes (a bounded fork bomb). Docker must stop it at the pids limit (64).
# Each child only sleeps; they all die with the container.
import os
import time

started = 0
for _ in range(200):
    try:
        pid = os.fork()
    except OSError:
        break
    if pid == 0:  # in the child: wait quietly, never run the rest of this file
        time.sleep(60)
        os._exit(0)
    started += 1
print(f"STARTED={started}")


def sum_of_evens(n):
    return sum(range(2, n + 1, 2))
