# Tries to read a file on the host. The test replaces the placeholder with the path of a secret file
# it wrote in a temp folder. Docker must block this (the file isn't in the container).
SECRET_PATH = "__SECRET_PATH__"

try:
    with open(SECRET_PATH) as secret:
        print("STOLEN=" + secret.read())
except OSError as exc:
    print("BLOCKED=" + type(exc).__name__)


def sum_of_evens(n):
    return sum(range(2, n + 1, 2))
