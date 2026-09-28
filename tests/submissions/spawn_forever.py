import subprocess
import sys

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1000)"])
print(f"CHILD_PID={child.pid}")


def sum_of_evens(n):
    return sum(range(2, n + 1, 2))
