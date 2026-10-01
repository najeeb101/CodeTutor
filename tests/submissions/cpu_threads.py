# Uses CPU time faster than wall time: hashlib releases the GIL for big inputs, so these threads
# really run in parallel. The runner's CPU limit (RLIMIT_CPU) then fires before the wall-clock limit.
import hashlib
import threading

# Small stacks: each thread reserves its stack in the address space, and 8 MB stacks hit the
# memory limit (RLIMIT_AS) after about 4 threads (measured).
threading.stack_size(256 * 1024)
DATA = b"x" * 10_000_000


def burn():
    while True:
        hashlib.sha256(DATA).digest()


for _ in range(4):
    threading.Thread(target=burn, daemon=True).start()
burn()  # the main thread too, so loading never finishes


def sum_of_evens(n):
    return 0
