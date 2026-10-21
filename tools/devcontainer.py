#!/usr/bin/env python3
"""Run a command in the devcontainer's image, with the repository at /workspace.

Usage:
  tools/devcontainer.py uv run cmake --preset qbox
  tools/devcontainer.py bash

The image is Linux with GCC, which is what CI builds in. It is built the
first time, and again whenever .devcontainer/Dockerfile changes.
"""

import hashlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType

REPOSITORY = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY / ".devcontainer" / "Dockerfile"
#: Where the repository is in the container.
WORKSPACE = PurePosixPath("/workspace")
#: Where the container has twister's own folder (firmware/twister.py).
TWISTER_HOME = PurePosixPath("/twister")

# uv's venv, its cache and its Pythons, which are kept in build/ so that
# they outlive the container. firmware/twister.py runs in the same image
# with the same venv and Python.
UV = {
    "UV_PROJECT_ENVIRONMENT": f"{WORKSPACE}/build/linux-venv",
    "UV_PYTHON_INSTALL_DIR": f"{WORKSPACE}/build/linux-python",
    "UV_CACHE_DIR": f"{WORKSPACE}/build/linux-uv-cache",
}


def main() -> int:
    """Run the command given, in the image. Returns 1 or 2 if it cannot."""
    command = sys.argv[1:]
    if not command:
        print(
            "usage: tools/devcontainer.py COMMAND [ARGUMENT...]",
            file=sys.stderr,
        )
        return 2
    if not shutil.which("docker"):
        print(
            "tools/devcontainer.py runs its command in the devcontainer's "
            "image, and found no Docker to do that with.\n"
            "Install Docker Desktop, start it, and run this again.",
            file=sys.stderr,
        )
        return 1
    built = image()
    if not built:
        return 1
    apart = kept_apart()
    make_room(apart)
    # Docker takes this process's place, so that the terminal, and Ctrl-C,
    # are the command's.
    os.execvp(
        "docker",
        [
            *("docker", "run", "--rm"),
            *(
                "--volume",
                f"{REPOSITORY}:{WORKSPACE}",
                "--workdir",
                str(WORKSPACE),
            ),
            *docker_options(apart),
            built,
            *command,
        ],
    )


def image() -> str | None:
    """The image, built from the Dockerfile if it is not there yet.

    It is named after the Dockerfile's contents, so a change to the
    Dockerfile builds it again. It is socpuppet-dev too, the name that
    stands for whichever was built last. None if it could not be built,
    which docker has said why.
    """
    digest = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()
    name = f"socpuppet-dev:{digest[:12]}"
    there = subprocess.run(
        ["docker", "image", "inspect", name], capture_output=True
    )
    if there.returncode != 0:
        built = subprocess.run(
            [
                *("docker", "build", "--tag", name, "--tag", "socpuppet-dev"),
                *("--file", str(DOCKERFILE), str(DOCKERFILE.parent)),
            ]
        )
        if built.returncode != 0:
            print(
                "The devcontainer's image did not build: Docker says why "
                "above. Is Docker running, and does .devcontainer/Dockerfile "
                "build?",
                file=sys.stderr,
            )
            return None
    return name


def docker_options(apart: dict[str, PurePosixPath]) -> list[str]:
    """What `docker run` is told, beyond the repository and the command.

    `apart` is what the container keeps apart from the host, as
    `kept_apart()` has it.
    """
    options = [f"{name}={value}" for name, value in UV.items()]
    # socpuppet's own variables, such as SOCPUPPET_REQUIRE_FIRMWARE and
    # SOCPUPPET_CPU, go in with the command. A path in one is read in the
    # container, where the repository is /workspace: a relative one still
    # works.
    options += [
        f"{name}={value}"
        for name, value in os.environ.items()
        if name.startswith("SOCPUPPET_")
    ]
    options = [word for each in options for word in ("--env", each)]
    if platform.system() != "Darwin":
        # The repository's mount keeps the container's user, so on Linux
        # the command runs as the caller's, to leave nothing in build/ that
        # only root can remove. Docker Desktop on a Mac maps the user by
        # itself.
        options += ["--user", f"{os.getuid()}:{os.getgid()}"]
    for name, there in apart.items():
        options += ["--volume", f"{apart_from_the_host(name)}:{there}"]
    # From a terminal, the command has one, so that a shell in the
    # container works.
    if sys.stdin.isatty() and sys.stdout.isatty():
        options += ["--interactive", "--tty"]
    return options


def kept_apart() -> dict[str, PurePosixPath]:
    """What the container keeps apart from the host's own, by name.

    Each is where the container has it. 🎓 The container is a Linux
    machine of its own, with its own compiler and the repository at
    /workspace, so what it builds for itself is not the host's, though
    the host is Linux too. uv's venv, cache and Pythons, and the linux
    preset's tree, build/linux, are the container's alone already, and
    nothing of the host's is where they are.
    """
    return {
        # QBox, and socpuppet's tree built with it, where
        # tools/build_qbox.py and the qbox preset put them.
        "qbox": WORKSPACE / "build" / "qbox",
        "qbox-dev": WORKSPACE / "build" / "qbox-dev",
        # Linux's own firmware tools, its SDK, LLVM and venv and the
        # kernel's and EDK2's trees, where firmware/build.py keeps a
        # machine's.
        "firmware-linux": WORKSPACE
        / "build"
        / "firmware"
        / containers_machine(),
        # Twister's Zephyr and builds, which firmware/twister.py uses when
        # it runs in the container, as on an Intel Mac.
        "twister": TWISTER_HOME,
    }


def apart_from_the_host(name: str) -> str:
    """What is mounted to keep `name` apart from the host's own.

    It is named for the image's Ubuntu, so an image of a new Ubuntu starts
    afresh. On a Mac it is a Docker volume, socpuppet-<name>-<the image's
    Ubuntu>, such as socpuppet-qbox-ubuntu-26.04: Docker Desktop reads
    the Mac's files through file sharing, which a compiler finds ten times
    slower than a volume (docs/twister-spike.md), and a Mac's file system
    takes two of the kernel's names that differ only in their case for one.
    `docker volume rm` throws an old Ubuntu's away. On Linux it is a folder of
    build/container/<the image's Ubuntu>, which the container writes as the
    caller, and `rm -rf` throws an old Ubuntu's away.
    """
    if platform.system() == "Darwin":
        return f"socpuppet-{name}-{ubuntu()}"
    return str(REPOSITORY / "build" / "container" / ubuntu() / name)


def ubuntu() -> str:
    """The Ubuntu the image builds on, as ubuntu-26.04, from its FROM line.

    🎓 What the container builds for itself was built by that Ubuntu's
    compiler against its libraries, and another Ubuntu's compiler should
    not build on top of it.
    """
    words = next(
        words
        for words in map(str.split, DOCKERFILE.read_text().splitlines())
        if words and words[0].upper() == "FROM"
    )
    image = next(word for word in words[1:] if not word.startswith("--"))
    return image.replace(":", "-")


def make_room(apart: dict[str, PurePosixPath]) -> None:
    """On Linux, make each folder kept `apart`, as the caller's.

    And where it is mounted, if that is in the repository. 💡 Docker makes
    a folder it is to mount that is not there, and makes it root's.
    """
    if platform.system() == "Darwin":
        return
    for name, there in apart.items():
        Path(apart_from_the_host(name)).mkdir(parents=True, exist_ok=True)
        if there.is_relative_to(WORKSPACE):
            point = REPOSITORY / there.relative_to(WORKSPACE)
            point.mkdir(parents=True, exist_ok=True)


def containers_machine() -> str:
    """The SDK's name for the container's machine: Linux, on this processor.

    firmware/build.py names a machine's directory so (its sdk_host()).
    """
    _, _, processor = load("firmware/build.py").sdk_host().partition("-")
    return f"linux-{processor}"


def load(path: str) -> ModuleType:
    """A script of the repository's, from its top, as a module."""
    spec = importlib.util.spec_from_file_location(
        Path(path).stem, REPOSITORY / path
    )
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    sys.exit(main())
