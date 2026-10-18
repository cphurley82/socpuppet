#!/usr/bin/env python3
"""Build the firmware the tests boot, and fetch what builds it.

Usage:
  uv run firmware/build.py [--out DIR] [-j N] [--in-docker] [PART ...]

The parts, each of which fetches or builds what it needs first:

  sdk          the Zephyr SDK's RISC-V toolchain
  llvm         the SDK's LLVM, for OpenSBI and EDK2
  zephyr-tree  Zephyr itself, a venv for its build scripts and twister's,
               and a west workspace around it
  rom          the boot ROM, for each kind of CPU, and sbi_payload, a
               program of ours for OpenSBI to jump to
  opensbi      OpenSBI for the host, as fw_jump, with its test_payload
  zephyr       Zephyr's images: four samples and two of its tests, and
               four applications of ours, for the boards they run on
  edk2         EDK2, which is UEFI, as uefi.fd
  linux        Linux, a stock defconfig kernel for the host, as linux.bin

With no part named, every one is built, in that order. Everything goes in
the output directory (build/firmware), and a second run reuses what is
there. For each Zephyr image it leaves <name>_<board>.elf, the image with
symbols; <name>_<board>.bin, the same as flat bytes, loaded at the start
of RAM; and <name>_<board>.opcodes.txt, how often each instruction appears
in it. The boot ROM, fw_jump, test_payload and sbi_payload are each an .elf
and a .bin, and EDK2 is uefi.fd, its flash device image. Linux is
linux.bin, the flat Image that fw_jump jumps to, linux.elf, its vmlinux
with the symbols, and linux.map, its System.map.

The Zephyr SDK has no toolchain for an Intel Mac. There the build runs in
the devcontainer's image, which is Linux, by way of tools/devcontainer.py,
and needs Docker for that; --in-docker does the same anywhere, and the
linux part does so on any Mac, whose file system cannot hold the kernel's
tree. The images come out the same: they are RISC-V programs, and do not
care what built them.
"""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import tomllib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
# socpuppet's boards, shields and drivers are in a Zephyr module that ships
# inside the Python package (`socpuppet zephyr-module` prints where). Here
# it is used straight from the repository.
MODULE = REPOSITORY / "python" / "socpuppet" / "zephyr_module"
PATCHES = REPOSITORY / "cmake" / "patches"

PARTS = (
    *("sdk", "llvm", "zephyr-tree"),
    *("rom", "opensbi", "zephyr", "edk2", "linux"),
)


@dataclass(frozen=True)
class Image:
    """One Zephyr image: an application, for a board, with a shield.

    The application is a directory of Zephyr's, or one of this
    repository's if it starts with "firmware/", and the image is named
    after the last part of it. A shield is Zephyr's word for hardware
    plugged into a board.
    """

    application: str
    board: str
    shield: str = ""
    #: What the image is called, if not the last part of the application's
    #: path: Zephyr's tests are each called `api` or the like.
    name: str = ""
    #: Kconfig options the image is built with beyond the application's
    #: and the shield's, each `CONFIG_<NAME>=<value>`.
    options: tuple[str, ...] = ()
    #: A devicetree overlay of this repository's laid over the board's and
    #: the shield's, by its path from the top of the repository.
    overlay: str = ""


IMAGES = [
    Image("samples/hello_world", "qemu_riscv64"),
    Image("samples/hello_world", "qemu_riscv32"),
    # socpuppet's own boards: the host, the SSD's controller, and the IO
    # die's manager.
    Image("samples/hello_world", "socpuppet_host"),
    Image("samples/hello_world", "socpuppet_ssd"),
    Image("samples/hello_world", "socpuppet_iomgr"),
    Image("samples/synchronization", "socpuppet_host"),
    # Zephyr's shell, which is typed at, and is woken by the console's
    # interrupt.
    Image("samples/subsys/shell/shell_module", "socpuppet_host"),
    # Zephyr's test of its disk interface, which here drives its NVMe
    # driver. `socpuppet_host_drive` is the host's SSD and the PCIe link
    # it is on.
    Image(
        "tests/drivers/disk/disk_access",
        "socpuppet_host",
        "socpuppet_host_drive",
    ),
    # Zephyr's test of its entropy API, which here drives its virtio
    # entropy driver against 🎭 the host's virtio entropy device.
    # `socpuppet_host_virtio` is the host's virtio slots.
    Image(
        "tests/drivers/entropy/api",
        "socpuppet_host",
        "socpuppet_host_virtio",
        name="entropy_api",
    ),
    # Zephyr's greeting, through its virtio console driver: the second
    # shield makes 🎭 the host's virtio console Zephyr's console, so the
    # 16550 says nothing.
    Image(
        "samples/hello_world",
        "socpuppet_host",
        "socpuppet_host_virtio;socpuppet_host_virtio_console",
        name="hello_virtio_console",
    ),
    # Zephyr's echo server, through its virtio network driver against 🎭
    # the host's virtio network device, with Python at the far end of the
    # wire. The sample leaves Ethernet to the board.
    Image(
        "samples/net/sockets/echo_server",
        "socpuppet_host",
        "socpuppet_host_virtio",
        options=("CONFIG_NET_L2_ETHERNET=y",),
    ),
    # Zephyr's virtiofs sample, through its virtio-fs client against 🎭 the
    # host's virtio file system device, with Python serving the share. The
    # sample names its device by a label of QEMU's x86 boards, which an
    # overlay of ours gives the host's device too, and asks for PCIe, which
    # QEMU's device is on and the host's is not.
    Image(
        "samples/subsys/fs/virtiofs",
        "socpuppet_host",
        "socpuppet_host_virtio",
        options=("CONFIG_PCIE=n",),
        overlay="firmware/virtiofs_sample.overlay",
    ),
    # The IO die's manager firmware, and the SSD's own.
    Image("firmware/iomgr", "socpuppet_iomgr"),
    Image("firmware/ssd", "socpuppet_ssd"),
    # Zephyr's test of a flash driver, which here is the driver for the
    # SSD's NAND. The application says how to build it for the board, and
    # adds nothing to it.
    Image("firmware/flash_test", "socpuppet_ssd"),
    # Asks for a reset and then stops feeding its watchdog, and says why
    # it started each time.
    Image("firmware/watchdog", "socpuppet_host"),
    Image("firmware/watchdog", "socpuppet_ssd"),
]

# What twister imports beyond what a build needs, which is in Zephyr's
# venv from the start, so that twister has nothing to install into a venv
# a build may be reading.
TWISTER_REQUIREMENTS = REPOSITORY / "firmware" / "twister-requirements.txt"

# What a part's build needs that is not fetched here, by the part: each is
# the program, its Ubuntu package and its Homebrew formula. EDK2 needs
# ACPICA's compiler, which compiles the ACPI tables of a driver of EDK2's.
# The kernel's build generates its parsers with flex and bison, and does
# its arithmetic with bc.
PROGRAMS = {
    "edk2": (("iasl", "acpica-tools", "acpica"),),
    "linux": (
        ("flex", "flex", "flex"),
        ("bison", "bison", "bison"),
        ("bc", "bc", "bc"),
    ),
}
# The machines the Zephyr SDK has a toolchain for, by the names it gives
# them. An Intel Mac is not one, and builds in Docker.
SDK_HOSTS = ("linux-x86_64", "linux-aarch64", "macos-aarch64")


class Failed(Exception):
    """A step of the build that failed, and what to tell the person."""


def main() -> int:
    """Build the parts asked for. Returns the exit status."""
    parser = argparse.ArgumentParser(
        prog="firmware/build.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "parts",
        nargs="*",
        choices=PARTS,
        metavar="part",
        help="build only these (default: all of them): %(choices)s",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPOSITORY / "build" / "firmware",
        help="the output directory (default: build/firmware)",
    )
    parser.add_argument(
        "-j",
        dest="jobs",
        type=int,
        default=2,
        metavar="N",
        help="build up to N of Zephyr's images at once (default: 2)",
    )
    parser.add_argument(
        "--in-docker",
        action="store_true",
        help="build in the devcontainer's image, as an Intel Mac does",
    )
    args = parser.parse_args()
    parts = args.parts or list(PARTS)
    out = args.out.resolve()
    try:
        if args.in_docker or sdk_host() == "macos-x86_64":
            return in_docker(parts, out, args.jobs)
        here = [p for p in parts if not builds_in_docker(p, sdk_host())]
        check_the_machine(here)
        build = Build(out, args.jobs)
        for part in parts:
            if part in here:
                build.parts[part]()
            elif status := in_docker([part], out, args.jobs):
                return status
    except Failed as failure:
        print(f"❌ {failure}", file=sys.stderr)
        return 1
    return 0


def builds_in_docker(part: str, host: str) -> bool:
    """Whether a part builds in the devcontainer's image on this machine.

    The kernel does on any Mac: its tree has files whose names differ only
    in their case, which a Mac's file system keeps as one, and its build
    wants a GNU make newer than a Mac's.
    """
    return part == "linux" and host.startswith("macos")


def check_the_machine(parts: list[str]) -> None:
    """Stop before any download if this machine cannot build the parts."""
    if sdk_host() not in SDK_HOSTS:
        raise Failed(
            "The Zephyr SDK has no toolchain for this machine "
            f"({platform.system()} {platform.machine()}). Build the firmware "
            "on Linux (x86-64 or arm64) or on a Mac."
        )
    for part in parts:
        for program, apt, brew in PROGRAMS.get(part, ()):
            if not shutil.which(program):
                raise Failed(
                    f"The {part} part's build needs {program}, and there is "
                    f"none. Install it: `sudo apt-get install {apt}` on "
                    f"Ubuntu, `brew install {brew}` on a Mac."
                )


def in_docker(parts: list[str], out: Path, jobs: int) -> int:
    """Run the same build in the devcontainer's image. Returns its status.

    The image is Linux, which the SDK has a toolchain for. The repository
    is at /workspace in there, so the output directory has to be inside it,
    where a path the build writes into an image (a source file's, for a
    debugger) is good in any container that has the repository there.
    """
    if not out.is_relative_to(REPOSITORY):
        raise Failed(
            f"{out} is outside the repository, which is all the "
            "devcontainer's image sees. Build into a directory inside it, "
            "and copy the images from there."
        )
    inside = Path("/workspace") / out.relative_to(REPOSITORY)
    return subprocess.run(
        [
            str(REPOSITORY / "tools" / "devcontainer.py"),
            *("python3", "firmware/build.py", *parts),
            *("--out", str(inside), "-j", str(jobs)),
        ],
        cwd=REPOSITORY,
    ).returncode


def read_pins(path: Path) -> dict[str, dict[str, str]]:
    """What versions.toml pins, by name: each a version, some a sha256."""
    return tomllib.loads(path.read_text())


def read_versions(path: Path) -> dict[str, str]:
    """The version of each thing the firmware is built with, by its name."""
    return {name: pin["version"] for name, pin in read_pins(path).items()}


def sdk_host() -> str:
    """The name the Zephyr SDK gives this kind of machine."""
    system = {"Linux": "linux", "Darwin": "macos"}.get(platform.system(), "")
    machine = {"arm64": "aarch64"}.get(platform.machine(), platform.machine())
    return f"{system}-{machine}"


class Build:
    """The firmware, built into one output directory, a part at a time."""

    def __init__(self, out: Path, jobs: int) -> None:
        self.out = out
        self.jobs = jobs
        self.pins = read_pins(REPOSITORY / "firmware" / "versions.toml")
        self.versions = {
            name: pin["version"] for name, pin in self.pins.items()
        }
        sdk_version = self.versions["sdk"]
        self.sdk_dir = out / f"zephyr-sdk-{sdk_version}"
        self.toolchain = self.sdk_dir / "gnu" / "riscv64-zephyr-elf"
        # Kept beside the SDK and not in it: it is two gigabytes, and what
        # copies or caches the SDK for Zephyr would carry it for nothing.
        self.llvm_dir = out / f"llvm-{sdk_version}"
        self.zephyr_dir = out / "zephyr"
        self.venv = out / "venv"
        out.mkdir(parents=True, exist_ok=True)
        # What each part's name runs.
        self.parts = {
            "sdk": self.sdk,
            "llvm": self.llvm,
            "zephyr-tree": self.zephyr_tree,
            "rom": self.rom,
            "opensbi": self.opensbi,
            "zephyr": self.zephyr,
            "edk2": self.edk2,
            "linux": self.linux,
        }

    # The toolchains.

    def sdk(self) -> None:
        """The SDK's small base bundle, and its one RISC-V compiler.

        The compiler builds for both 32 and 64 bits.
        """
        if self.toolchain.is_dir():
            return
        host = sdk_host()
        version = self.versions["sdk"]
        say(f"Fetching the Zephyr SDK {version} RISC-V toolchain for {host}")
        with self.staging() as name:
            staging = Path(name)
            self.fetch_sdk_file(
                f"zephyr-sdk-{version}_{host}_minimal.tar.xz", staging
            )
            self.fetch_sdk_file(
                f"toolchain_gnu_{host}_riscv64-zephyr-elf.tar.xz",
                staging / self.sdk_dir.name / "gnu",
            )
            # What an older run left of one, without its compiler, goes.
            shutil.rmtree(self.sdk_dir, ignore_errors=True)
            (staging / self.sdk_dir.name).rename(self.sdk_dir)

    def llvm(self) -> None:
        """The SDK's LLVM, which OpenSBI and EDK2 are built with.

        🎓 They are linked as position-independent programs, or with
        `-z notext`, and the SDK's GNU linker, built for bare-metal
        programs, refuses both. LLVM's linker does either, for any target.
        """
        if self.llvm_dir.is_dir():
            return
        host = sdk_host()
        say(f"Fetching the Zephyr SDK {self.versions['sdk']} LLVM for {host}")
        with self.staging() as name:
            staging = Path(name)
            self.fetch_sdk_file(f"toolchain_llvm_{host}.tar.xz", staging)
            (unpacked,) = staging.iterdir()
            unpacked.rename(self.llvm_dir)

    def staging(self) -> tempfile.TemporaryDirectory[str]:
        """A directory to unpack into, next to where it all goes.

        What is unpacked is moved into place only when it is whole, so a
        fetch that stops part of the way leaves nothing half there.
        """
        return tempfile.TemporaryDirectory(prefix=".staging-", dir=self.out)

    def fetch_sdk_file(self, name: str, into: Path) -> None:
        """Download one file of the SDK's release, check it, and unpack it.

        The checksum it is checked against is the one the release lists.
        """
        release = (
            "https://github.com/zephyrproject-rtos/sdk-ng/releases/download/"
            f"v{self.versions['sdk']}"
        )
        with tempfile.TemporaryDirectory(
            prefix=".download-", dir=self.out
        ) as directory:
            sums = Path(directory) / "sha256.sum"
            download(f"{release}/sha256.sum", sums)
            self.fetch(
                f"{release}/{name}", into, sha256=checksum_of(sums, name)
            )

    def fetch(self, url: str, into: Path, *, sha256: str) -> None:
        """Download one tarball, check it against `sha256`, and unpack it."""
        name = url.rsplit("/", 1)[-1]
        with tempfile.TemporaryDirectory(
            prefix=".download-", dir=self.out
        ) as directory:
            downloaded = Path(directory) / name
            download(url, downloaded)
            with downloaded.open("rb") as file:
                actual = hashlib.file_digest(file, "sha256").hexdigest()
            if actual != sha256:
                raise Failed(
                    f"{name}'s SHA-256 is {actual}, not the {sha256} it was "
                    "checked against. A download that stopped short gives "
                    "this; so does a version bumped in firmware/versions.toml "
                    "without its sha256. Run this again; if it fails the "
                    "same way, fix the pin."
                )
            into.mkdir(parents=True, exist_ok=True)
            try:
                with tarfile.open(downloaded) as archive:
                    archive.extractall(into, filter="tar")
            except (tarfile.TarError, EOFError, OSError) as error:
                raise Failed(f"{name} could not be unpacked: {error}") from None

    def zephyr_tree(self) -> None:
        """Zephyr, its build's Python packages, and a west workspace.

        Nothing built here needs any of Zephyr's external modules, so only
        the one repository is fetched.
        """
        if not self.zephyr_dir.is_dir():
            say(f"Fetching Zephyr {self.versions['zephyr']}")
            clone(
                "https://github.com/zephyrproject-rtos/zephyr",
                self.versions["zephyr"],
                self.zephyr_dir,
            )
        patch(self.zephyr_dir, "zephyr-*.patch")
        # The Python packages Zephyr's build scripts import, with CMake and
        # Ninja, and what twister imports, in an environment of their own.
        # The Python itself is uv's, kept in the output directory with the
        # rest. An environment only points at its Python, and one that
        # pointed outside the output directory would be left pointing at
        # nothing when this runs in a container that is thrown away
        # afterwards. So an environment whose CMake no longer runs is made
        # again.
        if not runs(self.venv / "bin" / "cmake", "--version"):
            say("Installing what Zephyr's build and twister need")
            shutil.rmtree(self.venv, ignore_errors=True)
            run(
                *("uv", "venv", "--quiet", "--python-preference"),
                *("only-managed", str(self.venv)),
                env={"UV_PYTHON_INSTALL_DIR": str(self.out / "python")},
            )
            run(
                *("uv", "pip", "install", "--quiet"),
                *("--python", str(self.venv / "bin" / "python")),
                "--requirement",
                str(self.zephyr_dir / "scripts" / "requirements-base.txt"),
                *("--requirement", str(TWISTER_REQUIREMENTS)),
                *("cmake", "ninja"),
            )
        # Zephyr's build expects to be inside a west workspace (west is
        # Zephyr's tool for managing its repositories), and at this release
        # it fails without one. So the output directory is made a workspace
        # whose only repository is Zephyr: nothing more is downloaded.
        if not (self.out / ".west").is_dir():
            run(
                str(self.venv / "bin" / "west"),
                *("init", "--local", "zephyr"),
                cwd=self.out,
            )

    # What is built with the SDK's compiler and nothing of Zephyr's.

    def rom(self) -> None:
        """The boot ROM, for each kind of CPU, and sbi_payload.

        The ROM is a program with no operating system and no C library
        under it, linked to run from where a socpuppet CPU has its ROM. It
        includes the register maps the Zephyr module carries, for the
        system controller and for the header of the image it loads.

        sbi_payload is a program in supervisor mode that makes the calls of
        SBI's that OpenSBI's test_payload does not. It is built as the ROM
        is, for where fw_jump jumps, and finds the system controller where
        the ROM does.
        """
        self.sdk()
        rom = REPOSITORY / "firmware" / "rom"
        for kind, march, mabi in (
            ("rv64", "rv64imac_zicsr", "lp64"),
            ("rv32", "rv32imac_zicsr", "ilp32"),
        ):
            say(f"Building the boot ROM for {kind}")
            self.bare_metal(
                self.out / f"rom_{kind}",
                march,
                mabi,
                rom / f"board_{kind}.h",
                rom / "rom.ld",
                rom,
            )
        say("Building the payload of ours for OpenSBI")
        payload = REPOSITORY / "firmware" / "sbi_payload"
        self.bare_metal(
            self.out / "sbi_payload",
            "rv64imac_zicsr",
            "lp64",
            rom / "board_rv64.h",
            payload / "payload.ld",
            payload,
        )

    def bare_metal(
        self,
        image: Path,
        march: str,
        mabi: str,
        board: Path,
        script: Path,
        sources: Path,
    ) -> None:
        """Compile a program that runs with nothing under it, and its .bin.

        ⚠️ The linker script is given to gcc itself with -T. Handed to the
        linker with -Wl,-T it is ignored without a word: the SDK's gcc is
        set up for picolibc, whose own script it uses unless it sees a -T
        of its own.
        """
        run(
            self.tool("gcc"),
            f"-march={march}",
            f"-mabi={mabi}",
            "-mcmodel=medany",
            *("-Os", "-g", "-Wall", "-Wextra", "-Werror", "-ffreestanding"),
            *("-nostdlib", "-nostartfiles"),
            *("-I", str(MODULE / "include"), "-include", str(board)),
            *("-T", str(script)),
            str(sources / "start.S"),
            *(str(c) for c in sorted(sources.glob("*.c"))),
            *("-o", f"{image}.elf"),
        )
        run(
            self.tool("objcopy"), "-O", "binary", f"{image}.elf", f"{image}.bin"
        )
        self.report(image)

    def opensbi(self) -> None:
        """OpenSBI, at its pinned release, for the host.

        🎓 `fw_jump` is the build of OpenSBI that jumps to a next stage
        somebody else has put in RAM: on the generic platform, 2 MiB into
        it, which is where Linux wants to be. The generic platform also
        builds test_payload, the payload it carries when it is given none;
        FW_PAYLOAD_OFFSET links test_payload where fw_jump jumps. OpenSBI
        runs wherever it is put, and FW_TEXT_START is only where its ELF
        file says it goes: the start of the host's RAM, so that Python can
        load it there.

        ⚠️ The SDK's clang knows which C libraries it has, and refuses
        flags it has none for. OpenSBI links no C library at all, so the
        refusal is turned off.

        ⚠️ On macOS OpenSBI's Makefile asks for greadlink, GNU's readlink
        from Homebrew's coreutils, for `readlink -f`. macOS's own has had
        -f since macOS 12.3, so it is given that one instead. It says
        nothing of a path that does not exist yet, where GNU's says the
        path, so the directory OpenSBI builds in is made first.
        """
        self.llvm()
        source = self.out / "opensbi"
        if not source.is_dir():
            say(f"Fetching OpenSBI {self.versions['opensbi']}")
            clone(
                "https://github.com/riscv-software-src/opensbi",
                self.versions["opensbi"],
                source,
            )
        patch(source, "opensbi-*.patch")
        say("Building OpenSBI for the host")
        built = self.out / "build_opensbi"
        built.mkdir(exist_ok=True)
        llvm = f"{self.llvm_dir}/bin/"
        logged(
            built.with_suffix(".log"),
            *("make", "-C", str(source), f"O={built}"),
            f"LLVM={llvm}",
            f"CC={llvm}clang -Wno-missing-multilib",
            *("READLINK=readlink", "PLATFORM=generic"),
            *("PLATFORM_RISCV_XLEN=64", "PLATFORM_RISCV_ABI=lp64"),
            "PLATFORM_RISCV_ISA=rv64imafdc_zicsr_zifencei",
            *("FW_TEXT_START=0x80000000", "FW_PAYLOAD_OFFSET=0x200000"),
        )
        firmware = built / "platform" / "generic" / "firmware"
        for name, file in (
            ("fw_jump", "fw_jump"),
            ("test_payload", "payloads/test"),
        ):
            for kind in ("elf", "bin"):
                shutil.copy(
                    firmware / f"{file}.{kind}", self.out / f"{name}.{kind}"
                )
            self.report(self.out / name)

    # Zephyr.

    def zephyr(self) -> None:
        """Zephyr's images, as many at a time as -j says.

        The first to fail stops the build: those not started yet are not
        started, and those building finish first.
        """
        self.sdk()
        self.zephyr_tree()
        failed = threading.Event()

        def build(image: Image) -> None:
            if failed.is_set():
                return
            try:
                self.zephyr_image(image)
            except Failed:
                failed.set()
                raise

        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            building = [pool.submit(build, image) for image in IMAGES]
        for each in building:
            each.result()

    def zephyr_image(self, image: Image) -> None:
        """Build one of Zephyr's images, and count its instructions."""
        called = image.name or Path(image.application).name
        name = f"{called}_{image.board}"
        shield = f" with {image.shield}" if image.shield else ""
        say(f"Building {called} for {image.board}{shield}")
        if image.application.startswith("firmware/"):
            source = REPOSITORY / image.application
        else:
            source = self.zephyr_dir / image.application
        build = self.out / f"build_{name}"
        env = {
            "ZEPHYR_BASE": str(self.zephyr_dir),
            "ZEPHYR_TOOLCHAIN_VARIANT": "zephyr",
            "ZEPHYR_SDK_INSTALL_DIR": str(self.sdk_dir),
            "PATH": f"{self.venv / 'bin'}{os.pathsep}{os.environ['PATH']}",
        }
        log = build.with_suffix(".log")
        cmake = str(self.venv / "bin" / "cmake")
        logged(
            log,
            *(cmake, "-S", str(source), "-B", str(build), "-G", "Ninja"),
            f"-DBOARD={image.board}",
            *([f"-DSHIELD={image.shield}"] if image.shield else []),
            *(f"-D{option}" for option in image.options),
            *(
                [f"-DEXTRA_DTC_OVERLAY_FILE={REPOSITORY / image.overlay}"]
                if image.overlay
                else []
            ),
            "-DCONFIG_BUILD_OUTPUT_BIN=y",
            f"-DZEPHYR_EXTRA_MODULES={MODULE}",
            f"-DUSER_CACHE_DIR={self.out / 'cache'}",
            env=env,
        )
        logged(log, cmake, "--build", str(build), env=env, after=True)
        made = self.out / name
        for kind in ("elf", "bin"):
            shutil.copy(build / "zephyr" / f"zephyr.{kind}", f"{made}.{kind}")
        disassembly = subprocess.run(
            [
                self.tool("objdump"),
                "--disassemble",
                "--no-show-raw-insn",
                "--disassembler-options=no-aliases",
                f"{made}.elf",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        Path(f"{made}.opcodes.txt").write_text(opcodes(disassembly))
        self.report(made)

    # EDK2.

    def edk2(self) -> None:
        """EDK2, at its stable tag: UEFI, as OpenSBI's next stage on the host.

        It is built from its port for QEMU's RISC-V `virt`.

        🎓 EDK2's build is a tool of its own, `build`, written in Python,
        which reads a platform's description (a .dsc, what to build, and an
        .fdf, how to lay it out in flash) and drives the compiler. Some of
        what it runs is in C, `BaseTools`, which is built first with the
        machine's own compiler and wants libuuid's header. A driver or two
        have ACPI tables written in ASL, compiled by ACPICA's iasl, which
        the system provides. EDK2 reads the include directories of every
        submodule a package declares, used or not, so all of them are
        fetched, each one commit deep.

        ⚠️ It is built with the SDK's LLVM, as OpenSBI is. EDK2 links every
        module with `-z notext`, which the SDK's GNU linker refuses.

        💡 The image is not position-independent: it runs where its FD (its
        flash device image) was built for, which is QEMU's flash on QEMU.
        PFLASH0_BASE is a define of the port's .fdf, and a define on the
        command line wins, so it is built for 2 MiB into the host's RAM,
        where fw_jump jumps. There is no flash to keep UEFI's variables in,
        so they are kept in RAM, and forgotten at reset
        (PcdEmuVariableNvModeEnable). The port's FD is 8 MiB, of which EDK2
        fills under 2, so it is built as 2 MiB, which is 6 MiB less for a
        boot ROM to check, in blocks of the port's 4 KiB, each number in
        hex, as an .fdf has it. It is a DEBUG build, which says on the
        console what each driver does as it loads: the boot is a rehearsal,
        and the console is where it is watched.
        """
        self.llvm()
        source = self.out / "edk2"
        if not source.is_dir():
            say(f"Fetching EDK2 {self.versions['edk2']}")
            clone(
                "https://github.com/tianocore/edk2",
                self.versions["edk2"],
                source,
            )
            run(
                *("git", "-C", str(source), "submodule", "--quiet", "update"),
                *("--init", "--depth", "1"),
            )
        patch(source, "edk2-*.patch")
        say("Building EDK2 for the host")
        logged(
            self.out / "build_edk2_basetools.log",
            *("make", "-C", str(source / "BaseTools"), "--jobs"),
        )
        workspace = self.out / "build_edk2"
        conf = workspace / "Conf"
        conf.mkdir(parents=True, exist_ok=True)
        size = 2 * 1024 * 1024
        target, toolchain = "DEBUG", "CLANGDWARF"
        # EDK2's set-up script sets what its build reads, so the two run in
        # one shell.
        logged(
            self.out / "build_edk2.log",
            "bash",
            "-c",
            'source "$0" BaseTools && build "$@"',
            str(source / "edksetup.sh"),
            *("-a", "RISCV64", "-t", toolchain, "-b", target),
            *("-p", "OvmfPkg/RiscVVirt/RiscVVirtQemu.dsc"),
            *("-n", str(os.cpu_count() or 1)),
            *("-D", "PFLASH0_BASE=0x80200000"),
            *("-D", f"CODE_SIZE={size:#x}"),
            *("-D", f"CODE_BLOCKS={size // 0x1000:#x}"),
            "--pcd",
            "gEfiMdeModulePkgTokenSpaceGuid.PcdEmuVariableNvModeEnable=TRUE",
            env={
                "WORKSPACE": str(workspace),
                "PACKAGES_PATH": str(source),
                "EDK_TOOLS_PATH": str(source / "BaseTools"),
                "CONF_PATH": str(conf),
                "PYTHON_COMMAND": sys.executable,
                "CLANGDWARF_BIN": f"{self.llvm_dir}/bin/",
            },
        )
        fd = (
            workspace
            / "Build"
            / "RiscVVirtQemu"
            / f"{target}_{toolchain}"
            / "FV"
            / "RISCV_VIRT_CODE.fd"
        )
        shutil.copy(fd, self.out / "uefi.fd")
        say(f"  {(self.out / 'uefi.fd').stat().st_size} bytes in uefi.fd")

    # Linux.

    def linux(self) -> None:
        """Linux, at its pinned release, as a stock defconfig kernel.

        🐧 The kernel is built with nothing of ours in it:
        `arch/riscv/configs/defconfig` as it ships, which has the drivers
        for everything on the host that Linux meets (the AIA interrupt
        controllers, the 16550, and 🎭 the virtio devices). What the kernel
        is handed at boot, the devicetree and the root filesystem, is
        Python's and build.py's business, not the kernel's.

        💡 It is the one part fetched as a release tarball and not cloned
        at a tag, as OpenSBI and EDK2 are: the tarball is 150 MB where a
        clone of the kernel's tree, one commit deep, is many times that,
        and kernel.org publishes each tarball's SHA-256, which the fetch
        is checked against (the pin in versions.toml). A tarball is no git
        tree, so there is no `patch()` for it, and none is wanted: a
        stock kernel is the decision (docs/history/decisions.md).

        It is built with the SDK's LLVM, as OpenSBI and EDK2 are: the
        kernel builds with clang and LLVM's linker, told so by `LLVM=`. The
        tools that run on this machine during the build are compiled by
        its own compiler, since the SDK's is for RISC-V.

        ⚠️ The SDK's clang knows which C libraries it has, and refuses
        flags it has none for. The kernel links no C library at all, so
        the refusal is turned off, as it is for OpenSBI.
        """
        self.llvm()
        source = self.out / "linux"
        version = self.versions["linux"]
        if not source.is_dir():
            say(f"Fetching Linux {version}")
            with self.staging() as name:
                staging = Path(name)
                self.fetch(
                    "https://cdn.kernel.org/pub/linux/kernel/"
                    f"v{version.split('.')[0]}.x/linux-{version}.tar.xz",
                    staging,
                    sha256=self.pins["linux"]["sha256"],
                )
                (staging / f"linux-{version}").rename(source)
        say("Building Linux for the host")
        built = self.out / "build_linux"
        built.mkdir(exist_ok=True)
        llvm = f"{self.llvm_dir}/bin/"
        make = (
            *("make", "-C", str(source), f"O={built}", "ARCH=riscv"),
            f"LLVM={llvm}",
            f"CC={llvm}clang -Wno-missing-multilib",
            *("HOSTCC=cc", "HOSTCXX=c++"),
        )
        log = built.with_suffix(".log")
        logged(log, *make, "defconfig")
        logged(log, *make, f"-j{os.cpu_count() or 1}", "Image", after=True)
        for made, kept in (
            ("arch/riscv/boot/Image", "linux.bin"),
            ("vmlinux", "linux.elf"),
            ("System.map", "linux.map"),
        ):
            shutil.copy(built / made, self.out / kept)
        # Not report(): vmlinux's entry is a virtual address, not where
        # linux.bin is loaded, and would mislead.
        say(f"  {(self.out / 'linux.bin').stat().st_size} bytes in linux.bin")

    # Helpers.

    def tool(self, name: str) -> str:
        """One of the SDK's RISC-V tools, by its short name."""
        return str(self.toolchain / "bin" / f"riscv64-zephyr-elf-{name}")

    def report(self, image: Path) -> None:
        """Say what kind of program an image is, where it starts, its size."""
        bits, entry = elf_header(Path(f"{image}.elf"))
        size = Path(f"{image}.bin").stat().st_size
        say(f"  {image.name}: ELF{bits}, starting at {entry:#x}, {size} bytes")


def logged(
    log: Path,
    *command: str,
    env: dict[str, str] | None = None,
    after: bool = False,
) -> None:
    """Run a command with its output in a log, which it starts afresh.

    `after` adds to what the log holds instead. If the command fails, how
    the log ends is shown, and the build stops.
    """
    with log.open("a" if after else "w") as output:
        finished = subprocess.run(
            command,
            stdout=output,
            stderr=subprocess.STDOUT,
            env={**os.environ, **(env or {})},
        )
    if finished.returncode != 0:
        tail = log.read_text(errors="replace").splitlines()[-40:]
        raise Failed(
            "\n".join([*tail, f"{Path(command[0]).name} failed: see {log}"])
        )


def elf_header(path: Path) -> tuple[int, int]:
    """An ELF file's class, 32 or 64, and its entry point.

    🎓 Both are in the header every ELF file starts with: the fifth byte
    says 32 or 64 bits, and the entry point is the address of the first
    instruction, 24 bytes in, as wide as an address. RISC-V's are
    little-endian.
    """
    header = path.read_bytes()[:32]
    bits = 64 if header[4] == 2 else 32
    width = bits // 8
    return bits, int.from_bytes(header[24 : 24 + width], "little")


def opcodes(disassembly: str) -> str:
    """How often each instruction appears in a disassembly, most first.

    A disassembly line is "<address>:", then the instruction's name, then
    its operands, separated by tabs. Without aliases, each is named as the
    instruction it really is: `ret` shows as the `c.jr` it is encoded as.
    """
    counts = Counter(
        fields[1]
        for fields in (line.split("\t") for line in disassembly.splitlines())
        if len(fields) >= 2 and fields[0].endswith(":")
    )
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "".join(f"{count} {name}\n" for name, count in ordered)


def download(url: str, to: Path) -> None:
    """Fetch one file, stopping the build if the server says no."""
    run(
        *("curl", "--fail", "--silent", "--show-error", "--location"),
        *("--output", str(to), url),
    )


def checksum_of(sums: Path, name: str) -> str:
    """The checksum a release's list gives one of its files."""
    for line in sums.read_text().splitlines():
        digest, _, listed = line.partition("  ")
        if listed == name:
            return digest
    raise Failed(f"The SDK's release lists no checksum for {name}.")


def clone(url: str, tag: str, into: Path) -> None:
    """Clone a repository at one tag, one commit deep."""
    run(
        *("git", "clone", "--quiet", "--depth", "1", "--branch", tag),
        *("-c", "advice.detachedHead=false", url, str(into)),
    )


def patch(tree: Path, pattern: str) -> None:
    """Apply socpuppet's patches to a clean tree.

    Each is a file in cmake/patches with its entry in docs/upstream.md. They
    are applied to a clean tree every time, so that a patch that changes is
    the one built.
    """
    run("git", "-C", str(tree), "checkout", "--quiet", "--", ".")
    for each in sorted(PATCHES.glob(pattern)):
        run("git", "-C", str(tree), "apply", str(each))


def run(
    *command: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> None:
    """Run a command whose output is short, and stop the build if it fails."""
    finished = subprocess.run(
        command, cwd=cwd, env={**os.environ, **(env or {})}
    )
    if finished.returncode != 0:
        raise Failed(f"{' '.join(command)} failed")


def runs(program: Path, *args: str) -> bool:
    """Whether a program is there and runs."""
    try:
        return (
            subprocess.run(
                [str(program), *args], capture_output=True
            ).returncode
            == 0
        )
    except OSError:
        return False


def say(text: str) -> None:
    """Tell the person running the build what it is doing."""
    print(text, flush=True)


if __name__ == "__main__":
    sys.exit(main())
