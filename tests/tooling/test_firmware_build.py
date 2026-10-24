"""firmware/build.py, which fetches the firmware's toolchains and builds it.

The script is run for real in a throwaway copy of what it reads, with a
fake for each program it runs: curl, git, make, uv, iasl and the SDK's
own tools, and later the venv's cmake and west and EDK2's build. They are
one script, which logs what it was asked and makes what the real program
would have made, so the tests can say what was built, and how, in seconds.
"""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import NamedTuple

import pytest

from conftest import AS_ON

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "firmware" / "build.py"
VERSIONS = REPO / "firmware" / "versions.toml"
TWISTER_REQUIREMENTS = REPO / "firmware" / "twister-requirements.txt"

# The machine the builds are tested on, whatever the one running the tests is,
# by the name the SDK gives it: by default the one every part builds on here,
# with the SDK's own toolchain. On an Intel Mac the script hands every part to
# Docker, and on any Mac the kernel, which the tests of Docker's routing say.
# The script is run through a few lines that tell it what platform.system()
# and platform.machine() say there.
HOST = "linux-x86_64"
MACHINES = {
    "linux-x86_64": ("Linux", "x86_64"),
    "macos-aarch64": ("Darwin", "arm64"),
    "macos-x86_64": ("Darwin", "x86_64"),
}

# The fake for every program. Each logs its name and arguments, as
# JSON, with when it started and ended. What it then does depends on which
# program it is faking. FAIL_ON names a word, and a command that
# holds it fails, after saying fifty numbered lines. SLOW_ON names a word,
# and a command that holds it takes half a second, far longer than a
# process takes to start, so that two run side by side are seen to overlap.
FAKE = r"""
import json, os, shutil, sys, time
name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
started = time.time()
fake = os.environ["FAKE"]


def write(path, text=""):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as file:
        file.write(text)


def elf(path):
    # An ELF64 file's header, starting at 0x80000000, and nothing more.
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    entry = (0x80000000).to_bytes(8, "little")
    with open(path, "wb") as file:
        file.write(b"\x7fELF\x02\x01\x01" + bytes(17) + entry)


def write_fake(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copy(fake, path)
    os.chmod(path, 0o755)


def after(flag):
    return args[args.index(flag) + 1]


status = 0
if os.environ.get("FAIL_ON", "@") in [name, *args]:
    for line in range(1, 51):
        print(f"spam {line}")
    status = 1
elif name == "curl":
    source = os.path.join(os.environ["DOWNLOADS"], os.path.basename(args[-1]))
    if os.path.exists(source):
        shutil.copy(source, after("--output"))
    else:
        # What curl --fail exits with when the server says no.
        status = 22
elif name == "git" and "clone" in args:
    # A clone keeps the tag it was made at in .git/TAG, and, as git's own,
    # refuses to clone into a directory with anything in it.
    url, directory = args[-2], args[-1]
    template = os.path.join(os.environ["CLONES"], os.path.basename(url))
    if os.path.isdir(directory) and os.listdir(directory):
        print(f"fatal: destination path '{directory}' already exists")
        status = 128
    elif os.path.isdir(template):
        shutil.copytree(template, directory)
    if status == 0:
        write(os.path.join(directory, ".git", "TAG"), after("--branch"))
elif name == "git" and "--points-at" in args:
    tag = os.path.join(after("-C"), ".git", "TAG")
    if os.path.exists(tag):
        print(open(tag).read())
    else:
        print(f"fatal: not a git repository: {after('-C')}")
        status = 128
elif name == "git" and "apply" in args:
    # A tree's patches are kept in one file of it, PATCHED, in the order
    # they were applied; checking the tree out again throws them away.
    with open(os.path.join(after("-C"), "PATCHED"), "a") as patched:
        patched.write(open(args[-1]).read())
elif name == "git" and "checkout" in args:
    patched = os.path.join(after("-C"), "PATCHED")
    if os.path.exists(patched):
        os.remove(patched)
elif name == "make" and "ARCH=riscv" in args:
    built = next(a[2:] for a in args if a.startswith("O="))
    if not os.path.exists(os.path.join(after("-C"), "Makefile")):
        print(f"make: *** No Makefile in {after('-C')}")
        status = 2
    elif "defconfig" in args:
        write(f"{built}/.config", "CONFIG_SPAM=y\n")
    elif "Image" in args:
        write(f"{built}/arch/riscv/boot/Image", "Image")
        elf(f"{built}/vmlinux")
        write(f"{built}/System.map", "ffffffff80000000 T _start\n")
        # The kernel's build makes its own tool for initramfs archives,
        # and says which release it is.
        write_fake(f"{built}/usr/gen_init_cpio")
        makefile = open(os.path.join(after("-C"), "Makefile")).read()
        write(f"{built}/include/config/kernel.release", makefile.split()[-1])
    for module in (a for a in args if a.endswith(".ko")):
        write(f"{built}/{module}", module)
elif name == "make" and any(a.startswith("O=") for a in args):
    built = next(a[2:] for a in args if a.startswith("O="))
    for each in ("fw_jump", "payloads/test"):
        for kind in ("elf", "bin"):
            elf(f"{built}/platform/generic/firmware/{each}.{kind}")
elif name == "uv" and args[0] == "venv":
    write_fake(os.path.join(args[-1], "bin", "python"))
elif name == "uv" and args[:2] == ["pip", "install"]:
    venv = os.path.dirname(os.path.dirname(after("--python")))
    for program in ("cmake", "west"):
        write_fake(os.path.join(venv, "bin", program))
elif name == "west":
    os.makedirs(".west", exist_ok=True)
elif name == "cmake" and args[0] == "--build":
    elf(os.path.join(args[1], "zephyr", "zephyr.elf"))
    elf(os.path.join(args[1], "zephyr", "zephyr.bin"))
elif name.endswith("-gcc"):
    elf(after("-o"))
elif name.endswith("-objcopy"):
    shutil.copy(args[-2], args[-1])
elif name.endswith("-objdump"):
    print(open(os.environ["DISASSEMBLY"]).read(), end="")
elif name == "mkfs.ext4":
    # The image is a tar of the tree it was made from, so a test can look
    # inside it as it would a real one.
    shutil.make_archive(args[-2], "tar", after("-d"))
    os.replace(args[-2] + ".tar", args[-2])
elif name == "gen_init_cpio":
    # The archive is a line of JSON for each entry of the list, in the
    # list's order, holding each file's text, so a test can read what is
    # in it; and, as the real tool, it fails on a file that is not there.
    # The list is in the kernel's format (usr/gen_init_cpio.c).
    entries = []
    for line in open(args[-1]).read().splitlines():
        kind, entry, *fields = line.split()
        if kind == "file" and not os.path.exists(fields[0]):
            print(f"File {fields[0]} could not be opened for reading")
            status = 1
            break
        entries.append(json.dumps({
            "kind": kind,
            "name": entry,
            "data": open(fields[0], errors="replace").read()
            if kind == "file" else None,
            "to": fields[0] if kind == "slink" else None,
            "device": " ".join(fields[3:]) if kind == "nod" else None,
            "mode": fields[1] if kind in ("file", "slink") else fields[0],
        }))
    if status == 0:
        write(after("-o"), "\n".join(entries) + "\n")
elif name == "build":
    built = os.path.join(
        os.environ["WORKSPACE"], "Build/RiscVVirtQemu/DEBUG_CLANGDWARF"
    )
    write(os.path.join(built, "FV/RISCV_VIRT_CODE.fd"), "uefi")
    write(os.path.join(built, "RISCV64/Shell.efi"), "shell")
if os.environ.get("SLOW_ON", "@") in [name, *args]:
    time.sleep(0.5)
with open(os.environ["LOG"], "a") as log:
    log.write(json.dumps({
        "name": name,
        "args": args,
        "start": started,
        "end": time.time(),
    }) + "\n")
sys.exit(status)
"""

# What EDK2's set-up script does here: put its build on the PATH.
# What EDK2's setup does here: copy its Conf template where there is none,
# or over the one there with --reconfig, as the real one does, and give a
# build that stops on a Conf that is not its own tree's.
EDKSETUP = """\
conf="$CONF_PATH/tools_def.txt"
template="$EDK_TOOLS_PATH/Conf/tools_def.template"
reconfig=FALSE
for arg in "$@"; do [ "$arg" = --reconfig ] && reconfig=TRUE; done
[ -e "$conf" ] && [ $reconfig != TRUE ] || cp "$template" "$conf"
build() {
    cmp -s "$conf" "$template" || { echo "Conf is not this tree's"; return 1; }
    "$FAKE_BUILD" "$@"
}
"""

# A disassembly as objdump prints it, with no aliases: an address and a
# colon, a tab, the instruction, a tab, its operands. Lines that are not
# instructions are left out of the count.
DISASSEMBLY = """\

spam.elf:     file format elf64-littleriscv


Disassembly of section .text:

0000000080000000 <__start>:
    80000000:\taddi\ta0,zero,1
    80000004:\tc.addi\ta0,1
    80000006:\taddi\ta1,zero,2
    80000008:\tecall
    8000000c:\tc.addi\ta1,1
    8000000e:\taddi\ta2,zero,3
"""

# A file in a tarball that is to be the fake, runnable.
RUNNABLE = object()


class Link(NamedTuple):
    """A symbolic link in a tarball, and what it points to."""

    to: str


def load_script():
    spec = importlib.util.spec_from_file_location("build", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILD = load_script()


@pytest.fixture
def firmware(tmp_path):
    made = Firmware(tmp_path)
    made.repository()
    made.upstream()
    return made


# The SDK, and its LLVM.


def test_with_no_sdk_the_sdk_is_fetched_checked_and_unpacked(firmware):
    firmware.sdk_release()

    result = firmware.run("sdk")

    assert result.returncode == 0, result.stdout
    assert (firmware.sdk / "sdk_version").exists()
    gcc = firmware.sdk / "gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-gcc"
    assert os.access(gcc, os.X_OK)


def test_a_download_whose_checksum_is_wrong_stops_the_fetch_unpacking_none(
    firmware,
):
    firmware.sdk_release(corrupt="gnu")

    result = firmware.run("sdk")

    assert result.returncode == 1
    assert firmware.sdk_file("gnu") in result.stdout
    assert not firmware.sdk.exists()


def test_with_the_sdk_there_nothing_is_fetched(firmware):
    firmware.sdk_release()
    firmware.run("sdk")
    firmware.forget_calls()

    result = firmware.run("sdk")

    assert result.returncode == 0, result.stdout
    assert firmware.calls("curl") == []


def test_a_fetch_that_stops_while_unpacking_leaves_no_sdk_behind(firmware):
    firmware.sdk_release(cut_short="gnu")

    result = firmware.run("sdk")

    assert result.returncode == 1
    assert not firmware.sdk.exists()


def test_llvm_is_fetched_beside_the_sdk_and_not_in_it(firmware):
    firmware.sdk_release()

    result = firmware.run("llvm")

    assert result.returncode == 0, result.stdout
    assert os.access(firmware.llvm / "bin" / "clang", os.X_OK)
    assert not firmware.sdk.exists()


def test_another_machines_toolchains_are_left_and_this_ones_fetched_beside_them(
    firmware,
):
    # 🎓 A Mac's build/firmware is shared with the Linux of Docker's
    # container, which builds the kernel there.
    firmware.host = "macos-aarch64"
    firmware.sdk_release()
    firmware.run("sdk", "llvm")
    macs = [firmware.sdk, firmware.llvm]
    assert all(each.exists() for each in macs)
    firmware.host = HOST
    firmware.sdk_release()

    result = firmware.run("sdk", "llvm")

    assert result.returncode == 0, result.stdout
    gcc = firmware.sdk / "gnu/riscv64-zephyr-elf/bin/riscv64-zephyr-elf-gcc"
    assert os.access(gcc, os.X_OK)
    assert os.access(firmware.llvm / "bin" / "clang", os.X_OK)
    assert all(each.exists() for each in macs)


# The boot ROM, and the payload of ours for OpenSBI.


def test_the_rom_is_built_for_each_kind_of_cpu_and_the_payload_for_rv64(
    firmware,
):
    firmware.sdk_release()

    result = firmware.run("rom")

    assert result.returncode == 0, result.stdout
    compiled = firmware.compiled()
    assert set(compiled) == {"rom_rv64", "rom_rv32", "sbi_payload"}
    for image, march, mabi in (
        ("rom_rv64", "-march=rv64imac_zicsr", "-mabi=lp64"),
        ("rom_rv32", "-march=rv32imac_zicsr", "-mabi=ilp32"),
        ("sbi_payload", "-march=rv64imac_zicsr", "-mabi=lp64"),
    ):
        assert march in compiled[image]
        assert mabi in compiled[image]
        assert (firmware.out / f"{image}.bin").exists(), image


def test_the_linker_script_is_given_to_gcc_itself_not_to_the_linker(
    firmware,
):
    firmware.sdk_release()

    firmware.run("rom")

    rom = firmware.compiled()["rom_rv64"]
    assert rom[rom.index("-T") + 1].endswith("firmware/rom/rom.ld")
    assert not any(arg.startswith("-Wl,-T") for arg in rom)


# OpenSBI.


def test_opensbi_is_built_with_the_sdks_llvm(firmware):
    firmware.sdk_release()

    result = firmware.run("opensbi")

    assert result.returncode == 0, result.stdout
    (make,) = firmware.calls("make")
    assert f"LLVM={firmware.llvm}/bin/" in make["args"]
    for image in ("fw_jump", "test_payload"):
        for kind in ("elf", "bin"):
            assert (firmware.out / f"{image}.{kind}").exists()


def test_opensbi_is_linked_to_start_at_the_hosts_ram(firmware):
    firmware.sdk_release()

    firmware.run("opensbi")

    (make,) = firmware.calls("make")
    # Where the host's RAM starts (python/socpuppet/boards/host.py).
    assert "FW_TEXT_START=0x80000000" in make["args"]


@pytest.mark.parametrize("part", ["opensbi", "edk2"])
def test_a_part_is_built_in_this_machines_folder(firmware, part):
    # 🎓 Each is compiled by this machine's LLVM, and a Mac's build/firmware
    # is shared with the Linux of Docker's container.
    firmware.sdk_release()

    result = firmware.run(part)

    assert result.returncode == 0, result.stdout
    built = f"build_{part}"
    assert any((firmware.machine / built).rglob("*"))
    assert not (firmware.out / built).exists()


def test_edk2s_tree_is_in_this_machines_folder_as_it_compiles_its_tools_there(
    firmware,
):
    # 🎓 EDK2's BaseTools are compiled inside its tree, by this machine's
    # own compiler, and a Mac's build/firmware is shared with the Linux of
    # Docker's container.
    firmware.sdk_release()

    result = firmware.run("edk2")

    assert result.returncode == 0, result.stdout
    assert (firmware.machine / "edk2" / "edksetup.sh").exists()
    assert not (firmware.out / "edk2").exists()


@pytest.mark.parametrize("part", ["opensbi", "edk2"])
def test_a_patch_that_changes_is_the_one_built_and_alone(firmware, part):
    firmware.sdk_release()
    patch = firmware.root / "cmake" / "patches" / f"{part}-spam.patch"
    firmware.run(part)

    patch.write_text("eggs\n")
    result = firmware.run(part)

    assert result.returncode == 0, result.stdout
    assert (firmware.tree(part) / "PATCHED").read_text() == "eggs\n"


@pytest.mark.parametrize(
    ("part", "tree"),
    [("opensbi", "opensbi"), ("edk2", "edk2"), ("zephyr-tree", "zephyr")],
)
def test_a_tree_pinned_anew_is_cloned_afresh_at_its_tag(firmware, part, tree):
    firmware.sdk_release()
    firmware.run(part)
    firmware.pin(tree, "spam")

    result = firmware.run(part)

    assert result.returncode == 0, result.stdout
    assert (firmware.tree(tree) / ".git" / "TAG").read_text() == "spam"


@pytest.mark.parametrize(
    ("part", "tree"),
    [("opensbi", "opensbi"), ("edk2", "edk2"), ("zephyr-tree", "zephyr")],
)
def test_a_tree_at_its_pinned_tag_is_kept(firmware, part, tree):
    firmware.sdk_release()
    firmware.run(part)
    kept = firmware.tree(tree) / "spam"
    kept.write_text("eggs")

    result = firmware.run(part)

    assert result.returncode == 0, result.stdout
    assert kept.read_text() == "eggs"


# Zephyr's tree.


def test_a_zephyr_patch_that_changes_is_the_one_built_and_alone(firmware):
    patch = firmware.root / "cmake" / "patches" / "zephyr-spam.patch"
    firmware.run("zephyr-tree")

    patch.write_text("eggs\n")
    result = firmware.run("zephyr-tree")

    assert result.returncode == 0, result.stdout
    assert (firmware.out / "zephyr" / "PATCHED").read_text() == "eggs\n"


def test_zephyrs_tree_is_cloned_at_its_tag_with_a_venv_and_a_workspace(
    firmware,
):
    result = firmware.run("zephyr-tree")

    assert result.returncode == 0, result.stdout
    (clone,) = [c for c in firmware.calls("git") if "clone" in c["args"]]
    assert firmware.versions["zephyr"] in clone["args"]
    assert os.access(firmware.machine / "venv" / "bin" / "cmake", os.X_OK)
    assert (firmware.out / ".west").is_dir()


def test_a_venv_whose_cmake_runs_is_kept_and_one_whose_does_not_is_made_again(
    firmware,
):
    firmware.run("zephyr-tree")
    firmware.forget_calls()

    firmware.run("zephyr-tree")
    assert firmware.venvs_made() == 0
    assert firmware.calls("west") == []

    (firmware.machine / "venv" / "bin" / "cmake").unlink()
    firmware.run("zephyr-tree")
    assert firmware.venvs_made() == 1


def test_zephyrs_venv_has_what_twister_needs(firmware):
    firmware.run("zephyr-tree")

    (install,) = [
        c for c in firmware.calls("uv") if c["args"][:2] == ["pip", "install"]
    ]
    requirements = [
        Path(install["args"][i + 1]).name
        for i, arg in enumerate(install["args"])
        if arg == "--requirement"
    ]
    assert TWISTER_REQUIREMENTS.name in requirements


# Zephyr's images.


def test_each_image_is_configured_for_its_board_and_shield_with_our_module(
    firmware,
):
    firmware.sdk_release()

    result = firmware.run("zephyr")

    assert result.returncode == 0, result.stdout
    configures = [
        c["args"] for c in firmware.calls("cmake") if "-S" in c["args"]
    ]
    assert len(configures) == len(BUILD.IMAGES)
    module = firmware.root / "python" / "socpuppet" / "zephyr_module"
    for image in BUILD.IMAGES:
        (args,) = [
            a
            for a in configures
            if Path(a[a.index("-B") + 1]).name == f"build_{name_of(image)}"
        ]
        assert f"-DBOARD={image.board}" in args
        assert args[args.index("-S") + 1].endswith(image.application)
        assert f"-DZEPHYR_EXTRA_MODULES={module}" in args
        if image.shield:
            assert f"-DSHIELD={image.shield}" in args
        for option in image.options:
            assert f"-D{option}" in args
        if image.overlay:
            overlay = firmware.root / image.overlay
            assert f"-DEXTRA_DTC_OVERLAY_FILE={overlay}" in args
        for kind in ("elf", "bin", "opcodes.txt"):
            assert (firmware.out / f"{name_of(image)}.{kind}").exists()


def test_an_image_is_built_in_this_machines_folder(firmware):
    # 🎓 A Mac's build/firmware is shared with the Linux of Docker's
    # container, and what each compiles is its own.
    firmware.sdk_release()

    result = firmware.run("zephyr")

    assert result.returncode == 0, result.stdout
    for image in BUILD.IMAGES:
        build = f"build_{name_of(image)}"
        assert (firmware.machine / build / "zephyr" / "zephyr.elf").exists()
        assert not (firmware.out / build).exists()


def test_an_image_built_before_with_another_sdk_is_configured_afresh(firmware):
    # 🎓 Zephyr keeps where it found the SDK in a build directory's cache,
    # and looks there again: an SDK that has moved since is not found.
    firmware.sdk_release()
    image = BUILD.IMAGES[0]
    firmware.configured_before(image, sdk=firmware.out / firmware.sdk.name)

    result = firmware.run("zephyr")

    assert result.returncode == 0, result.stdout
    assert "--fresh" in firmware.configure_of(image)


def test_an_image_built_before_with_this_sdk_keeps_its_configuration(firmware):
    firmware.sdk_release()
    image = BUILD.IMAGES[0]
    firmware.configured_before(image, sdk=firmware.sdk)

    result = firmware.run("zephyr")

    assert result.returncode == 0, result.stdout
    assert "--fresh" not in firmware.configure_of(image)


def test_an_image_never_built_is_configured_with_nothing_to_start_afresh(
    firmware,
):
    firmware.sdk_release()

    result = firmware.run("zephyr")

    assert result.returncode == 0, result.stdout
    assert "--fresh" not in firmware.configure_of(BUILD.IMAGES[0])


def test_the_opcodes_file_counts_each_instruction_most_used_first(firmware):
    firmware.sdk_release()

    firmware.run("zephyr")

    for image in BUILD.IMAGES:
        opcodes = firmware.out / f"{name_of(image)}.opcodes.txt"
        assert opcodes.read_text() == "3 addi\n2 c.addi\n1 ecall\n"


def test_images_are_built_as_many_at_a_time_as_asked(firmware):
    firmware.sdk_release()

    firmware.run("zephyr", "-j", "2", SLOW_ON="--build")

    builds = [c for c in firmware.calls("cmake") if c["args"][0] == "--build"]
    assert most_at_once(builds) == 2


def test_an_image_that_fails_stops_the_images_not_yet_started(firmware):
    firmware.sdk_release()
    first = BUILD.IMAGES[0]

    result = firmware.run("zephyr", "-j", "1", FAIL_ON=f"-DBOARD={first.board}")

    assert result.returncode == 1
    configures = [c for c in firmware.calls("cmake") if "-S" in c["args"]]
    assert len(configures) == 1


# Linux.


def test_the_kernel_is_fetched_at_its_pin_checked_and_built_with_the_sdks_llvm(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release(version="6.18.57")
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    (fetch,) = [
        c
        for c in firmware.calls("curl")
        if Path(c["args"][-1]).name.startswith("linux-")
    ]
    assert fetch["args"][-1].endswith("/v6.x/linux-6.18.57.tar.xz")
    makes = [
        c["args"] for c in firmware.calls("make") if "ARCH=riscv" in c["args"]
    ]
    (configure,) = [m for m in makes if "defconfig" in m]
    (build,) = [m for m in makes if "Image" in m]
    for args in (configure, build):
        assert f"LLVM={firmware.llvm}/bin/" in args
    assert "defconfig" in configure
    assert "Image" in build
    assert (firmware.out / "linux.bin").read_text() == "Image"
    assert (firmware.out / "linux.elf").exists()
    assert (firmware.out / "linux.map").read_text().endswith("T _start\n")


def test_the_kernels_two_nvme_modules_are_built_after_its_image_the_same_way(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    makes = [
        c["args"] for c in firmware.calls("make") if "ARCH=riscv" in c["args"]
    ]
    (configure,) = [m for m in makes if "defconfig" in m]
    (build,) = [m for m in makes if "Image" in m]
    (modules,) = [m for m in makes if any(a.endswith(".ko") for a in m)]
    assert {a for a in modules if a.endswith(".ko")} == {
        "drivers/nvme/host/nvme-core.ko",
        "drivers/nvme/host/nvme.ko",
    }
    assert "Image" not in modules
    assert makes.index(build) < makes.index(modules)
    assert set(configure) - {"defconfig"} <= set(modules)


def test_a_kernel_pinned_anew_is_fetched_and_built_from_its_own_source(
    firmware,
):
    firmware.sdk_release()
    firmware.alpine_release()
    firmware.linux_release(version="6.18.57")
    firmware.run("linux")
    firmware.forget_calls()
    firmware.linux_release(version="6.18.58")

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    (fetch,) = [
        c
        for c in firmware.calls("curl")
        if Path(c["args"][-1]).name.startswith("linux-")
    ]
    assert fetch["args"][-1].endswith("/linux-6.18.58.tar.xz")
    sources = {
        Path(args[args.index("-C") + 1])
        for args in (
            c["args"]
            for c in firmware.calls("make")
            if "ARCH=riscv" in c["args"]
        )
    }
    assert [(source / "Makefile").read_text() for source in sources] == [
        "VERSION = 6.18.58\n"
    ]
    assert (firmware.machine / "linux-6.18.57" / "Makefile").exists()


def test_the_root_filesystem_is_alpines_minirootfs_with_our_inittab_in_ext4(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    files = inside(firmware.out / "rootfs.ext4")
    assert files["etc/inittab"].data == b"spam\n"
    assert files["etc/profile"].data == b"PS1=spam\n"
    assert files["sbin/init"].link == "/bin/busybox"


#: What ssh to the guest needs of Alpine's packages: dropbear, the libraries
#: it needs that the mini root has not, and OpenSSH's SFTP server, which
#: OpenSSH's scp speaks to.
SSH_PACKAGES = ("dropbear", "utmps-libs", "skalibs-libs", "openssh-sftp-server")


def test_the_root_filesystem_has_alpines_packages_for_ssh_fetched_at_their_pins(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release(version="3.23.4", package_version="1.0-r0")

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    fetched = [c["args"][-1] for c in firmware.calls("curl")]
    for package in SSH_PACKAGES:
        assert (
            "https://dl-cdn.alpinelinux.org/alpine/v3.23/main/riscv64/"
            f"{package}-1.0-r0.apk"
        ) in fetched
    files = inside(firmware.out / "rootfs.ext4")
    for package in SSH_PACKAGES:
        assert files[f"usr/lib/{package}"].data == b"spam\n"


def test_the_root_filesystem_leaves_out_what_a_package_says_of_itself(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    files = inside(firmware.out / "rootfs.ext4")
    assert [n for n in files if n.startswith((".PKGINFO", ".SIGN."))] == []


def test_a_package_whose_checksum_is_wrong_stops_the_build_making_no_image(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release(corrupt_package="dropbear")

    result = firmware.run("linux")

    assert result.returncode == 1
    (complaint,) = [
        line for line in result.stdout.splitlines() if "'s SHA-256 is " in line
    ]
    assert "dropbear-" in complaint
    assert not (firmware.out / "rootfs.ext4").exists()


def test_a_package_alpine_no_longer_has_stops_the_build_saying_to_pin_its_newest(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release(missing_package="dropbear")

    result = firmware.run("linux")

    assert result.returncode == 1
    assert "keeps only the newest build of each package" in result.stdout
    assert "dropbear" in result.stdout
    assert not (firmware.out / "rootfs.ext4").exists()


def test_the_root_filesystem_leaves_alpines_unpacked_tree_as_alpine_made_it(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    (alpines,) = firmware.out.glob("alpine-minirootfs-*")
    assert (alpines / "etc/inittab").read_text() == (
        "::sysinit:/sbin/openrc sysinit\n"
    )


def test_the_initramfs_is_made_by_the_kernels_own_tool_with_busybox_musl_nvme(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release(version="6.18.57")
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    listed = archived(firmware.out / "initramfs.cpio")
    assert listed["/bin/busybox"].data == firmware.fake.read_text()
    assert listed["/bin/sh"].to == "busybox"
    assert listed["/lib/ld-musl-riscv64.so.1"].data == "musl\n"
    assert listed["/lib/libc.musl-riscv64.so.1"].to == "ld-musl-riscv64.so.1"
    modules = "/lib/modules/6.18.57/kernel/drivers/nvme/host"
    for module in ("nvme-core.ko", "nvme.ko"):
        assert listed[f"{modules}/{module}"].data == (
            f"drivers/nvme/host/{module}"
        )
    assert listed["/dev/console"].device == "c 5 1"


def test_the_initramfs_has_our_files_at_their_paths_with_their_modes(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    listed = archived(firmware.out / "initramfs.cpio")
    assert listed["/init"].data == "spam\n"
    assert listed["/init"].mode == "0755"
    assert listed["/etc/spam"].data == "spam\n"
    assert listed["/etc/spam"].mode == "0644"


def test_every_entry_of_the_initramfs_comes_after_its_folder(firmware):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run("linux")

    assert result.returncode == 0, result.stdout
    listed = archived(firmware.out / "initramfs.cpio")
    names = list(listed)
    for name in names:
        parent = str(Path(name).parent)
        if parent != "/":
            assert listed[parent].kind == "dir", name
            assert names.index(parent) < names.index(name), name


class Listed(NamedTuple):
    """An entry of a fake initramfs: what kind it is, a file's text, a
    link's target, a node's type and numbers, and its mode."""

    kind: str
    data: str | None
    to: str | None
    device: str | None
    mode: str


def archived(cpio):
    """The entries of a fake initramfs, by name, in the order listed."""
    entries = {}
    for line in cpio.read_text().splitlines():
        entry = json.loads(line)
        name = entry.pop("name")
        entries[name] = Listed(**entry)
    return entries


class Entry(NamedTuple):
    """A file of a fake image: its bytes, or what it is a link to."""

    data: bytes | None = None
    link: str | None = None


def inside(image):
    """The files of a fake image, by name.

    The fake mkfs.ext4 tars the tree it is given, naming each file "./..."
    as shutil.make_archive does; the names here have that stripped.
    """
    with tarfile.open(image) as archive:
        return {
            Path(member.name).as_posix(): Entry(
                data=archive.extractfile(member).read()
                if member.isfile()
                else None,
                link=member.linkname if member.issym() else None,
            )
            for member in archive
        }


def test_a_root_whose_checksum_is_wrong_stops_the_fetch_making_no_image(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release(corrupt=True)

    result = firmware.run("linux")

    assert result.returncode == 1
    assert "alpine-minirootfs" in result.stdout
    assert not (firmware.out / "rootfs.ext4").exists()


def test_a_kernel_whose_checksum_is_wrong_stops_the_fetch_unpacking_none(
    firmware,
):
    firmware.sdk_release()
    firmware.linux_release(corrupt=True)

    result = firmware.run("linux")

    assert result.returncode == 1
    assert "linux-" in result.stdout
    assert "versions.toml" in result.stdout
    assert list(firmware.machine.glob("linux-*")) == []
    assert firmware.calls("make") == []


# EDK2, and a part that fails.


def test_edk2_is_built_with_its_submodules_and_its_fd_kept(firmware):
    firmware.sdk_release()

    result = firmware.run("edk2")

    assert result.returncode == 0, result.stdout
    git = [call["args"] for call in firmware.calls("git")]
    assert any("submodule" in args for args in git)
    (build,) = firmware.calls("build")
    assert "RISCV64" in build["args"]
    assert (firmware.out / "uefi.fd").read_text() == "uefi"


def test_edk2s_shell_is_kept_as_a_program_a_disk_can_boot(firmware):
    # 🎓 UEFI's shell, as a file: what a server's removable disk can boot,
    # to run a startup.nsh that starts a kernel with what it is to be told.
    firmware.sdk_release()

    result = firmware.run("edk2")

    assert result.returncode == 0, result.stdout
    assert (firmware.out / "uefi_shell.efi").read_text() == "shell"


def test_edk2_is_built_with_no_conf_an_earlier_build_left(firmware):
    # 🎓 EDK2's setup copies its Conf templates only where there are none,
    # so one left by a tree at an earlier tag would be built with.
    firmware.sdk_release()
    firmware.run("edk2")
    (firmware.machine / "build_edk2" / "Conf" / "tools_def.txt").write_text(
        "spam\n"
    )

    result = firmware.run("edk2")

    assert result.returncode == 0, result.stdout


def test_linux_without_bc_stops_before_anything_is_fetched(firmware):
    firmware.sdk_release()
    firmware.linux_release()
    (firmware.bin / "bc").unlink()

    result = firmware.run("rom", "linux", PATH=firmware.path_without("bc"))

    assert result.returncode == 1
    assert "bc" in result.stdout
    assert firmware.calls("curl") == []


def test_edk2_without_iasl_stops_before_anything_is_fetched(firmware):
    firmware.sdk_release()
    (firmware.bin / "iasl").unlink()

    result = firmware.run("rom", "edk2", PATH=firmware.path_without("iasl"))

    assert result.returncode == 1
    assert "iasl" in result.stdout
    assert firmware.calls("curl") == []


def test_a_part_that_fails_shows_how_its_log_ends_and_stops_the_build(
    firmware,
):
    firmware.sdk_release()

    result = firmware.run("opensbi", "zephyr", FAIL_ON="PLATFORM=generic")

    assert result.returncode == 1
    assert "build_opensbi.log" in result.stdout
    # The last forty lines of the fifty, and none before them.
    assert "spam 50" in result.stdout
    assert "spam 10\n" not in result.stdout
    assert firmware.calls("cmake") == []


# In Docker, and all of it.


def test_in_docker_the_same_build_runs_in_the_devcontainers_image(firmware):
    result = firmware.run("--in-docker", "rom", "-j", "3")

    assert result.returncode == 0, result.stdout
    (call,) = firmware.calls("devcontainer.py")
    command = call["args"]
    assert command[:3] == ["python3", "firmware/build.py", "rom"]
    # Into build/firmware, which is its default in the container too.
    assert "--out" not in command
    assert command[command.index("-j") + 1] == "3"
    assert firmware.calls("curl") == []


def test_on_a_mac_the_kernel_builds_in_docker_and_the_other_parts_here():
    assert BUILD.builds_in_docker("linux", "macos-aarch64")
    assert not BUILD.builds_in_docker("rom", "macos-aarch64")
    assert not BUILD.builds_in_docker("linux", "linux-x86_64")


def test_on_an_intel_mac_every_part_builds_in_docker():
    assert all(
        BUILD.builds_in_docker(part, "macos-x86_64") for part in BUILD.PARTS
    )


def test_on_an_apple_silicon_mac_the_kernel_goes_to_docker_and_the_rom_builds_here(
    firmware,
):
    firmware.host = "macos-aarch64"
    firmware.sdk_release()

    result = firmware.run("rom", "linux")

    assert result.returncode == 0, result.stdout
    assert set(firmware.compiled()) == {"rom_rv64", "rom_rv32", "sbi_payload"}
    (call,) = firmware.calls("devcontainer.py")
    assert call["args"][:3] == ["python3", "firmware/build.py", "linux"]


def test_on_an_intel_mac_every_part_goes_to_docker_in_one_run(firmware):
    firmware.host = "macos-x86_64"

    result = firmware.run("rom", "linux")

    assert result.returncode == 0, result.stdout
    (call,) = firmware.calls("devcontainer.py")
    assert call["args"][:4] == ["python3", "firmware/build.py", "rom", "linux"]
    assert firmware.compiled() == {}


@pytest.mark.parametrize(
    ("host", "args"),
    [
        (HOST, ("--in-docker", "rom", "--out", "build/spam")),
        (HOST, ("--in-docker", "rom", "--out", "{elsewhere}")),
        ("macos-aarch64", ("linux", "--out", "build/spam")),
        ("macos-x86_64", ("rom", "--out", "build/spam")),
    ],
)
def test_in_docker_an_output_directory_other_than_build_firmware_is_refused(
    firmware, tmp_path, host, args
):
    # 🎓 Docker's container is a machine of its own, whose folder in
    # build/firmware tools/devcontainer.py keeps apart from the host's: in
    # another output directory the two would share one.
    firmware.host = host
    elsewhere = str(tmp_path / "elsewhere")

    result = firmware.run(*(arg.format(elsewhere=elsewhere) for arg in args))

    assert result.returncode == 1
    assert "build/firmware" in result.stdout
    assert firmware.calls("devcontainer.py") == []


def test_when_no_part_is_named_every_part_is_built(firmware):
    firmware.sdk_release()
    firmware.linux_release()
    firmware.alpine_release()

    result = firmware.run()

    assert result.returncode == 0, result.stdout
    for image in (
        *("rom_rv64.bin", "fw_jump.elf", "sbi_payload.bin", "uefi.fd"),
        *("linux.bin", "rootfs.ext4"),
    ):
        assert (firmware.out / image).exists(), image
    for image in BUILD.IMAGES:
        assert (firmware.out / f"{name_of(image)}.elf").exists()


class Firmware:
    """The throwaway repository, the downloads, and the log of programs."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "repo"
        self.out = self.root / "build" / "firmware"
        self.downloads = tmp_path / "downloads"
        self.clones = tmp_path / "clones"
        self.bin = tmp_path / "bin"
        self.log = tmp_path / "log"
        self.fake = tmp_path / "fake"
        self.fake.write_text(f"#!{sys.executable}\n{FAKE}")
        self.fake.chmod(0o755)
        self.versions = BUILD.read_versions(VERSIONS)
        self.host = HOST

    def repository(self):
        """The files of the repository the script reads."""
        (self.root / "firmware").mkdir(parents=True)
        for path in (SCRIPT, VERSIONS, TWISTER_REQUIREMENTS):
            shutil.copy(path, self.root / "firmware" / path.name)
        for path in (
            "firmware/rom/start.S",
            "firmware/rom/spam.c",
            "firmware/rom/eggs.c",
            "firmware/rom/rom.ld",
            "firmware/rom/board_rv64.h",
            "firmware/rom/board_rv32.h",
            "firmware/sbi_payload/start.S",
            "firmware/sbi_payload/spam.c",
            "firmware/sbi_payload/payload.ld",
            "firmware/rootfs/etc/inittab",
            "firmware/initramfs/init",
            "firmware/initramfs/etc/spam",
            "python/socpuppet/zephyr_module/zephyr/module.yml",
            "cmake/patches/opensbi-spam.patch",
            "cmake/patches/edk2-spam.patch",
            "cmake/patches/zephyr-spam.patch",
        ):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("spam\n")
        (self.root / "firmware" / "initramfs" / "init").chmod(0o755)
        (self.root / "firmware" / "initramfs" / "etc" / "spam").chmod(0o644)
        self.install(self.root / "tools" / "devcontainer.py")
        for program in (
            *("curl", "git", "make", "uv", "iasl", "build"),
            *("flex", "bison", "bc", "mkfs.ext4"),
        ):
            self.install(self.bin / program)

    @property
    def machine(self):
        """Where the tools of the machine the script is run as go."""
        return self.out / self.host

    def tree(self, name):
        """Where a source tree is: EDK2's, which its build compiles its
        tools into, in this machine's folder, and the others beside the
        images."""
        return (self.machine if name == "edk2" else self.out) / name

    @property
    def sdk(self):
        """Where the Zephyr SDK goes."""
        return self.machine / f"zephyr-sdk-{self.versions['sdk']}"

    @property
    def llvm(self):
        """Where the SDK's LLVM goes."""
        return self.machine / f"llvm-{self.versions['sdk']}"

    def install(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.fake, path)
        path.chmod(0o755)

    def sdk_file(self, kind):
        """The name of one of the SDK's files: "minimal", "gnu" or "llvm"."""
        return {
            "minimal": f"{self.sdk.name}_{self.host}_minimal.tar.xz",
            "gnu": f"toolchain_gnu_{self.host}_riscv64-zephyr-elf.tar.xz",
            "llvm": f"toolchain_llvm_{self.host}.tar.xz",
        }[kind]

    def sdk_release(self, corrupt=None, cut_short=None):
        """Put the SDK's three files and their checksums where curl looks.

        `corrupt` names a file ("gnu", say) whose checksum is to be wrong,
        and `cut_short` one that stops part of the way, as a download that
        failed would, listed with the checksum of what there is of it.
        """
        self.downloads.mkdir(exist_ok=True)
        contents = {
            "minimal": {f"{self.sdk.name}/sdk_version": "1"},
            "gnu": {
                f"riscv64-zephyr-elf/bin/riscv64-zephyr-elf-{tool}": RUNNABLE
                for tool in ("gcc", "objcopy", "objdump")
            },
            "llvm": {"llvm/bin/clang": RUNNABLE},
        }
        sums = []
        for kind, files in contents.items():
            path = self.downloads / self.sdk_file(kind)
            tarball(path, files, self.fake)
            if kind == cut_short:
                path.write_bytes(path.read_bytes()[:200])
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if kind == corrupt:
                digest = "0" * 64
            sums.append(f"{digest}  {path.name}")
        (self.downloads / "sha256.sum").write_text("\n".join(sums) + "\n")

    def linux_release(self, version=None, corrupt=False):
        """Put a kernel's tarball where curl looks, and pin its checksum.

        The version is the repository's pin unless one is given. With
        `corrupt`, the checksum pinned is not the tarball's.
        """
        self.downloads.mkdir(exist_ok=True)
        version = version or self.versions["linux"]
        path = self.downloads / f"linux-{version}.tar.xz"
        tarball(
            path,
            {f"linux-{version}/Makefile": f"VERSION = {version}\n"},
            self.fake,
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.pin("linux", version, "0" * 64 if corrupt else digest)

    def alpine_release(
        self,
        version=None,
        corrupt=False,
        package_version=None,
        corrupt_package=None,
        missing_package=None,
    ):
        """Put Alpine's mini root filesystem where curl looks, and pin it.

        As Alpine's own: busybox, the links to it, and an inittab and a
        profile that ours replaces or keeps. The version is the
        repository's pin unless one is given. With `corrupt`, the checksum
        pinned is not the tarball's. And the packages for ssh, each pinned
        at `package_version` or the repository's own, as Alpine's are: a
        signature, what the package says of itself, and its one file,
        usr/lib/<its name>. With `corrupt_package`, the checksum pinned of
        that one is not its file's, and `missing_package` is pinned and
        not there, as one Alpine has since rebuilt.
        """
        self.downloads.mkdir(exist_ok=True)
        version = version or self.versions["alpine"]
        path = self.downloads / f"alpine-minirootfs-{version}-riscv64.tar.gz"
        tarball(
            path,
            {
                "./bin/busybox": RUNNABLE,
                "./lib/ld-musl-riscv64.so.1": "musl\n",
                "./lib/libc.musl-riscv64.so.1": Link("ld-musl-riscv64.so.1"),
                "./sbin/init": Link("/bin/busybox"),
                "./etc/inittab": "::sysinit:/sbin/openrc sysinit\n",
                "./etc/profile": "PS1=spam\n",
            },
            self.fake,
            compression="gz",
        )
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.pin("alpine", version, "0" * 64 if corrupt else digest)
        pins = BUILD.read_pins(VERSIONS)
        for package in SSH_PACKAGES:
            version = package_version or pins[package]["version"]
            path = self.downloads / f"{package}-{version}.apk"
            tarball(
                path,
                {
                    ".SIGN.RSA.spam@example.org.rsa.pub": "signature\n",
                    ".PKGINFO": f"pkgname = {package}\n",
                    f"usr/lib/{package}": "spam\n",
                },
                self.fake,
                compression="gz",
            )
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.pin(
                package,
                version,
                "0" * 64 if package == corrupt_package else digest,
            )
            if package == missing_package:
                path.unlink()

    def pin(self, name, version, sha256=None):
        """Write one entry of the copy of versions.toml the script reads."""
        versions = self.root / "firmware" / "versions.toml"
        pins = {**BUILD.read_pins(versions), name: {"version": version}}
        if sha256 is not None:
            pins[name]["sha256"] = sha256
        versions.write_text(
            "\n".join(
                f"[{each}]\n"
                + "".join(f'{key} = "{value}"\n' for key, value in pin.items())
                for each, pin in pins.items()
            )
        )

    def upstream(self):
        """What a clone of Zephyr and of EDK2 holds, as far as it matters."""
        zephyr = self.clones / "zephyr" / "scripts" / "requirements-base.txt"
        zephyr.parent.mkdir(parents=True)
        zephyr.write_text("spam\n")
        conf = self.clones / "edk2" / "BaseTools" / "Conf"
        conf.mkdir(parents=True)
        (conf / "tools_def.template").write_text("eggs\n")
        (self.clones / "edk2" / "edksetup.sh").write_text(EDKSETUP)

    def path_without(self, program):
        """The PATH, with the system's own copy of a program hidden."""
        directories = [str(self.bin), *os.environ["PATH"].split(os.pathsep)]
        return os.pathsep.join(
            directory
            for directory in directories
            if not (Path(directory) / program).exists()
        )

    def run(self, *args, **env):
        disassembly = self.log.parent / "disassembly.txt"
        disassembly.write_text(DISASSEMBLY)
        return subprocess.run(
            [
                *(sys.executable, "-c", AS_ON, *MACHINES[self.host]),
                *(str(self.root / "firmware" / "build.py"), *args),
            ],
            cwd=self.root,
            env={
                **os.environ,
                "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                "LOG": str(self.log),
                "FAKE": str(self.fake),
                "FAKE_BUILD": str(self.bin / "build"),
                "DOWNLOADS": str(self.downloads),
                "CLONES": str(self.clones),
                "DISASSEMBLY": str(disassembly),
                **env,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
        )

    def calls(self, name=None):
        """The programs run, in order: [{"name", "args", ...}]."""
        if not self.log.exists():
            return []
        lines = self.log.read_text().splitlines()
        calls = [json.loads(line) for line in lines]
        return [call for call in calls if name in (None, call["name"])]

    def forget_calls(self):
        """Start the log of programs again, after a test's setting up."""
        self.log.unlink()

    def configured_before(self, image, *, sdk):
        """Leave an image's build directory as if configured with `sdk`."""
        build = self.machine / f"build_{name_of(image)}"
        build.mkdir(parents=True)
        (build / "CMakeCache.txt").write_text(
            f"ZEPHYR_SDK_INSTALL_DIR:INTERNAL={sdk}\n"
        )

    def configure_of(self, image):
        """The arguments cmake was given to configure an image's build."""
        build = f"build_{name_of(image)}"
        (configure,) = [
            args
            for args in (call["args"] for call in self.calls("cmake"))
            if "-B" in args and Path(args[args.index("-B") + 1]).name == build
        ]
        return configure

    def compiled(self):
        """What the SDK's gcc compiled: {image's name: gcc's arguments}."""
        return {
            Path(call["args"][call["args"].index("-o") + 1]).stem: call["args"]
            for call in self.calls("riscv64-zephyr-elf-gcc")
        }

    def venvs_made(self):
        return len([c for c in self.calls("uv") if c["args"][0] == "venv"])


def tarball(path, contents, fake, compression="xz"):
    """A tarball at `path` of {name: text, RUNNABLE for the fake, or a Link}."""
    with tarfile.open(path, f"w:{compression}") as archive:
        for name, text in contents.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            if isinstance(text, Link):
                info.type = tarfile.SYMTYPE
                info.linkname = text.to
                archive.addfile(info)
                continue
            data = fake.read_bytes() if text is RUNNABLE else text.encode()
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def name_of(image):
    """What an image's files are called: <application>_<board>."""
    return f"{image.name or Path(image.application).name}_{image.board}"


def most_at_once(calls):
    """The most of the calls that were running at any one moment."""
    return max(
        sum(1 for b in calls if b["start"] <= a["start"] < b["end"])
        for a in calls
    )
