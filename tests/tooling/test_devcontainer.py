"""tools/devcontainer.sh, which runs a command in the devcontainer's image.

The script is run for real, with a stand-in for docker on its path that
writes each command it was given to a log and knows only the images the
test says exist, so the tests can say what the script asked Docker for
without Docker.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "devcontainer.sh"
DOCKERFILE = REPO / ".devcontainer" / "Dockerfile"
TAG = (
    "socpuppet-dev:" + hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:12]
)

# A docker that logs each command, and has an image only if the test said so.
DOCKER = """
import json, os, sys
args = sys.argv[1:]
with open(os.environ["LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[:2] == ["image", "inspect"]:
    sys.exit(0 if args[2] in os.environ.get("IMAGES", "").split() else 1)
"""

# A uname that says what the test wants it to.
UNAME = """
import os
print(os.environ.get("UNAME", "Darwin"))
"""


@pytest.fixture
def devcontainer(tmp_path):
    """Run the script with the stand-ins; returns (result, docker's calls)."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"
    for name, body in {"docker": DOCKER, "uname": UNAME}.items():
        program = bin_directory / name
        program.write_text(f"#!{sys.executable}\n{body}")
        program.chmod(0o755)

    # The caller's own SOCPUPPET_* variables would reach the container too.
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("SOCPUPPET_")
    }

    def run(*args, images=(TAG,), env=None):
        result = subprocess.run(
            ["bash", str(SCRIPT), *args],
            env={
                **inherited,
                "PATH": f"{bin_directory}{os.pathsep}{os.defpath}",
                "LOG": str(log),
                "IMAGES": " ".join(images),
                **(env or {}),
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        lines = log.read_text().splitlines() if log.exists() else []
        return result, [json.loads(line) for line in lines]

    return run


def runs(calls):
    """The arguments of each `docker run` among docker's calls."""
    return [call[1:] for call in calls if call[0] == "run"]


def values(call, option):
    """What each `option VALUE` of a docker command gave, in order."""
    return [call[i + 1] for i, word in enumerate(call[:-1]) if word == option]


def test_the_command_runs_in_the_devcontainers_image_with_the_repository_at_workspace(
    devcontainer,
):
    command = ["uv", "run", "pytest", "-k", "spam eggs"]

    result, calls = devcontainer(*command)

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert f"{REPO}:/workspace" in values(run, "--volume")
    assert values(run, "--workdir") == ["/workspace"]
    assert run[-len(command) - 1 :] == [TAG, *command]


def test_an_image_is_built_from_the_dockerfile_when_none_has_its_hash_and_is_also_named_socpuppet_dev(
    devcontainer,
):
    result, calls = devcontainer("true", images=())

    assert result.returncode == 0, result.stdout
    (build,) = [call[1:] for call in calls if call[0] == "build"]
    assert set(values(build, "--tag")) == {TAG, "socpuppet-dev"}
    assert values(build, "--file") == [str(DOCKERFILE)]
    assert build[-1] == str(DOCKERFILE.parent)
    assert calls.index(["build", *build]) < calls.index(["run", *runs(calls)[0]])


def test_an_image_already_built_from_this_dockerfile_is_not_built_again(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    assert not [call for call in calls if call[0] == "build"]


def test_qboxs_two_trees_are_docker_volumes_at_their_usual_places_under_build(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    volumes = values(run, "--volume")
    assert "socpuppet-qbox:/workspace/build/qbox" in volumes
    assert "socpuppet-qbox-dev:/workspace/build/qbox-dev" in volumes


def test_uvs_environment_cache_and_pythons_are_under_build_so_they_outlive_the_container(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    environment = dict(each.split("=", 1) for each in values(run, "--env"))
    # The Linux venv and Python that firmware/twister.sh makes, so that the
    # two share one.
    assert environment["UV_PROJECT_ENVIRONMENT"] == "/workspace/build/linux-venv"
    assert environment["UV_PYTHON_INSTALL_DIR"] == "/workspace/build/firmware/python"
    assert environment["UV_CACHE_DIR"].startswith("/workspace/build/")


def test_socpuppet_variables_in_the_callers_environment_reach_the_container(
    devcontainer,
):
    result, calls = devcontainer(
        "true",
        env={"SOCPUPPET_REQUIRE_FIRMWARE": "1", "SOCPUPPET_CPU": "qbox_cpu"},
    )

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    environment = values(run, "--env")
    assert "SOCPUPPET_REQUIRE_FIRMWARE=1" in environment
    assert "SOCPUPPET_CPU=qbox_cpu" in environment


def test_on_linux_the_container_runs_as_the_caller_so_that_nothing_in_build_is_roots(
    devcontainer,
):
    result, calls = devcontainer("true", env={"UNAME": "Linux"})

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert values(run, "--user") == [f"{os.getuid()}:{os.getgid()}"]


def test_on_a_mac_the_container_runs_as_its_own_user(devcontainer):
    result, calls = devcontainer("true", env={"UNAME": "Darwin"})

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert values(run, "--user") == []
