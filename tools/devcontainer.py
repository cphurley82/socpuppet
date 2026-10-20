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
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
DOCKERFILE = REPOSITORY / ".devcontainer" / "Dockerfile"

# uv's venv, its cache and its Pythons, which are kept in build/ so that
# they outlive the container. firmware/twister.py runs in the same image
# with the same venv and Python.
UV = {
    "UV_PROJECT_ENVIRONMENT": "/workspace/build/linux-venv",
    "UV_PYTHON_INSTALL_DIR": "/workspace/build/linux-python",
    "UV_CACHE_DIR": "/workspace/build/linux-uv-cache",
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
    # Docker takes this process's place, so that the terminal, and Ctrl-C,
    # are the command's.
    os.execvp(
        "docker",
        [
            *("docker", "run", "--rm"),
            *(
                "--volume",
                f"{REPOSITORY}:/workspace",
                "--workdir",
                "/workspace",
            ),
            *docker_options(),
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


def docker_options() -> list[str]:
    """What `docker run` is told, beyond the repository and the command."""
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
    if platform.system() == "Linux":
        # The repository's mount keeps the container's user, so the
        # command runs as the caller's, to leave nothing in build/ that
        # only root can remove.
        options += ["--user", f"{os.getuid()}:{os.getgid()}"]
    elif platform.system() == "Darwin":
        # Docker Desktop on a Mac maps the user by itself, and reads the
        # repository through file sharing, which a compiler finds ten
        # times slower than a Docker volume (docs/twister-spike.md). So
        # QBox's tree and socpuppet's tree built with it are volumes, at
        # the places in build/ that tools/build_qbox.py and the qbox preset
        # use, in front of whatever the Mac has there, a native build
        # included. `docker volume rm socpuppet-qbox socpuppet-qbox-dev`
        # throws them away.
        options += [
            *("--volume", "socpuppet-qbox:/workspace/build/qbox"),
            *("--volume", "socpuppet-qbox-dev:/workspace/build/qbox-dev"),
            # And twister's Zephyr and builds, for the same reason
            # (firmware/twister.py).
            *("--volume", "socpuppet-twister:/twister"),
            # And Linux's own firmware tools, its SDK, LLVM and venv and
            # the kernel's tree, where firmware/build.py keeps a machine's,
            # beside the Mac's own: a Mac's file system also takes two of
            # the kernel's names that differ only in their case for one.
            *(
                "--volume",
                "socpuppet-firmware-linux:/workspace/build/firmware/"
                f"{containers_machine()}",
            ),
        ]
    # From a terminal, the command has one, so that a shell in the
    # container works.
    if sys.stdin.isatty() and sys.stdout.isatty():
        options += ["--interactive", "--tty"]
    return options


def containers_machine() -> str:
    """The SDK's name for the container's machine: Linux, on this processor.

    firmware/build.py names a machine's directory so (its sdk_host()).
    """
    build = REPOSITORY / "firmware" / "build.py"
    spec = importlib.util.spec_from_file_location("build", build)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, _, processor = module.sdk_host().partition("-")
    return f"linux-{processor}"


if __name__ == "__main__":
    sys.exit(main())
