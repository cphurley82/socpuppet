#!/usr/bin/env python3
"""Check this machine for what socpuppet's development needs.

Usage:
  uv run python tools/doctor.py              every area
  uv run python tools/doctor.py qbox docker  the areas named

Each area is something a part of the work needs: socpuppet's build, the
firmware's, QBox's packages, the network or Docker. An area that is missing
something says what, and the command that installs it here. docs/setup.md
says why each is needed.
"""

import argparse
import concurrent.futures
import importlib.util
import json
import platform
import shutil
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPOSITORY = Path(__file__).resolve().parents[1]

# How a package is installed on Ubuntu and on a Mac.
APT = "sudo apt-get install -y"
BREW = "brew install"


@dataclass(frozen=True)
class Fix:
    """What to do about a need that is missing.

    A package, which goes on one command with the others of its installer,
    or something to do, said as it is.
    """

    what: str
    installer: str | None = None


# Apple's command line tools, which have the compiler, git and make.
XCODE = Fix("xcode-select --install")


@dataclass(frozen=True)
class Need:
    """One thing an area needs, and what to do when it is missing."""

    name: str
    # What is wrong, or None if nothing is.
    problem: Callable[[], str | None]
    # What to do about it, by platform.system()'s name.
    fix: Mapping[str, Fix]


@dataclass(frozen=True)
class Area:
    """Something a part of the work needs: what it is called, and its needs."""

    name: str
    title: str
    needs: tuple[Need, ...] = ()
    # Whether the work goes on without it: what needs it is left out.
    optional: bool = False


def installed(name: str) -> Callable[[], str | None]:
    """What is wrong with a program's being on the path, if anything."""

    def problem() -> str | None:
        return None if shutil.which(name) else f"{name} is not installed"

    return problem


def program(name: str, apt: str, mac: Fix) -> Need:
    """A program found on the path: its Ubuntu package and a Mac's fix."""
    return Need(name, installed(name), {"Linux": Fix(apt, APT), "Darwin": mac})


def library(name: str, apt: str, brew: str) -> Need:
    """A library pkg-config finds: its Ubuntu package and Homebrew formula.

    Without pkg-config there is no asking, and pkg-config is a need of its
    own.
    """

    def problem() -> str | None:
        if not shutil.which("pkg-config"):
            return None
        found = subprocess.run(["pkg-config", "--exists", name]).returncode == 0
        return None if found else f"pkg-config cannot find {name}"

    return Need(
        name, problem, {"Linux": Fix(apt, APT), "Darwin": Fix(brew, BREW)}
    )


def site(url: str) -> Need:
    """A site the work fetches from, which curl, as the work does, reaches.

    Any answer at all is reaching it.
    """
    host = urllib.parse.urlsplit(url).hostname or url

    def problem() -> str | None:
        if not shutil.which("curl"):
            return f"curl is not installed, to try {host} with"
        tried = subprocess.run(
            ["curl", "-sS", "--head", "--max-time", "10", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        if tried.returncode == 0:
            return None
        return f"{host} cannot be reached: {tried.stderr.strip()}"

    fix = Fix("check the connection, and HTTPS_PROXY if there is a proxy")
    return Need(host, problem, {"Linux": fix, "Darwin": fix})


def docker_answers() -> str | None:
    """What is wrong with Docker's daemon, if Docker is installed."""
    if not shutil.which("docker"):
        return None
    info = subprocess.run(
        ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if info.returncode == 0:
        return None
    return (
        "`docker info` fails: is the daemon running, and are you in the "
        "docker group?"
    )


DOCKER = (
    Need(
        "docker",
        installed("docker"),
        {
            "Linux": Fix(
                "install Docker Engine: https://docs.docker.com/engine/install/"
            ),
            "Darwin": Fix(
                "install Docker Desktop: "
                "https://www.docker.com/products/docker-desktop/"
            ),
        },
    ),
    Need(
        "docker info",
        docker_answers,
        {
            "Linux": Fix(
                "start Docker, or join its group and log in again: "
                "sudo usermod -aG docker $USER"
            ),
            "Darwin": Fix("start Docker Desktop"),
        },
    ),
)


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


# The scripts whose lists of what they need are the ones checked here.
BUILD_QBOX = load("tools/build_qbox.py")
FIRMWARE_BUILD = load("firmware/build.py")

AREAS = (
    Area(
        "build",
        "socpuppet's build",
        (
            program("git", "git", XCODE),
            program("c++", "build-essential", XCODE),
            # The tests that check a devicetree skip without it.
            program("dtc", "device-tree-compiler", Fix("dtc", BREW)),
        ),
    ),
    Area(
        "firmware",
        "the firmware's build",
        (
            program("git", "git", XCODE),
            program("curl", "curl", Fix("curl", BREW)),
            program("make", "build-essential", XCODE),
        ),
    ),
    Area(
        "edk2",
        "EDK2's build",
        tuple(
            program(name, apt, Fix(brew, BREW))
            for name, apt, brew in FIRMWARE_BUILD.PROGRAMS["edk2"]
        ),
    ),
    Area(
        "linux",
        "the Linux kernel's build",
        tuple(
            program(name, apt, Fix(brew, BREW))
            for name, apt, brew in FIRMWARE_BUILD.PROGRAMS["linux"]
        ),
    ),
    Area(
        "qbox",
        "QBox's packages",
        (
            *(
                program(name, apt, Fix(brew, BREW))
                for name, apt, brew in BUILD_QBOX.PROGRAMS
            ),
            *(library(*each) for each in BUILD_QBOX.LIBRARIES),
        ),
        # QBox's CPU is a second hart, which few need.
        optional=True,
    ),
    Area(
        "network",
        "the network",
        # Python's packages, and QBox's configure, which fetches CPM.cmake
        # from GitHub every time.
        (site("https://pypi.org"), site("https://github.com")),
    ),
    # The wheels of Linux are built in a container, and the devcontainer's
    # image is tested in one.
    Area("docker", "Docker", DOCKER, optional=True),
)


@dataclass(frozen=True)
class Report:
    """How an area is: what is wrong with it, and what to do about it."""

    area: Area
    problems: list[str]
    fix: list[str]

    def as_json(self) -> dict[str, object]:
        """It, for a program to read."""
        return {
            "name": self.area.name,
            "title": self.area.title,
            "optional": self.area.optional,
            "problems": self.problems,
            "fix": self.fix,
        }

    def show(self) -> str:
        """What a person reads of it: a mark, the problems, then the fix."""
        if not self.problems:
            return f"✅ {self.area.title}"
        mark = "⚠️" if self.area.optional else "❌"
        lines = [f"{mark} {self.area.title}: {'; '.join(self.problems)}"]
        lines += [f"     {fix}" for fix in self.fix]
        return "\n".join(lines)


def main() -> int:
    """Check each area asked for, and say how it is. Returns the exit status.

    An area that is not optional and has a problem fails the check.
    """
    args = parse(sys.argv[1:])
    areas = [
        area for area in AREAS if not args.areas or area.name in args.areas
    ]
    reports = examine(areas)
    if args.json:
        print(json.dumps({"areas": [each.as_json() for each in reports]}))
    else:
        for report in reports:
            print(report.show())
    failed = any(each.problems and not each.area.optional for each in reports)
    return 1 if failed else 0


def parse(arguments: list[str]) -> argparse.Namespace:
    """What was asked."""
    parser = argparse.ArgumentParser(
        prog="tools/doctor.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "areas",
        nargs="*",
        choices=[area.name for area in AREAS],
        metavar="area",
        help="check only these (default: every one): %(choices)s",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="say it as JSON, for a program to read",
    )
    return parser.parse_args(arguments)


def examine(areas: list[Area]) -> list[Report]:
    """How each area is, in the order given.

    The needs are looked at side by side, since some wait on a program, and
    a site that does not answer waits for seconds.
    """
    system = platform.system()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        looked = [
            [(need, pool.submit(need.problem)) for need in area.needs]
            for area in areas
        ]
        reports = []
        for area, needs in zip(areas, looked, strict=True):
            wrong = [
                (need, problem)
                for need, future in needs
                if (problem := future.result())
            ]
            reports.append(
                Report(
                    area,
                    [problem for _, problem in wrong],
                    installs(need.fix[system] for need, _ in wrong),
                )
            )
        return reports


def installs(fixes: Iterable[Fix]) -> list[str]:
    """What to do, with the packages of each installer on one command."""
    packages: dict[str | None, list[str]] = {}
    advice: list[str] = []
    for fix in fixes:
        said = (
            packages.setdefault(fix.installer, []) if fix.installer else advice
        )
        if fix.what not in said:
            said.append(fix.what)
    return [
        *(
            " ".join([installer, *names])
            for installer, names in packages.items()
        ),
        *advice,
    ]


if __name__ == "__main__":
    sys.exit(main())
