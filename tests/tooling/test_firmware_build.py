"""firmware/build.py, which fetches the firmware's toolchains and builds it.

The script is run for real in a throwaway copy of what it reads, with a
stand-in for each program it runs: curl, git, make, uv, iasl and the SDK's
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

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "firmware" / "build.py"
VERSIONS = REPO / "firmware" / "versions.toml"
TWISTER_REQUIREMENTS = REPO / "firmware" / "twister-requirements.txt"

# The stand-in for every program. Each logs its name and arguments, as
# JSON, with when it started and ended. What it then does depends on which
# program it is standing in for. FAIL_ON names a word, and a command that
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


def stand_in(path):
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
    url, directory = args[-2], args[-1]
    template = os.path.join(os.environ["CLONES"], os.path.basename(url))
    if os.path.isdir(template):
        shutil.copytree(template, directory)
    os.makedirs(os.path.join(directory, ".git"), exist_ok=True)
elif name == "git" and "apply" in args:
    # A tree's patches are kept in one file of it, PATCHED, in the order
    # they were applied; checking the tree out again throws them away.
    with open(os.path.join(after("-C"), "PATCHED"), "a") as patched:
        patched.write(open(args[-1]).read())
elif name == "git" and "checkout" in args:
    patched = os.path.join(after("-C"), "PATCHED")
    if os.path.exists(patched):
        os.remove(patched)
elif name == "make" and any(a.startswith("O=") for a in args):
    built = next(a[2:] for a in args if a.startswith("O="))
    for each in ("fw_jump", "payloads/test"):
        for kind in ("elf", "bin"):
            elf(f"{built}/platform/generic/firmware/{each}.{kind}")
elif name == "uv" and args[0] == "venv":
    stand_in(os.path.join(args[-1], "bin", "python"))
elif name == "uv" and args[:2] == ["pip", "install"]:
    venv = os.path.dirname(os.path.dirname(after("--python")))
    for program in ("cmake", "west"):
        stand_in(os.path.join(venv, "bin", program))
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
elif name == "build":
    write(
        os.path.join(
            os.environ["WORKSPACE"],
            "Build/RiscVVirtQemu/DEBUG_CLANGDWARF/FV/RISCV_VIRT_CODE.fd",
        ),
        "uefi",
    )
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
EDKSETUP = 'build() { "$FAKE_BUILD" "$@"; }\n'

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

# A file in a tarball that is to be the stand-in, runnable.
RUNNABLE = object()


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
    llvm = firmware.out / f"llvm-{firmware.versions['sdk']}"
    assert os.access(llvm / "bin" / "clang", os.X_OK)
    assert not firmware.sdk.exists()


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
    llvm = firmware.out / f"llvm-{firmware.versions['sdk']}"
    assert f"LLVM={llvm}/bin/" in make["args"]
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
def test_a_patch_that_changes_is_the_one_built_and_alone(firmware, part):
    firmware.sdk_release()
    patch = firmware.root / "cmake" / "patches" / f"{part}-spam.patch"
    firmware.run(part)

    patch.write_text("eggs\n")
    result = firmware.run(part)

    assert result.returncode == 0, result.stdout
    assert (firmware.out / part / "PATCHED").read_text() == "eggs\n"


# Zephyr's tree.


def test_zephyrs_tree_is_cloned_at_its_tag_with_a_venv_and_a_workspace(
    firmware,
):
    result = firmware.run("zephyr-tree")

    assert result.returncode == 0, result.stdout
    (clone,) = [c for c in firmware.calls("git") if "clone" in c["args"]]
    assert firmware.versions["zephyr"] in clone["args"]
    assert os.access(firmware.out / "venv" / "bin" / "cmake", os.X_OK)
    assert (firmware.out / ".west").is_dir()


def test_a_venv_whose_cmake_runs_is_kept_and_one_whose_does_not_is_made_again(
    firmware,
):
    firmware.run("zephyr-tree")
    firmware.forget_calls()

    firmware.run("zephyr-tree")
    assert firmware.venvs_made() == 0
    assert firmware.calls("west") == []

    (firmware.out / "venv" / "bin" / "cmake").unlink()
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
            if f"-DBOARD={image.board}" in a
            and a[a.index("-S") + 1].endswith(image.application)
        ]
        assert f"-DZEPHYR_EXTRA_MODULES={module}" in args
        if image.shield:
            assert f"-DSHIELD={image.shield}" in args
        for kind in ("elf", "bin", "opcodes.txt"):
            assert (firmware.out / f"{name_of(image)}.{kind}").exists()


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
    assert command[command.index("--out") + 1] == "/workspace/build/firmware"
    assert command[command.index("-j") + 1] == "3"
    assert firmware.calls("curl") == []


def test_in_docker_an_output_directory_outside_the_repository_is_refused(
    firmware, tmp_path
):
    result = firmware.run("--in-docker", "--out", str(tmp_path / "elsewhere"))

    assert result.returncode == 1
    assert "outside the repository" in result.stdout
    assert firmware.calls("devcontainer.py") == []


def test_when_no_part_is_named_every_part_is_built(firmware):
    firmware.sdk_release()

    result = firmware.run()

    assert result.returncode == 0, result.stdout
    for image in ("rom_rv64.bin", "fw_jump.elf", "sbi_payload.bin", "uefi.fd"):
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
        self.host = BUILD.sdk_host()
        self.sdk = self.out / f"zephyr-sdk-{self.versions['sdk']}"

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
            "python/socpuppet/zephyr_module/zephyr/module.yml",
            "cmake/patches/opensbi-spam.patch",
            "cmake/patches/edk2-spam.patch",
        ):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("spam\n")
        self.install(self.root / "tools" / "devcontainer.py")
        for program in ("curl", "git", "make", "uv", "iasl", "build"):
            self.install(self.bin / program)

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

    def upstream(self):
        """What a clone of Zephyr and of EDK2 holds, as far as it matters."""
        zephyr = self.clones / "zephyr" / "scripts" / "requirements-base.txt"
        zephyr.parent.mkdir(parents=True)
        zephyr.write_text("spam\n")
        (self.clones / "edk2").mkdir(parents=True)
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
            [sys.executable, str(self.root / "firmware" / "build.py"), *args],
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

    def compiled(self):
        """What the SDK's gcc compiled: {image's name: gcc's arguments}."""
        return {
            Path(call["args"][call["args"].index("-o") + 1]).stem: call["args"]
            for call in self.calls("riscv64-zephyr-elf-gcc")
        }

    def venvs_made(self):
        return len([c for c in self.calls("uv") if c["args"][0] == "venv"])


def tarball(path, contents, fake):
    """A .tar.xz at `path` of {name: text, or RUNNABLE for the stand-in}."""
    with tarfile.open(path, "w:xz") as archive:
        for name, text in contents.items():
            data = fake.read_bytes() if text is RUNNABLE else text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))


def name_of(image):
    """What an image's files are called: <application>_<board>."""
    return f"{Path(image.application).name}_{image.board}"


def most_at_once(calls):
    """The most of the calls that were running at any one moment."""
    return max(
        sum(1 for b in calls if b["start"] <= a["start"] < b["end"])
        for a in calls
    )
