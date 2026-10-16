"""tools/devcontainer.py, which runs a command in the devcontainer's image.

The script is run for real, with a stand-in for docker on its path that
writes each command it was given to a log and knows only the images the
test says exist, so the tests can say what the script asked Docker for
without Docker.
"""

import hashlib
import json
import os
import platform
import pty
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "devcontainer.py"
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

# What the tool does differently on a Mac and on Linux is tested on the
# machine the tests run on.
ON_LINUX = pytest.mark.skipif(
    platform.system() != "Linux", reason="what it does on Linux, run there"
)
ON_A_MAC = pytest.mark.skipif(
    platform.system() != "Darwin", reason="what it does on a Mac, run there"
)

# Where the qbox preset puts QBox and socpuppet's tree built with it, in the
# container.
QBOX_PRESET = next(
    preset
    for preset in json.loads((REPO / "CMakePresets.json").read_text())[
        "configurePresets"
    ]
    if preset["name"] == "qbox"
)
QBOX_DEV = QBOX_PRESET["binaryDir"].replace("${sourceDir}", "/workspace")
QBOX = str(
    Path(
        QBOX_PRESET["cacheVariables"]["SOCPUPPET_QBOX_DIR"].replace(
            "${sourceDir}", "/workspace"
        )
    ).parent
)


@pytest.fixture
def devcontainer(tmp_path):
    """Run the script with the stand-ins; returns (result, docker's calls)."""
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    log = tmp_path / "log"

    def install(name, body):
        program = bin_directory / name
        program.write_text(f"#!{sys.executable}\n{body}")
        program.chmod(0o755)

    # The caller's own SOCPUPPET_* variables would reach the container too.
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("SOCPUPPET_")
    }

    def run(
        *args,
        images=(TAG,),
        env=None,
        terminal=False,
        docker=True,
    ):
        """Run it; with `terminal`, its input and output are a terminal."""
        log.unlink(missing_ok=True)
        if docker:
            install("docker", DOCKER)
            path = f"{bin_directory}{os.pathsep}{os.defpath}"
        else:
            # Only the stand-ins, since a Linux machine may have Docker in
            # /usr/bin.
            path = str(bin_directory)
        ours, theirs = pty.openpty() if terminal else (None, None)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            env={
                **inherited,
                "PATH": path,
                "LOG": str(log),
                "IMAGES": " ".join(images),
                **(env or {}),
            },
            stdin=theirs if terminal else subprocess.DEVNULL,
            stdout=theirs if terminal else subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )
        if terminal:
            os.close(theirs)
            os.close(ours)
        lines = log.read_text().splitlines() if log.exists() else []
        return result, [json.loads(line) for line in lines]

    return run


def runs(calls):
    """The arguments of each `docker run` among docker's calls."""
    return [call[1:] for call in calls if call[0] == "run"]


def values(call, option):
    """What each `option VALUE` of a docker command gave, in order."""
    return [call[i + 1] for i, word in enumerate(call[:-1]) if word == option]


def position(calls, command):
    """Where the only docker call of `command` (`run`, `build`) came."""
    (index,) = [i for i, call in enumerate(calls) if call[0] == command]
    return index


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
    assert position(calls, "build") < position(calls, "run")


def test_an_image_already_built_from_this_dockerfile_is_not_built_again(
    devcontainer,
):
    result, calls = devcontainer("true", images=(TAG,))

    assert result.returncode == 0, result.stdout
    assert not [call for call in calls if call[0] == "build"]


@ON_A_MAC
def test_on_a_mac_qboxs_two_trees_are_docker_volumes_where_the_qbox_preset_looks(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    volumes = values(run, "--volume")
    assert f"socpuppet-qbox:{QBOX}" in volumes
    assert f"socpuppet-qbox-dev:{QBOX_DEV}" in volumes


@ON_LINUX
def test_on_linux_qboxs_trees_are_the_repositorys_own_as_any_other_build_tree(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert values(run, "--volume") == [f"{REPO}:/workspace"]


def test_uvs_environment_cache_and_pythons_are_under_build_so_they_outlive_the_container(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    environment = dict(each.split("=", 1) for each in values(run, "--env"))
    for variable in (
        "UV_PROJECT_ENVIRONMENT",
        "UV_PYTHON_INSTALL_DIR",
        "UV_CACHE_DIR",
    ):
        assert environment[variable].startswith("/workspace/build/"), variable


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


@ON_LINUX
def test_on_linux_the_container_runs_as_the_caller_so_that_nothing_in_build_is_roots(
    devcontainer,
):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert values(run, "--user") == [f"{os.getuid()}:{os.getgid()}"]


@ON_A_MAC
def test_on_a_mac_the_container_runs_as_its_own_user(devcontainer):
    result, calls = devcontainer("true")

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert values(run, "--user") == []


def test_without_docker_the_tool_stops_and_says_to_install_docker_desktop(
    devcontainer,
):
    result, _ = devcontainer("true", docker=False)

    assert result.returncode != 0
    assert "Docker Desktop" in result.stdout


def test_without_a_command_the_usage_is_printed(devcontainer):
    result, calls = devcontainer()

    assert result.returncode == 2
    assert "usage: tools/devcontainer.py" in result.stdout
    assert not calls


def test_from_a_terminal_the_container_is_given_one_so_that_a_shell_in_it_works(
    devcontainer,
):
    result, calls = devcontainer("bash", terminal=True)

    assert result.returncode == 0
    (run,) = runs(calls)
    assert {"--interactive", "--tty"} <= set(run[: run.index(TAG)])


def test_from_a_script_the_container_is_given_no_terminal(devcontainer):
    result, calls = devcontainer("true", terminal=False)

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert "--tty" not in run
