#!/usr/bin/env python3
"""Run twister, Zephyr's test runner, on socpuppet's boards.

Usage:
  uv run firmware/twister.py --suites                     every suite in
                                                          firmware/twister-suites.txt,
                                                          on every board
  uv run firmware/twister.py --suites -p socpuppet_host   the same, on one board
  uv run firmware/twister.py -p socpuppet_ssd -T tests/kernel/sleep -v
                                                          one suite, by hand

Twister builds Zephyr's own test suites, and ours, for a board, runs each
on socpuppet as the board's emulator, and judges it by what the board's
console prints. Everything after --suites goes to twister. A -T that is
relative is a directory of Zephyr's tree, unless it is firmware or python,
or under one of them: those are this repository's. The verdicts and the
logs are left in build/twister/out, in a directory for each run of
twister: twister.json, twister.xml for a CI's test report, twister.log,
and each scenario's build.log, its handler.log, which is its console, and
its handler_stderr.log, where `socpuppet run` says how a run ended.

It wants what `uv run firmware/build.py rom zephyr-tree` leaves in
build/firmware (the SDK, Zephyr, a venv, the boot ROMs) and a socpuppet
built for this machine, which `cmake --build --preset dev` leaves
importable from python/.

On an Intel Mac it runs itself in the devcontainer's image, as
firmware/build.py does, since the Zephyr SDK has no toolchain for one.
There it builds a socpuppet for Linux in build/linux first, and keeps
Zephyr, the SDK, a venv and twister's build directories on a Docker volume,
socpuppet-twister: a compiler that reads its headers through Docker's file
sharing takes ten times as long (docs/twister-spike.md has the figures).
They are copied to the volume the first time and when their versions
change, and `docker volume rm socpuppet-twister` throws the copy away.
"""

import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

REPOSITORY = Path(__file__).resolve().parents[1]
FIRMWARE = REPOSITORY / "build" / "firmware"
OUT = REPOSITORY / "build" / "twister" / "out"
REQUIREMENTS = REPOSITORY / "firmware" / "twister-requirements.txt"

# Every board, unless the command names some.
BOARDS = ("socpuppet_host", "socpuppet_ssd", "socpuppet_iomgr")

# What twister imports beyond what a build needs, by the names of the
# modules: firmware/twister-requirements.txt has them by their packages'.
TWISTER_IMPORTS = (
    "import psutil, tabulate, natsort, anytree, junitparser, colorama, ply,"
    " serial, pytest, packaging, dotenv"
)


def load(path: Path) -> ModuleType:
    """One of the repository's scripts, as a module."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Failed(Exception):
    """What stops twister from running, and what to do about it."""


def main() -> int:
    """Run twister as asked. Returns its exit status."""
    arguments = sys.argv[1:]
    if (platform.system(), platform.machine()) == ("Darwin", "x86_64"):
        return in_docker(arguments)
    try:
        return Twister().go(arguments)
    except Failed as failure:
        print(failure, file=sys.stderr)
        return 1


def in_docker(arguments: list[str]) -> int:
    """Run the same command in the devcontainer's image, on the volume.

    tools/devcontainer.py mounts the volume, socpuppet-twister, at /twister
    on a Mac, and passes socpuppet's variables in: these two say to use it,
    and to build a socpuppet for Linux first.
    """
    return subprocess.run(
        [
            str(REPOSITORY / "tools" / "devcontainer.py"),
            *("python3", "firmware/twister.py", *arguments),
        ],
        env={
            **os.environ,
            "SOCPUPPET_TWISTER_HOME": "/twister",
            "SOCPUPPET_TWISTER_BUILD": "1",
        },
    ).returncode


class Twister:
    """Where twister, Zephyr and the SDK are, and how to run twister."""

    def __init__(self) -> None:
        versions = tomllib.loads(
            (REPOSITORY / "firmware" / "versions.toml").read_text()
        )
        self.sdk_name = f"zephyr-sdk-{versions['sdk']['version']}"
        # The Python that socpuppet was built for, which runs it.
        self.project_venv = Path(
            os.environ.get("UV_PROJECT_ENVIRONMENT", REPOSITORY / ".venv")
        )
        # In the container, Zephyr, the SDK, the venv and twister's build
        # directories are on the volume, and its verdicts come back.
        self.home = os.environ.get("SOCPUPPET_TWISTER_HOME")
        # Out of it, build/firmware has Zephyr, and the directory of this
        # machine's tools the SDK and the venv.
        self.machine = (
            FIRMWARE / load(REPOSITORY / "firmware" / "build.py").sdk_host()
        )
        self.zephyr = Path(self.home or FIRMWARE) / "zephyr"
        tools = Path(self.home) if self.home else self.machine
        self.sdk = tools / self.sdk_name
        self.venv = tools / "venv"
        self.out = Path(self.home) / "out" if self.home else OUT
        self.runs: list[str] = []

    def go(self, arguments: list[str]) -> int:
        """Run twister on the suites asked for. Returns the worst status."""
        self.check_what_it_needs()
        if os.environ.get("SOCPUPPET_TWISTER_BUILD"):
            self.build_for_linux()
        self.check_socpuppet()
        if self.home:
            self.fill_the_volume()
        else:
            self.install_what_twister_imports(self.venv)
        self.set_up()
        status = 0
        if arguments[:1] == ["--suites"]:
            status = self.suites(arguments[1:])
        else:
            status = self.twister("one", arguments)
        self.bring_back()
        say("Verdicts and logs: build/twister/out")
        return status

    def check_what_it_needs(self) -> None:
        """Stop if what firmware/build.py fetches and builds is not there."""
        for each in (
            FIRMWARE / "zephyr",
            self.machine / "venv" / "bin" / "python",
            self.machine / self.sdk_name,
            FIRMWARE / "rom_rv32.elf",
            FIRMWARE / "rom_rv64.elf",
        ):
            if not each.exists():
                raise Failed(
                    f"There is no {each}. Run "
                    "`uv run firmware/build.py rom zephyr-tree` first, which "
                    "fetches Zephyr and its SDK and builds the boot ROMs."
                )

    def check_socpuppet(self) -> None:
        """Stop if socpuppet is not built for this machine.

        Python's own words are left to be read: a venv that is not there,
        an extension built for another Python and a library that is
        missing each say something different.
        """
        imported = subprocess.run(
            [
                str(self.project_venv / "bin" / "python"),
                *("-c", "import socpuppet; socpuppet.Platform"),
            ],
            env={**os.environ, "PYTHONPATH": str(REPOSITORY / "python")},
        )
        if imported.returncode != 0:
            raise Failed(
                "socpuppet is not built for this machine. Build it first: "
                "uv sync && uv run cmake --preset dev && "
                "uv run cmake --build --preset dev"
            )

    def build_for_linux(self) -> None:
        """In the container, build socpuppet for Linux, again each run.

        It is the linux preset's tree, build/linux. A venv whose Python was
        in a container that is gone is made again, and the tree with it,
        since its cache names that Python's headers. A tree whose
        dependencies were patched by older patches has them dropped, as
        tools/ci.py drops them, to be fetched and patched again.
        """
        tree = REPOSITORY / "build" / "linux"
        if not runs(self.project_venv / "bin" / "python", "-c", ""):
            say("The Linux venv's Python is gone: making it, and build/linux")
            shutil.rmtree(self.project_venv, ignore_errors=True)
            shutil.rmtree(tree, ignore_errors=True)
        ci = load(REPOSITORY / "tools" / "ci.py")
        ci.LOGS.mkdir(parents=True, exist_ok=True)
        ci.drop_stale_dependencies(clean=False)
        command("uv", "sync", "--quiet")
        if not (tree / "CMakeCache.txt").exists():
            say(
                "Building socpuppet for Linux in build/linux, which takes ten "
                "minutes the first time"
            )
            command("uv", "run", "cmake", "--preset", "linux")
        command("uv", "run", "cmake", "--build", "--preset", "linux")

    def fill_the_volume(self) -> None:
        """Copy Zephyr and the SDK to the volume, once for each version.

        A stamp of the two versions says whether the volume's copy is the
        one build/firmware has.
        """
        assert self.home
        home = Path(self.home)
        described = subprocess.run(
            [
                "git",
                "-C",
                str(FIRMWARE / "zephyr"),
                "describe",
                "--tags",
                "--always",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        stamp = f"{described or 'unknown'} {self.sdk_name}"
        if (
            not (home / "stamp").exists()
            or (home / "stamp").read_text().strip() != stamp
        ):
            say("Copying Zephyr and the SDK to the volume, once a version")
            for each in ("zephyr", self.sdk_name, "venv", ".west"):
                shutil.rmtree(home / each, ignore_errors=True)
            shutil.copytree(
                FIRMWARE / "zephyr",
                home / "zephyr",
                symlinks=True,
                ignore=shutil.ignore_patterns(".git"),
            )
            shutil.copytree(
                self.machine / self.sdk_name,
                home / self.sdk_name,
                symlinks=True,
            )
            initialized = subprocess.run(
                [
                    str(self.machine / "venv" / "bin" / "west"),
                    *("init", "--local", "zephyr"),
                ],
                cwd=home,
                capture_output=True,
                text=True,
            )
            if initialized.returncode != 0:
                raise Failed(
                    f"west could not make the volume a workspace:\n"
                    f"{initialized.stderr}"
                )
            (home / "stamp").write_text(stamp + "\n")
        if not runs(self.venv / "bin" / "python", "-c", TWISTER_IMPORTS):
            say("Making the volume's venv")
            shutil.rmtree(self.venv, ignore_errors=True)
            command(
                *("uv", "venv", "--quiet", "--python-preference"),
                *("only-managed", str(self.venv)),
                env={"UV_PYTHON_INSTALL_DIR": str(home / "python")},
            )
            command(
                *("uv", "pip", "install", "--quiet"),
                *("--python", str(self.venv / "bin" / "python")),
                "--requirement",
                str(self.zephyr / "scripts" / "requirements-base.txt"),
                *("--requirement", str(REQUIREMENTS), "cmake", "ninja"),
            )

    def install_what_twister_imports(self, venv: Path) -> None:
        """Install what twister imports, if the venv lacks it.

        firmware/build.py puts it in Zephyr's venv from the start, so this
        is for a venv made before it did.
        """
        if not runs(venv / "bin" / "python", "-c", TWISTER_IMPORTS):
            command(
                *("uv", "pip", "install", "--quiet"),
                *("--python", str(venv / "bin" / "python")),
                *("--requirement", str(REQUIREMENTS)),
            )

    def set_up(self) -> None:
        """Put the emulator on the PATH, and tell twister where all is.

        The emulator goes by the name the boards' platform files give it.
        Twister looks for it on its own PATH before it runs anything, and
        builds a board whose emulator it cannot find without ever running
        it. The tree's own socpuppet is not installed anywhere, so it is
        given a name here.
        """
        programs = REPOSITORY / "build" / "twister" / "bin"
        programs.mkdir(parents=True, exist_ok=True)
        socpuppet = programs / "socpuppet"
        socpuppet.write_text(
            "#!/bin/sh\n"
            f'PYTHONPATH="{REPOSITORY / "python"}" exec '
            f'"{self.project_venv / "bin" / "python"}" -m socpuppet "$@"\n'
        )
        socpuppet.chmod(0o755)
        os.environ.update(
            {
                "ZEPHYR_BASE": str(self.zephyr),
                "ZEPHYR_TOOLCHAIN_VARIANT": "zephyr",
                "ZEPHYR_SDK_INSTALL_DIR": str(self.sdk),
                # The same variable tells twister where the boards are and
                # CMake where the module is.
                "ZEPHYR_EXTRA_MODULES": str(
                    REPOSITORY / "python" / "socpuppet" / "zephyr_module"
                ),
                "PATH": os.pathsep.join(
                    [str(programs), str(self.venv / "bin"), os.environ["PATH"]]
                ),
                # Where `socpuppet run` finds the boot ROM. Ninja runs it
                # from the image's build directory, so the default,
                # build/firmware under where it is run, would not do.
                "SOCPUPPET_FIRMWARE_DIR": str(FIRMWARE),
                # Zephyr's build uses ccache when it finds one, and it was
                # measured to cost more than it saves once the sources are
                # on a local disk.
                "USE_CCACHE": "0",
            }
        )

    def suites(self, arguments: list[str]) -> int:
        """Run every suite of the list. Returns the worst status.

        The suites with no flags of their own run in one run of twister,
        which is much quicker than a run each. A suite with flags gets a
        run of its own, so that a flag such as -K forces nothing but its
        own suite onto a board.
        """
        boards: list[str] = []
        if not any(
            word in ("-p", "--platform")
            or word.startswith(("-p", "--platform="))
            for word in arguments
        ):
            boards = [word for board in BOARDS for word in ("-p", board)]
        plain: list[str] = []
        status = 0
        listed = (REPOSITORY / "firmware" / "twister-suites.txt").read_text()
        for line in listed.splitlines():
            words = line.split()
            if not words or words[0].startswith("#"):
                continue
            suite, *flags = words
            if not flags:
                plain += ["-T", suite]
                continue
            say(f"=== {suite} {' '.join(flags)}")
            # The run is named after its suite: tests-arch-riscv-fatal.
            name = suite.replace("/", "-")
            ran = self.twister(name, ["-T", suite, *flags, *boards, *arguments])
            status = status or ran
        say("=== the rest of firmware/twister-suites.txt")
        ran = self.twister("suites", [*plain, *boards, *arguments])
        return status or ran

    def twister(self, name: str, arguments: list[str]) -> int:
        """Run twister once, its output in a directory named `name`.

        --clobber-output: the last run's output is replaced, where twister
        would otherwise keep every run's beside it. It gives way to
        --no-clean, which builds on the last run's and is for running a
        failure again.
        """
        self.runs.append(name)
        return subprocess.run(
            [
                str(self.venv / "bin" / "python"),
                str(self.zephyr / "scripts" / "twister"),
                *("--outdir", str(self.out / name)),
                *("--clobber-output", "--no-detailed-test-id"),
                "--quarantine-list",
                str(REPOSITORY / "firmware" / "twister-quarantine.yaml"),
                *self.resolved(arguments),
            ]
        ).returncode

    def resolved(self, arguments: list[str]) -> list[str]:
        """The arguments, with each suite's directory made absolute."""
        resolved: list[str] = []
        words = iter(arguments)
        for word in words:
            if word in ("-T", "--testsuite-root"):
                resolved += ["-T", self.resolve(next(words))]
            elif word.startswith("--testsuite-root="):
                resolved += ["-T", self.resolve(word.split("=", 1)[1])]
            elif word.startswith("-T"):
                resolved += ["-T", self.resolve(word[2:])]
            else:
                resolved.append(word)
        return resolved

    def resolve(self, suite: str) -> str:
        """A -T that is relative is Zephyr's, unless it is ours."""
        if Path(suite).is_absolute():
            return suite
        if Path(suite).parts[0] in ("firmware", "python"):
            return str(REPOSITORY / suite)
        return str(self.zephyr / suite)

    def bring_back(self) -> None:
        """Bring this command's verdicts and logs back from the volume.

        The builds stay there.
        """
        if not self.home:
            return
        shutil.rmtree(OUT, ignore_errors=True)
        kept = ("twister.log", "build.log", "handler.log", "handler_stderr.log")
        for name in self.runs:
            for path in (self.out / name).rglob("*"):
                if path.is_file() and (
                    path.suffix in (".json", ".xml") or path.name in kept
                ):
                    copy = OUT / path.relative_to(self.out)
                    copy.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, copy)


def say(text: str) -> None:
    """Tell the person running twister what it is doing."""
    print(text, flush=True)


def command(*argv: str, env: dict[str, str] | None = None) -> None:
    """Run a command, and stop if it fails."""
    if subprocess.run(argv, env={**os.environ, **(env or {})}).returncode:
        raise Failed(f"{' '.join(argv)} failed")


def runs(program: Path, *args: str) -> bool:
    """Whether a program is there and runs, quietly."""
    try:
        return (
            subprocess.run(
                [str(program), *args], capture_output=True
            ).returncode
            == 0
        )
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(main())
