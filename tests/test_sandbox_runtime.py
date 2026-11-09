"""The container runtime of the grading sandbox (Deploy Step 3): plain Docker (runc) or gVisor.

The unit tests need no Docker. The `docker` ones need the runtime they name: `runsc` is only
registered where deploy/install-gvisor.sh ran (CI's gvisor job and the server), so they skip
elsewhere, unless REQUIRE_RUNSC=1 says "this machine must have it" (then a skip is a failure).
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

import pytest

from codetutor.grader import DockerSandbox, SandboxUnavailableError
from codetutor.grader.models import SandboxJob
from codetutor.grader.sandbox import DOCKER_IMAGE, docker_command
from codetutor.settings import sandbox_runtime
from conftest import docker_runtime


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


def test_no_runtime_means_docker_default() -> None:
    assert "--runtime" not in docker_command(DOCKER_IMAGE, _job(), "c1")


def test_a_runtime_is_added_and_every_other_guard_stays() -> None:
    plain = docker_command(DOCKER_IMAGE, _job(), "c1")
    gvisor = docker_command(DOCKER_IMAGE, _job(), "c1", runtime="runsc")

    assert gvisor[gvisor.index("--runtime") + 1] == "runsc"
    without = [*gvisor[: gvisor.index("--runtime")], *gvisor[gvisor.index("--runtime") + 2 :]]
    assert without == plain  # the runtime is the only difference: all the locks are kept


def test_the_runtime_comes_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_RUNTIME", raising=False)
    assert sandbox_runtime() is None
    monkeypatch.setenv("SANDBOX_RUNTIME", "")
    assert sandbox_runtime() is None
    monkeypatch.setenv("SANDBOX_RUNTIME", "runsc")
    assert sandbox_runtime() == "runsc"


@pytest.mark.docker
def test_a_runtime_docker_does_not_know_is_refused_at_start() -> None:
    with pytest.raises(SandboxUnavailableError, match="not registered"):
        DockerSandbox(runtime="no-such-runtime")


@pytest.mark.docker
def test_the_grading_container_runs_under_gvisor_when_asked() -> None:
    if docker_runtime() != "runsc":
        if os.environ.get("REQUIRE_RUNSC") == "1":
            pytest.fail("REQUIRE_RUNSC=1 but TEST_SANDBOX_RUNTIME is not runsc")
        pytest.skip("gVisor is not registered here (deploy/install-gvisor.sh)")
    DockerSandbox(runtime="runsc")  # the canary passes
    inside = subprocess.run(
        ["docker", "run", "--rm", "--runtime", "runsc", "--network", "none", DOCKER_IMAGE]
        + ["python", "-c", "import platform; print(platform.release())"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # The container sees gVisor's own kernel, not the host's: that is the whole point.
    assert inside != platform.release(), (
        f"inside the container: {inside}, host: {platform.release()}"
    )


def test_the_install_script_tests_with_the_pinned_grading_image() -> None:
    script = (Path(__file__).resolve().parents[1] / "deploy" / "install-gvisor.sh").read_text()
    assert f'TEST_IMAGE="{DOCKER_IMAGE}"' in script


def test_the_install_script_pins_a_release_and_both_hashes() -> None:
    script = (Path(__file__).resolve().parents[1] / "deploy" / "install-gvisor.sh").read_text()
    assert re.search(r'^VERSION="\d{8}\.\d"$', script, re.MULTILINE)
    for arch in ("X86_64", "AARCH64"):
        assert re.search(rf'^SHA512_{arch}="[0-9a-f]{{128}}"$', script, re.MULTILINE), arch
