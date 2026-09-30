# Tries to open a network connection (a public DNS server). Docker must block this (--network none).
import socket

try:
    socket.create_connection(("1.1.1.1", 53), timeout=1).close()
    print("CONNECTED")
except OSError as exc:
    print("BLOCKED=" + type(exc).__name__)


def sum_of_evens(n):
    return sum(range(2, n + 1, 2))
