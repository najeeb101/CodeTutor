# The grading image: the pinned Python from grader/sandbox.py (DOCKER_IMAGE) plus the runner, and
# nothing else. The containerized worker uses it instead of bind-mounting runner.py from its own
# disk (a path the Docker daemon can't see). DockerSandbox(runner_in_image=True) checks at start
# that the runner in here is byte-identical to the worker's own, so a stale image can't grade.
FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
COPY src/codetutor/grader/runner.py /sandbox/runner.py
