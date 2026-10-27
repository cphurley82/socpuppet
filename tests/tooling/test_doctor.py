"""tools/doctor.py, which checks this machine for socpuppet's development.

The doctor is run for real, with a path of fakes for every program it
looks for. Each fake writes the command it was given to a log, and the
tests take a program away, or make one fail, to give the machine a problem.
"""

import ctypes.util
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "tools" / "doctor.py"

# A program that logs its command line and exits 0, unless FAIL_ON names a
# word of the command, when it says so on its error output and exits 1. It
# takes as many seconds as SLOW says.
FAKE = """\
import os, sys, time
command = " ".join([os.path.basename(sys.argv[0]), *sys.argv[1:]])
with open(os.environ["LOG"], "a") as log:
    log.write(command + "\\n")
time.sleep(float(os.environ.get("SLOW", "0")))
if os.environ.get("FAIL_ON", "@") in command.split():
    print("spam: no eggs", file=sys.stderr)
    sys.exit(1)
"""


def load_doctor():
    """tools/doctor.py as a module, for what its tables say."""
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOCTOR_MODULE = load_doctor()
AREAS = DOCTOR_MODULE.AREAS
# The kernel the fake machine runs, unless a test says otherwise.
RELEASE = "7.0.0-38-generic"
# What QBox's build needs, as tools/build_qbox.py lists it for the doctor.
QBOX = DOCTOR_MODULE.BUILD_QBOX

# Every program the doctor looks for, each of which the machine has unless
# a test takes it away.
PROGRAMS = (
    *("git", "c++", "dtc", "curl", "make", "iasl", "docker"),
    *("flex", "bison", "bc", "mkfs.ext4"),
    *(name for name, _, _ in QBOX.PROGRAMS),
    "pkgutil",
    "sudo",
    *(name for name, _ in DOCTOR_MODULE.PCIEM_GUEST.PROGRAMS),
    *("ssh", "scp"),
)

# The package of python.org's CPython that cibuildwheel looks for on a Mac,
# of the Python the tools are pinned to: named for its minor version.
PYTHON = (REPO / ".python-version").read_text().strip()
MINOR = ".".join(PYTHON.split(".")[:2])
PYTHON_ORG = f"org.python.Python.PythonFramework-{MINOR}"

# pkgutil, which lists the packages of the machine: python.org's CPython
# among them unless PACKAGES says what else there is.
PKGUTIL = f"""\
import os
print(os.environ.get("PACKAGES", "{PYTHON_ORG}"))
"""


@pytest.fixture
def doctor(tmp_path):
    """Run the doctor with the fakes; returns run(*args, **env).

    run returns the finished process. run.without(program) takes a program
    off the path, and run.lines() are the commands the fakes were given.
    The files the doctor looks at, in /proc, /sys, /dev, /boot and /lib,
    are a Linux's running RELEASE with pciem loaded, KVM, and the kernel
    and its headers, unless a test changes them with run.runs_kernel,
    run.unload_pciem, run.lock_pciems_device, run.is_not_linux,
    run.hides_the_kernel, run.locks_kvm or run.lacks_kernel_headers.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    for program in PROGRAMS:
        path = bin_directory / program
        path.write_text(
            f"#!{sys.executable}\n{PKGUTIL if program == 'pkgutil' else FAKE}"
        )
        path.chmod(0o755)
    log = tmp_path / "log"
    machine = tmp_path / "machine"
    (machine / "proc/sys/kernel").mkdir(parents=True)
    (machine / "proc/sys/kernel/osrelease").write_text(f"{RELEASE}\n")
    (machine / "sys/module/pciem").mkdir(parents=True)
    (machine / "dev").mkdir()
    (machine / "dev/pciem").write_text("")
    (machine / "dev/kvm").write_text("")
    (machine / "boot").mkdir()
    (machine / f"boot/vmlinuz-{RELEASE}").write_text("")
    headers = machine / f"lib/modules/{RELEASE}/build"
    headers.mkdir(parents=True)
    (headers / "Makefile").write_text("")

    def run(*args, **env):
        return subprocess.run(
            [sys.executable, str(DOCTOR), "--root", str(machine), *args],
            env={
                **os.environ,
                "PATH": str(bin_directory),
                "LOG": str(log),
                **env,
            },
            capture_output=True,
            text=True,
        )

    def without(program):
        (bin_directory / program).unlink()

    def lines():
        return log.read_text().splitlines() if log.exists() else []

    def runs_kernel(release):
        (machine / "proc/sys/kernel/osrelease").write_text(release + "\n")

    def unload_pciem():
        (machine / "sys/module/pciem").rmdir()
        (machine / "dev/pciem").unlink()

    def lock_pciems_device():
        (machine / "dev/pciem").chmod(0o444)

    def is_not_linux():
        # A Mac: no /proc, /sys, /boot or /lib, and a /dev with no pciem
        # or KVM in it.
        for directory in ("proc", "sys", "boot", "lib"):
            shutil.rmtree(machine / directory)
        (machine / "dev/pciem").unlink()
        (machine / "dev/kvm").unlink()

    def hides_the_kernel():
        # Unreadable, as Ubuntu's is to all but root.
        (machine / f"boot/vmlinuz-{RELEASE}").chmod(0)

    def locks_kvm():
        (machine / "dev/kvm").chmod(0)

    def lacks_kernel_headers():
        shutil.rmtree(machine / f"lib/modules/{RELEASE}/build")

    run.without = without
    run.hides_the_kernel = hides_the_kernel
    run.locks_kvm = locks_kvm
    run.lacks_kernel_headers = lacks_kernel_headers
    run.lines = lines
    run.runs_kernel = runs_kernel
    run.unload_pciem = unload_pciem
    run.lock_pciems_device = lock_pciems_device
    run.is_not_linux = is_not_linux
    return run


def test_on_a_machine_with_everything_every_area_is_well(doctor):
    result = doctor()

    assert result.returncode == 0, result.stdout + result.stderr
    assert marks(result.stdout) == {area.title: "✅" for area in AREAS}


# What each required area looks for, the commands that install it on Ubuntu
# and on a Mac, where Apple's command line tools have some of them, and the
# parts of the firmware it is for: a machine that builds all of them in
# Docker looks for Docker in its place.
XCODE = "xcode-select --install"
APT = "sudo apt-get install -y"
BUILD = DOCTOR_MODULE.FIRMWARE_BUILD
EVERY_PART = BUILD.PARTS
REQUIRED = [
    ("git", "socpuppet's build", f"{APT} git", XCODE, ()),
    ("c++", "socpuppet's build", f"{APT} build-essential", XCODE, ()),
    (
        "dtc",
        "socpuppet's build",
        f"{APT} device-tree-compiler",
        "brew install dtc",
        (),
    ),
    (
        "curl",
        "the firmware's build",
        f"{APT} curl",
        "brew install curl",
        EVERY_PART,
    ),
    (
        "make",
        "the firmware's build",
        f"{APT} build-essential",
        XCODE,
        EVERY_PART,
    ),
    (
        "iasl",
        "EDK2's build",
        f"{APT} acpica-tools",
        "brew install acpica",
        ("edk2",),
    ),
    (
        "flex",
        "the Linux kernel's build",
        f"{APT} flex",
        "brew install flex",
        ("linux",),
    ),
    (
        "bc",
        "the Linux kernel's build",
        f"{APT} bc",
        "brew install bc",
        ("linux",),
    ),
]


def in_docker_here(part):
    """Whether this machine builds a part of the firmware in Docker."""
    return BUILD.builds_in_docker(part, BUILD.sdk_host())


# Whether this machine builds a part in Docker, which a required area then
# wants, so that the check fails without it.
DOCKER_REQUIRED = any(in_docker_here(part) for part in EVERY_PART)


@pytest.mark.parametrize(
    ("program", "title", "on_linux", "on_a_mac", "parts"),
    REQUIRED,
    ids=[need[0] for need in REQUIRED],
)
def test_a_missing_program_fails_its_area_and_says_how_to_install_it(
    doctor, program, title, on_linux, on_a_mac, parts
):
    if parts and all(in_docker_here(part) for part in parts):
        pytest.skip("this machine builds that part in Docker")
    doctor.without(program)

    result = doctor()

    assert result.returncode == 1
    assert marks(result.stdout)[title] == "❌"
    assert f"{program} is not installed" in result.stdout
    fix = on_linux if platform.system() == "Linux" else on_a_mac
    assert fix in result.stdout


@pytest.mark.parametrize("part", ["edk2", "linux"])
def test_a_part_that_builds_in_docker_here_wants_docker_and_not_its_programs(
    part,
):
    wanted = [
        need.name for need in DOCTOR_MODULE.needs_of(part, "macos-x86_64")
    ]

    assert wanted == ["docker", "docker info"]


def test_a_part_that_builds_here_wants_its_programs():
    wanted = [
        need.name for need in DOCTOR_MODULE.needs_of("linux", "linux-x86_64")
    ]

    assert wanted == ["flex", "bison", "bc", "mkfs.ext4"]


def test_on_an_intel_mac_the_firmwares_build_wants_docker_for_its_tools():
    # Every part builds in the devcontainer's image there.
    wanted = [
        need.name for need in DOCTOR_MODULE.firmware_needs("macos-x86_64")
    ]

    assert wanted == ["git", "docker", "docker info"]


@pytest.mark.parametrize("host", ["linux-x86_64", "macos-aarch64"])
def test_where_any_part_of_the_firmware_builds_here_it_wants_git_curl_and_make(
    host,
):
    wanted = [need.name for need in DOCTOR_MODULE.firmware_needs(host)]

    assert wanted == ["git", "curl", "make"]


@pytest.mark.skipif(
    platform.system() != "Darwin", reason="only a Mac builds its wheel so"
)
def test_a_mac_without_pythons_cpython_warns_without_failing_and_says_where(
    doctor,
):
    result = doctor("wheel", PACKAGES="com.apple.pkg.spam")

    assert result.returncode == 0, result.stdout
    assert marks(result.stdout)["the wheel's build"] == "⚠️"
    assert f"python.org's CPython {PYTHON} is not installed" in result.stdout
    assert "https://www.python.org/downloads/macos/" in result.stdout


def test_pythons_cpython_is_looked_for_by_its_minor_version_as_it_names_itself():
    # Its package is one for every 3.13: a pin to 3.13.5 still finds it.
    package = DOCTOR_MODULE.python_org_package("3.13.5")

    assert package == "org.python.Python.PythonFramework-3.13"


def test_where_pythons_cpython_is_installed_the_wheels_build_is_well(doctor):
    result = doctor("wheel")

    assert marks(result.stdout) == {"the wheel's build": "✅"}


@pytest.mark.skipif(
    platform.system() == "Darwin", reason="a Mac is where it is looked for"
)
def test_other_than_on_a_mac_pythons_cpython_is_not_looked_for(doctor):
    result = doctor("wheel", PACKAGES="com.apple.pkg.spam")

    assert marks(result.stdout) == {"the wheel's build": "✅"}


def problems(output):
    """What each area's line of the output says is wrong, by its title."""
    found = {}
    for line in output.splitlines():
        _, _, rest = line.partition(" ")
        for area in AREAS:
            if rest.startswith(f"{area.title}: "):
                found[area.title] = rest.removeprefix(f"{area.title}: ")
    return found


def marks(output):
    """The mark each area's line of the output opens with, by its title."""
    found = {}
    for line in output.splitlines():
        mark, _, rest = line.partition(" ")
        for area in AREAS:
            if rest.strip().startswith(area.title):
                found[area.title] = mark
    return found


PCIEM = "pciem, for a real host"


def test_without_pciems_module_loaded_pciem_warns_without_failing_and_says_how_to_load_it(
    doctor,
):
    doctor.unload_pciem()

    result = doctor("pciem")

    assert result.returncode == 0, result.stdout
    assert problems(result.stdout)[PCIEM] == "pciem's module is not loaded"
    assert "tools/build_pciem.py" in result.stdout
    assert "docs/setup.md" in result.stdout


def test_a_kernel_older_than_6_6_makes_pciem_warn_and_says_why(doctor):
    doctor.runs_kernel("6.5.9")

    result = doctor("pciem")

    assert problems(result.stdout)[PCIEM] == (
        "the kernel is 6.5.9, and pciem needs 6.6 or later"
    )


@pytest.mark.parametrize("release", ["6.6.0", RELEASE])
def test_a_kernel_of_6_6_or_later_is_well_for_pciem(doctor, release):
    doctor.runs_kernel(release)

    result = doctor("pciem")

    assert marks(result.stdout)[PCIEM] == "✅"


def test_on_a_machine_that_is_not_linux_pciem_says_so_and_nothing_else(
    doctor,
):
    doctor.is_not_linux()

    result = doctor("pciem", FAIL_ON="sudo")

    assert result.returncode == 0, result.stdout
    assert problems(result.stdout)[PCIEM] == (
        "this machine is not Linux, and pciem is Linux's"
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write any file")
def test_where_pciems_device_cannot_be_written_pciem_says_to_give_it_to_you(
    doctor,
):
    doctor.lock_pciems_device()

    result = doctor("pciem")

    assert problems(result.stdout)[PCIEM].endswith(
        "dev/pciem cannot be opened for writing"
    )
    assert "udev" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root needs no sudo")
def test_where_sudo_asks_for_a_password_pciem_says_to_let_you_run_as_root_without_one(
    doctor,
):
    result = doctor("pciem", FAIL_ON="sudo")

    assert problems(result.stdout)[PCIEM] == "sudo asks for a password"
    assert "without a password" in result.stdout


GUEST = "a QEMU guest, for a real host on CI"


@pytest.mark.parametrize(
    ("program", "package"),
    [
        ("qemu-system-x86_64", "qemu-system-x86"),
        ("busybox", "busybox-static"),
        ("zstd", "zstd"),
    ],
)
def test_without_a_program_of_the_guests_it_warns_without_failing_and_names_its_package(
    doctor, program, package
):
    doctor.without(program)

    result = doctor("guest")

    assert result.returncode == 0, result.stdout
    assert problems(result.stdout)[GUEST] == f"{program} is not installed"
    assert f"{APT} {package}" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_where_the_running_kernel_cannot_be_read_the_guest_says_to_let_it_be(
    doctor,
):
    doctor.hides_the_kernel()

    result = doctor("guest")

    assert problems(result.stdout)[GUEST].endswith(
        f"boot/vmlinuz-{RELEASE} cannot be read"
    )
    assert "sudo chmod a+r /boot/vmlinuz-$(uname -r)" in result.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write any file")
def test_where_kvm_cannot_be_opened_the_guest_says_how_to_give_it_to_you(
    doctor,
):
    doctor.locks_kvm()

    result = doctor("guest")

    assert problems(result.stdout)[GUEST].endswith(
        "dev/kvm cannot be opened for writing"
    )
    assert "sudo setfacl -m u:$USER:rw /dev/kvm" in result.stdout


def test_without_the_running_kernels_headers_the_guest_names_their_package(
    doctor,
):
    doctor.lacks_kernel_headers()

    result = doctor("guest")

    assert problems(result.stdout)[GUEST] == (
        f"there are no headers for the kernel, {RELEASE}"
    )
    assert f"{APT} linux-headers-$(uname -r)" in result.stdout


def test_on_a_machine_that_is_not_linux_the_guest_says_so_and_nothing_else(
    doctor,
):
    doctor.is_not_linux()

    result = doctor("guest")

    assert result.returncode == 0, result.stdout
    assert problems(result.stdout)[GUEST] == (
        "this machine is not Linux, and the guest is its own kernel's"
    )


def test_a_missing_qbox_package_warns_without_failing_and_names_them_all(
    doctor,
):
    doctor.without("meson")
    doctor.without("ninja")

    result = doctor(FAIL_ON="sdl2")

    assert result.returncode == 0, result.stdout
    assert marks(result.stdout)["QBox's packages"] == "⚠️"
    for problem in (
        "meson is not installed",
        "ninja is not installed",
        "pkg-config cannot find sdl2",
    ):
        assert problem in result.stdout
    on_linux = platform.system() == "Linux"
    installer = APT if on_linux else "brew install"
    wanted = {
        apt if on_linux else brew
        for name, apt, brew in (*QBOX.PROGRAMS, *QBOX.LIBRARIES)
        if name in ("meson", "ninja", "sdl2")
    }
    install = next(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith(installer)
    )
    assert set(install.removeprefix(installer).split()) == wanted


CABLE = "a cable to this machine's network, and ssh to Linux"


def test_without_scp_the_cable_warns_without_failing_and_names_its_package(
    doctor,
):
    doctor.without("scp")

    result = doctor("cable")

    assert result.returncode == 0, result.stdout
    assert marks(result.stdout)[CABLE] == "⚠️"
    assert "scp is not installed" in problems(result.stdout)[CABLE]
    if platform.system() == "Linux":
        install = next(
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip().startswith(APT)
        )
        assert "openssh-client" in install.removeprefix(APT).split()
    else:
        assert DOCTOR_MODULE.MACOS_HAS_IT.what in result.stdout


def test_a_library_that_cannot_be_loaded_is_a_problem_naming_it():
    problem = DOCTOR_MODULE.loadable("spam", "/nowhere/libspam.so")

    assert problem() == "libspam cannot be loaded"


def test_a_library_every_machine_has_can_be_loaded():
    # 🎓 The C library, which every program on the machine is linked with.
    problem = DOCTOR_MODULE.loadable("c")

    assert problem() is None


def test_a_library_found_only_elsewhere_can_be_loaded():
    # 🎓 The C library again, under a name the machine does not know it by.
    problem = DOCTOR_MODULE.loadable("spam", ctypes.util.find_library("c"))

    assert problem() is None


def test_the_cable_takes_no_notice_of_pkg_config_failing_to_find_slirp(
    doctor,
):
    # 🎓 Ubuntu's slirp.pc wants glib's headers, which libslirp-dev does not
    # bring and socpuppet.slirp, loading the library itself, has no use for.
    as_it_is = doctor("cable")

    with_pkg_config_failing = doctor("cable", FAIL_ON="slirp")

    assert (
        marks(with_pkg_config_failing.stdout)[CABLE]
        == (marks(as_it_is.stdout)[CABLE])
    )
    assert problems(with_pkg_config_failing.stdout).get(CABLE) == (
        problems(as_it_is.stdout).get(CABLE)
    )


def test_a_site_that_cannot_be_reached_fails_the_network_saying_why(doctor):
    result = doctor(FAIL_ON="https://github.com")

    assert result.returncode == 1
    assert marks(result.stdout)["the network"] == "❌"
    assert "github.com cannot be reached: spam: no eggs" in result.stdout
    assert "pypi.org" not in result.stdout


def test_without_curl_the_network_fails_saying_curl_is_missing(doctor):
    doctor.without("curl")

    result = doctor()

    assert marks(result.stdout)["the network"] == "❌"
    assert "curl is not installed, to try" in result.stdout


def test_without_docker_installed_docker_warns_without_failing(doctor):
    # Unless a part of the build is built in Docker here, which wants it.
    doctor.without("docker")

    result = doctor()

    assert result.returncode == int(DOCKER_REQUIRED), result.stdout
    assert marks(result.stdout)["Docker"] == "⚠️"
    assert "docker is not installed" in result.stdout


def test_with_docker_not_answering_docker_warns_saying_what_to_try(doctor):
    result = doctor(FAIL_ON="info")

    assert result.returncode == int(DOCKER_REQUIRED), result.stdout
    assert marks(result.stdout)["Docker"] == "⚠️"
    assert "`docker info` fails" in result.stdout


def test_the_checks_that_wait_on_a_program_wait_at_the_same_time(doctor):
    # Long enough that starting the fakes, which a busy machine takes
    # seconds over, is small beside it.
    slow = 3
    started = time.monotonic()

    result = doctor(SLOW=str(slow))

    took = time.monotonic() - started
    asked = len(doctor.lines())
    assert result.returncode == 0, result.stdout
    # One after another, the programs asked would take `asked` seconds.
    assert asked > 2
    assert took < asked * slow / 2


def test_with_areas_named_only_those_are_checked(doctor):
    result = doctor("build", "docker")

    assert marks(result.stdout) == {"socpuppet's build": "✅", "Docker": "✅"}
    # Neither a site nor a library was asked after.
    assert not any(
        "https://" in line or "pkg-config" in line for line in doctor.lines()
    )


def test_an_unknown_area_is_refused_and_the_usage_names_every_area(doctor):
    result = doctor("spam")

    assert result.returncode == 2
    for area in AREAS:
        assert area.name in result.stderr


# Every kind of machine the firmware is built on: the Zephyr SDK's, and an
# Intel Mac, which builds it in Docker.
FIRMWARE_HOSTS = (*BUILD.SDK_HOSTS, "macos-x86_64")


def every_need():
    """The needs of every area, as each kind of machine has them.

    The firmware's areas are made for the machine the doctor runs on, so
    those of the other kinds are made here.
    """
    for area in AREAS:
        yield from area.needs
    for host in FIRMWARE_HOSTS:
        yield from DOCTOR_MODULE.firmware_needs(host)
        # The parts with an area of their own, for their programs.
        for part in BUILD.PROGRAMS:
            yield from DOCTOR_MODULE.needs_of(part, host)


@pytest.mark.parametrize("system", ["Linux", "Darwin"])
def test_every_need_of_every_area_has_a_fix_of_its_own_on_linux_and_on_a_mac(
    system,
):
    # 💡 A need with Linux's fix and no Mac's fails here on any machine, not
    # only on a Mac's nightly run.
    told_elsewhere = [
        need.name
        for need in every_need()
        if need.fix_on(system) is DOCTOR_MODULE.ELSEWHERE
    ]

    assert told_elsewhere == []


def test_on_a_system_the_doctor_has_no_fix_for_a_missing_need_points_at_the_setup_guide():
    # 🎓 "Windows" is what platform.system() says there.
    spam = DOCTOR_MODULE.Need(
        "spam",
        lambda: "spam is missing",
        {
            "Linux": DOCTOR_MODULE.Fix("eggs"),
            "Darwin": DOCTOR_MODULE.Fix("eggs"),
        },
    )
    area = DOCTOR_MODULE.Area("spam", "spam", (spam,))

    (report,) = DOCTOR_MODULE.examine([area], system="Windows")

    fix = "\n".join(report.fix)
    assert "Linux" in fix
    assert "Mac" in fix
    assert "docs/setup.md" in fix


def test_on_a_system_the_doctor_has_no_fix_for_a_need_with_one_fix_for_every_system_says_it():
    spam = DOCTOR_MODULE.Need(
        "spam", lambda: "spam is missing", DOCTOR_MODULE.Fix("eggs")
    )
    area = DOCTOR_MODULE.Area("spam", "spam", (spam,))

    (report,) = DOCTOR_MODULE.examine([area], system="Windows")

    assert report.fix == ["eggs"]


def test_as_json_each_area_says_its_problems_and_how_to_fix_them(doctor):
    doctor.without("dtc")
    doctor.without("docker")

    result = doctor("--json", "build", "docker", "network")

    assert result.returncode == 1
    on_linux = platform.system() == "Linux"
    assert json.loads(result.stdout) == {
        "areas": [
            {
                "name": "build",
                "title": "socpuppet's build",
                "optional": False,
                "problems": ["dtc is not installed"],
                "fix": [
                    f"{APT} device-tree-compiler"
                    if on_linux
                    else "brew install dtc"
                ],
            },
            {
                "name": "network",
                "title": "the network",
                "optional": False,
                "problems": [],
                "fix": [],
            },
            {
                "name": "docker",
                "title": "Docker",
                "optional": True,
                "problems": ["docker is not installed"],
                "fix": [
                    "install Docker Engine: https://docs.docker.com/engine/install/"
                    if on_linux
                    else "install Docker Desktop: "
                    "https://www.docker.com/products/docker-desktop/"
                ],
            },
        ]
    }
