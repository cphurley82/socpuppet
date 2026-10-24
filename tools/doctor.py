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
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.parse
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

REPOSITORY = Path(__file__).resolve().parents[1]
# The root of the files the pciem area looks at, /proc, /sys and /dev:
# this machine's, unless the tests give it another (--root).
ROOT = Path("/")

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
# For what comes with macOS itself.
MACOS_HAS_IT = Fix("nothing to install: macOS comes with it")


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


def python_org_package(version: str) -> str:
    """The package pkgutil knows python.org's CPython of a version by.

    It is named for the minor version, which every patch release of it
    installs over.
    """
    minor = ".".join(version.split(".")[:2])
    return f"org.python.Python.PythonFramework-{minor}"


def python_org_cpython() -> str | None:
    """What is wrong with python.org's CPython on a Mac, if anything.

    cibuildwheel builds a Mac's wheel with it, asks pkgutil whether it is
    there, and outside of CI will not install it, for it is a system-wide
    install that asks for a password. Other systems have no use for it.
    """
    if platform.system() != "Darwin" or not shutil.which("pkgutil"):
        return None
    version = (REPOSITORY / ".python-version").read_text().strip()
    packages = subprocess.run(
        ["pkgutil", "--pkgs"], stdout=subprocess.PIPE, text=True
    ).stdout.split()
    if python_org_package(version) in packages:
        return None
    return f"python.org's CPython {version} is not installed"


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
    """A script of the repository's, from its top, as a module.

    A script of tools/ imports its siblings (tools/needs.py) as a script
    run from there can, so the directory is put on the path first.
    """
    tools = str(REPOSITORY / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
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
PCIEM_GUEST = load("tools/pciem_guest.py")


def needs_of(part: str, host: str) -> tuple[Need, ...]:
    """What a part of the firmware's build needs of a machine of this kind.

    Its programs, or Docker where the machine builds it in the devcontainer's
    image, whose programs the machine has no use for.
    """
    if FIRMWARE_BUILD.builds_in_docker(part, host):
        return DOCKER
    return tuple(
        program(name, apt, Fix(brew, BREW))
        for name, apt, brew in FIRMWARE_BUILD.PROGRAMS[part]
    )


def firmware_needs(host: str) -> tuple[Need, ...]:
    """What the firmware's build needs of a machine of this kind.

    The tools to fetch and build its parts, or Docker where the machine
    builds every part in the devcontainer's image.
    """
    git = program("git", "git", XCODE)
    if all(
        FIRMWARE_BUILD.builds_in_docker(part, host)
        for part in FIRMWARE_BUILD.PARTS
    ):
        return (git, *DOCKER)
    return (
        git,
        program("curl", "curl", Fix("curl", BREW)),
        program("make", "build-essential", XCODE),
    )


def running_linux() -> str | None:
    """The running Linux kernel's release, or None if this is not Linux."""
    release = ROOT / "proc/sys/kernel/osrelease"
    return release.read_text().strip() if release.exists() else None


def not_linux(why: str) -> Callable[[], str | None]:
    """What is wrong with this machine, if it is not Linux.

    `why` is why it should be.
    """

    def problem() -> str | None:
        if running_linux() is not None:
            return None
        return f"this machine is not Linux, and {why}"

    return problem


def on_linux(problem: Callable[[], str | None]) -> Callable[[], str | None]:
    """A need of Linux's: `problem`, on Linux.

    On a machine that is not Linux it is no problem: that machine has one
    need of its own, which says so.
    """

    def linux_only() -> str | None:
        return None if running_linux() is None else problem()

    return linux_only


def old_kernel() -> str | None:
    """What is wrong with the running kernel for pciem, if anything."""
    release = running_linux() or ""
    version = re.match(r"(\d+)\.(\d+)", release)
    if version and (int(version[1]), int(version[2])) >= (6, 6):
        return None
    return f"the kernel is {release}, and pciem needs 6.6 or later"


def pciem_unloaded() -> str | None:
    """What is wrong with pciem's module, if anything."""
    if (ROOT / "sys/module/pciem").is_dir():
        return None
    return "pciem's module is not loaded"


def pciem_unwritable() -> str | None:
    """What is wrong with pciem's device, if anything.

    Without pciem's module there is no device, which is the module's need.
    """
    device = ROOT / "dev/pciem"
    if not device.exists() or os.access(device, os.W_OK):
        return None
    return f"{device} cannot be opened for writing"


def sudo_asks() -> str | None:
    """What is wrong with running the host's commands as root, if anything.

    🐧 A real host's tests format, mount and unmount the drive with this
    machine's own mkfs.ext4 and mount, which are root's, and let the
    driver go of it through /sys. Without sudo there is no asking, and
    sudo is a need of its own. `-k`, so that a password typed a moment ago
    does not pass for none.
    """
    if os.geteuid() == 0 or not shutil.which("sudo"):
        return None
    asked = subprocess.run(
        ["sudo", "-n", "-k", "true"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return None if asked.returncode == 0 else "sudo asks for a password"


# What a real host needs of this machine, in two parts: what opening
# /dev/pciem takes, which a test of what pciem refuses needs and no more
# (tests/python/pciem_area.py), and then what running the host's commands
# as root takes. The fixes are Linux's, since only on Linux is any of it a
# problem, but the first: a machine that is not Linux is told so on
# whatever it runs (and in the tests, a Linux pointed at a machine of
# their own with no /proc).
NOT_HERE = Fix("nothing here: a real host is a Linux machine's")
PCIEM_DEVICE = (
    Need(
        "Linux",
        not_linux("pciem is Linux's"),
        {"Linux": NOT_HERE, "Darwin": NOT_HERE},
    ),
    Need(
        "kernel 6.6",
        on_linux(old_kernel),
        {"Linux": Fix("upgrade to a kernel of 6.6 or later")},
    ),
    Need(
        "pciem.ko",
        on_linux(pciem_unloaded),
        {
            "Linux": Fix(
                "build it with uv run tools/build_pciem.py, then set memory "
                "aside and load it as docs/setup.md says"
            )
        },
    ),
    Need(
        "/dev/pciem",
        on_linux(pciem_unwritable),
        {
            "Linux": Fix(
                "give it to your user with a udev rule, as docs/setup.md says"
            )
        },
    ),
)
PCIEM = (
    *PCIEM_DEVICE,
    Need("sudo", on_linux(installed("sudo")), {"Linux": Fix("sudo", APT)}),
    Need(
        "sudo without a password",
        on_linux(sudo_asks),
        {
            "Linux": Fix(
                "run the tests as root, or let sudo run commands as root "
                "without a password, as docs/setup.md says"
            )
        },
    ),
)


def kernel_unreadable() -> str | None:
    """What is wrong with QEMU's booting the running kernel, if anything."""
    kernel = ROOT / "boot" / f"vmlinuz-{running_linux()}"
    if os.access(kernel, os.R_OK):
        return None
    return f"{kernel} cannot be read"


def kvm_unwritable() -> str | None:
    """What is wrong with QEMU's running the guest on KVM, if anything."""
    device = ROOT / "dev/kvm"
    if os.access(device, os.W_OK):
        return None
    return f"{device} cannot be opened for writing"


def no_headers() -> str | None:
    """What is wrong with building a module for the running kernel."""
    release = running_linux() or ""
    if (ROOT / "lib/modules" / release / "build/Makefile").exists():
        return None
    return f"there are no headers for the kernel, {release}"


# What tools/pciem_guest.py needs of this machine, to boot its kernel with
# pciem in a guest: what CI's runner, which cannot load pciem itself, runs
# a real host's tests in. And the kernel's headers, which the guest has no
# use for, but tools/build_pciem.py builds pciem's module for it with.
GUEST = (
    Need(
        "Linux",
        not_linux("the guest is its own kernel's"),
        {"Linux": NOT_HERE, "Darwin": NOT_HERE},
    ),
    *(
        Need(name, on_linux(installed(name)), {"Linux": Fix(apt, APT)})
        for name, apt in PCIEM_GUEST.PROGRAMS
    ),
    Need(
        "the running kernel",
        on_linux(kernel_unreadable),
        {
            "Linux": Fix(
                "let QEMU read it: sudo chmod a+r /boot/vmlinuz-$(uname -r)"
            )
        },
    ),
    Need(
        "/dev/kvm",
        on_linux(kvm_unwritable),
        {
            "Linux": Fix(
                "QEMU runs the guest on KVM: give it to your user until the "
                "next boot with sudo setfacl -m u:$USER:rw /dev/kvm"
            )
        },
    ),
    Need(
        "the kernel's headers",
        on_linux(no_headers),
        {"Linux": Fix("linux-headers-$(uname -r)", APT)},
    ),
)


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
        firmware_needs(FIRMWARE_BUILD.sdk_host()),
    ),
    Area(
        "edk2",
        "EDK2's build",
        needs_of("edk2", FIRMWARE_BUILD.sdk_host()),
    ),
    Area(
        "linux",
        "the Linux kernel's build",
        needs_of("linux", FIRMWARE_BUILD.sdk_host()),
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
    Area(
        "wheel",
        "the wheel's build",
        (
            Need(
                "python.org's CPython",
                python_org_cpython,
                {
                    "Linux": Fix("nothing: a container builds it"),
                    "Darwin": Fix(
                        "install the .pkg of the Python in .python-version "
                        "from https://www.python.org/downloads/macos/ "
                        "(it asks for your password)"
                    ),
                },
            ),
        ),
        optional=True,
    ),
    # The wheels of Linux are built in a container, and the devcontainer's
    # image is tested in one.
    Area("docker", "Docker", DOCKER, optional=True),
    # 🐧 This machine's own Linux as the host of the puppet's SSD, which few
    # need, and only a Linux machine can be.
    Area("pciem", "pciem, for a real host", PCIEM, optional=True),
    # Where pciem cannot be loaded, as on CI's runners, the same tests run
    # in a guest of the machine's own, which few need.
    Area("guest", "a QEMU guest, for a real host on CI", GUEST, optional=True),
    # 🐧 libslirp plugs the puppet's network card into this machine's
    # network (socpuppet.slirp), and ssh and scp reach Linux over it.
    # Without them Linux boots with its card unplugged.
    Area(
        "cable",
        "a cable to this machine's network, and ssh to Linux",
        (
            library("slirp", "libslirp-dev", "libslirp"),
            program("ssh", "openssh-client", MACOS_HAS_IT),
            program("scp", "openssh-client", MACOS_HAS_IT),
        ),
        optional=True,
    ),
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
    global ROOT
    ROOT = args.root
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
    # For the tests: the root of a machine of their own making.
    parser.add_argument(
        "--root", type=Path, default=ROOT, help=argparse.SUPPRESS
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
