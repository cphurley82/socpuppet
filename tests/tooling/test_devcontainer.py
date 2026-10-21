"""tools/devcontainer.py, which runs a command in the devcontainer's image.

The script is run for real, with a stand-in for docker on its path that
writes each command it was given to a log and knows only the images the
test says exist, so the tests can say what the script asked Docker for
without Docker.
"""

import hashlib
import importlib.util
import json
import os
import platform
import pty
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

from conftest import AS_ON

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / ".devcontainer" / "Dockerfile"
#: What the script reads of its repository, which each test copies into a
#: throwaway one, so that what the script makes there is the test's.
READS = (
    "tools/devcontainer.py",
    ".devcontainer/Dockerfile",
    "firmware/build.py",
    "firmware/twister.py",
)
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

# Where the container has twister's own folder, as the script names it for
# firmware/twister.py.
_spec = importlib.util.spec_from_file_location(
    "devcontainer", REPO / "tools" / "devcontainer.py"
)
_script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_script)
TWISTER_HOME = str(_script.TWISTER_HOME)

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
    root = tmp_path / "repo"
    for path in READS:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / path, root / path)

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
        as_on=None,
    ):
        """Run it; with `terminal`, its input and output are a terminal.

        `as_on` is (platform.system(), platform.machine()) to run it as.
        """
        log.unlink(missing_ok=True)
        if docker:
            install("docker", DOCKER)
            path = f"{bin_directory}{os.pathsep}{os.defpath}"
        else:
            # Only the stand-ins, since a Linux machine may have Docker in
            # /usr/bin.
            path = str(bin_directory)
        ours, theirs = pty.openpty() if terminal else (None, None)
        on = ("-c", AS_ON, *as_on) if as_on else ()
        result = subprocess.run(
            [
                sys.executable,
                *on,
                str(root / "tools" / "devcontainer.py"),
                *args,
            ],
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

    run.root = root
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
    assert f"{devcontainer.root}:/workspace" in values(run, "--volume")
    assert values(run, "--workdir") == ["/workspace"]
    assert run[-len(command) - 1 :] == [TAG, *command]


def test_an_image_is_built_from_the_dockerfile_when_none_has_its_hash_and_is_also_named_socpuppet_dev(
    devcontainer,
):
    result, calls = devcontainer("true", images=())

    assert result.returncode == 0, result.stdout
    (build,) = [call[1:] for call in calls if call[0] == "build"]
    assert set(values(build, "--tag")) == {TAG, "socpuppet-dev"}
    dockerfile = devcontainer.root / ".devcontainer" / "Dockerfile"
    assert values(build, "--file") == [str(dockerfile)]
    assert build[-1] == str(dockerfile.parent)
    assert position(calls, "build") < position(calls, "run")


def test_an_image_already_built_from_this_dockerfile_is_not_built_again(
    devcontainer,
):
    result, calls = devcontainer("true", images=(TAG,))

    assert result.returncode == 0, result.stdout
    assert not [call for call in calls if call[0] == "build"]


@pytest.mark.parametrize(
    ("processor", "linux"),
    [("arm64", "linux-aarch64"), ("x86_64", "linux-x86_64")],
)
def test_on_a_mac_linuxs_firmware_tools_are_a_docker_volume_named_for_the_images_ubuntu_in_build_firmware_linux_and_the_processor(
    devcontainer, processor, linux
):
    # 🎓 firmware/build.py keeps a machine's tools in build/firmware/<the
    # SDK's name for the machine>, and the container's Linux is the Mac's
    # kind of processor.
    from_ubuntu(devcontainer.root, "28.04")

    result, calls = devcontainer("true", as_on=("Darwin", processor))

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    assert (
        "socpuppet-firmware-linux-ubuntu-28.04:"
        f"/workspace/build/firmware/{linux}" in values(run, "--volume")
    )


#: What the container builds for itself, on an Intel machine: the name it
#: is kept under, and where the container has it.
KEPT_APART = {
    "qbox": QBOX,
    "qbox-dev": QBOX_DEV,
    "firmware-linux": "/workspace/build/firmware/linux-x86_64",
    "twister": TWISTER_HOME,
}


def test_on_a_mac_what_the_container_builds_for_itself_is_a_docker_volume_named_for_the_images_ubuntu(
    devcontainer,
):
    from_ubuntu(devcontainer.root, "28.04")

    result, calls = devcontainer("true", as_on=("Darwin", "x86_64"))

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    volumes = values(run, "--volume")
    for folder, there in KEPT_APART.items():
        assert f"socpuppet-{folder}-ubuntu-28.04:{there}" in volumes


def test_on_linux_what_the_container_builds_for_itself_is_kept_in_a_folder_of_build_container_named_for_the_images_ubuntu(
    devcontainer,
):
    # 🎓 The container is a Linux machine of its own, with its own compiler
    # and the repository at /workspace: what it builds for itself is not
    # the host's, though the host is Linux too. Nor is what GCC 13 built
    # against Ubuntu 24.04's libraries a tree for GCC 15 on 26.04.
    from_ubuntu(devcontainer.root, "28.04")

    result, calls = devcontainer("true", as_on=("Linux", "x86_64"))

    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    volumes = values(run, "--volume")
    kept = devcontainer.root / "build" / "container" / "ubuntu-28.04"
    for folder, there in KEPT_APART.items():
        assert f"{kept / folder}:{there}" in volumes


def test_on_linux_a_missing_folder_kept_apart_is_made_as_the_callers_before_docker_runs(
    devcontainer,
):
    # 💡 Docker makes a folder it is to mount that is not there, and makes
    # it root's.
    from_ubuntu(devcontainer.root, "28.04")
    made = [
        each
        for folder, there in KEPT_APART.items()
        for each in made_for(devcontainer.root, "ubuntu-28.04", folder, there)
    ]
    assert not any(each.exists() for each in made)

    result, _ = devcontainer("true", as_on=("Linux", "x86_64"))

    assert result.returncode == 0, result.stdout
    for each in made:
        assert each.is_dir(), each
        assert each.stat().st_uid == os.getuid(), each


def from_ubuntu(root, version):
    """Make the repository's Dockerfile build from Ubuntu `version`."""
    dockerfile = root / ".devcontainer" / "Dockerfile"
    text, replaced = re.subn(
        r"^FROM ubuntu:\S+",
        f"FROM ubuntu:{version}",
        dockerfile.read_text(),
        flags=re.MULTILINE,
    )
    assert replaced == 1, "the Dockerfile has no single FROM ubuntu: line"
    dockerfile.write_text(text)


def made_for(root, ubuntu, folder, there):
    """The folder of build/container/<ubuntu> that is mounted at `there`,
    and the mount point too when it is in the repository."""
    made = [root / "build" / "container" / ubuntu / folder]
    if there.startswith("/workspace/"):
        made.append(root / Path(there).relative_to("/workspace"))
    return made


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


def test_vs_codes_devcontainer_has_the_repository_at_workspace_as_the_script():
    vs_code = jsonc(REPO / ".devcontainer" / "devcontainer.json")

    assert fields(vs_code["workspaceMount"])["target"] == "/workspace"
    assert vs_code["workspaceFolder"] == "/workspace"


@pytest.mark.parametrize("processor", ["arm64", "x86_64"])
def test_vs_codes_devcontainer_mounts_each_volume_the_script_mounts_on_a_mac_of_either_processor(
    devcontainer, processor
):
    # 🎓 VS Code reads .devcontainer/devcontainer.json and not the script,
    # and a JSON file cannot ask which processor it is on: the container's
    # firmware folder is mounted for both. Twister's own folder is only for
    # firmware/twister.py run through the script, which says to use it.
    result, calls = devcontainer("true", as_on=("Darwin", processor))
    assert result.returncode == 0, result.stdout
    (run,) = runs(calls)
    vs_code = jsonc(REPO / ".devcontainer" / "devcontainer.json")

    mounts = [fields(each) for each in vs_code["mounts"]]
    for volume in values(run, "--volume"):
        source, target = volume.split(":")
        if source != str(devcontainer.root) and target != TWISTER_HOME:
            assert any(
                mount["source"] == source
                and mount["target"] == target
                and mount["type"] == "volume"
                for mount in mounts
            )


def test_vs_codes_devcontainer_makes_each_mount_point_in_the_repository_first(
    tmp_path,
):
    # 💡 Docker makes a folder it is to mount that is not there, and on
    # Linux makes it root's. VS Code runs initializeCommand on the host,
    # as the caller, in the repository, before it makes the container.
    vs_code = jsonc(REPO / ".devcontainer" / "devcontainer.json")

    subprocess.run(
        vs_code["initializeCommand"], shell=True, cwd=tmp_path, check=True
    )

    for mount in vs_code["mounts"]:
        target = PurePosixPath(fields(mount)["target"])
        if target.is_relative_to("/workspace"):
            assert (tmp_path / target.relative_to("/workspace")).is_dir()


def jsonc(path):
    """A JSON file that may have // comments on lines of their own."""
    lines = path.read_text().splitlines()
    return json.loads(
        "\n".join(line for line in lines if not line.strip().startswith("//"))
    )


def fields(mount):
    """A mount's `key=value,...` string as a dict."""
    return dict(field.split("=", 1) for field in mount.split(","))
