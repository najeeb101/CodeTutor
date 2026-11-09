"""The runner baked into a grading image (Deploy Step 1): for a worker that runs in a container.

The unit tests need no Docker. The `docker` ones build small images and grade with them.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from codetutor.grader import DockerSandbox, SandboxUnavailableError, grade
from codetutor.grader.models import SandboxJob
from codetutor.grader.sandbox import DOCKER_IMAGE, DOCKER_RUNNER_PATH, RUNNER_PATH, docker_command
from codetutor.problems.loader import load_problem

REPO = Path(__file__).resolve().parents[1]
TEST_IMAGE = "codetutor-sandbox:test"
STALE_IMAGE = "codetutor-sandbox:test-stale"


def _job() -> SandboxJob:
    return SandboxJob(
        token="t",
        code="def f():\n    return 1\n",
        function_name="f",
        tests=[],
        per_test_timeout_s=1.0,
        total_timeout_s=2.0,
        memory_mb=256,
        max_file_mb=1,
        max_output_bytes=1000,
    )


def test_the_default_command_bind_mounts_the_local_runner() -> None:
    argv = docker_command(DOCKER_IMAGE, _job(), "c1", runner_in_image=False)
    mount = argv[argv.index("--mount") + 1]
    assert f"src={RUNNER_PATH}" in mount and mount.endswith(",readonly")
    assert argv[-1] == DOCKER_RUNNER_PATH


# TODO(najeeb): write `test_the_image_command_has_no_mount_but_keeps_every_guard`. Build the argv
# with runner_in_image=True (like the test above) and check three things: "--mount" is not in it,
# "--read-only" is in it, and the item after "--network" is "none". Hint: argv is a plain list,
# so `x in argv` and `argv[argv.index("--network") + 1]` are all you need.


def _build(tag: str, dockerfile: str, context: Path | None) -> None:
    if context is None:  # a Dockerfile on stdin, no files to copy
        cmd, text = ["docker", "build", "-q", "-t", tag, "-"], dockerfile
    else:
        cmd, text = ["docker", "build", "-q", "-t", tag, "-f", dockerfile, str(context)], None
    subprocess.run(cmd, input=text, capture_output=True, text=True, check=True)


@pytest.fixture(scope="module")
def image_sandbox() -> Iterator[DockerSandbox]:
    _build(TEST_IMAGE, str(REPO / "deploy" / "sandbox.Dockerfile"), REPO)
    yield DockerSandbox(TEST_IMAGE, runner_in_image=True)
    subprocess.run(["docker", "image", "rm", TEST_IMAGE], capture_output=True, check=False)


@pytest.mark.docker
@pytest.mark.parametrize("code_file", ["solution.py", "buggy/checks_fizz_first.py"])
def test_the_image_grades_exactly_like_the_bind_mount(
    image_sandbox: DockerSandbox, code_file: str
) -> None:
    folder = REPO / "problems/cs1/03_loops/fizzbuzz"
    problem = load_problem(folder)
    code = (folder / code_file).read_text()
    with_mount = grade(problem, code, sandbox=DockerSandbox())
    with_image = grade(problem, code, sandbox=image_sandbox)
    assert with_image.status == with_mount.status
    assert [t.status for t in with_image.tests] == [t.status for t in with_mount.tests]


@pytest.mark.docker
def test_an_image_with_another_runner_is_refused() -> None:
    stale = f"FROM {DOCKER_IMAGE}\nRUN mkdir /sandbox && echo '# old' > /sandbox/runner.py\n"
    _build(STALE_IMAGE, stale, None)
    try:
        with pytest.raises(SandboxUnavailableError, match="out of date"):
            DockerSandbox(STALE_IMAGE, runner_in_image=True)
    finally:
        subprocess.run(["docker", "image", "rm", STALE_IMAGE], capture_output=True, check=False)
