"""tools/doctor.py, which checks this machine for socpuppet's development.

The doctor is run for real, with a path of fakes for every program it
looks for. Each fake writes the command it was given to a log, and the
tests take a program away, or make one fail, to give the machine a problem.
"""

import importlib.util
import json
import os
import platform
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
# What QBox's build needs, as tools/build_qbox.py lists it for the doctor.
QBOX = DOCTOR_MODULE.BUILD_QBOX

# Every program the doctor looks for, each of which the machine has unless
# a test takes it away.
PROGRAMS = (
    *("git", "c++", "dtc", "curl", "make", "iasl", "docker"),
    *(name for name, _, _ in QBOX.PROGRAMS),
)


@pytest.fixture
def doctor(tmp_path):
    """Run the doctor with the fakes; returns run(*args, **env).

    run returns the finished process. run.without(program) takes a program
    off the path, and run.lines() are the commands the fakes were given.
    """
    bin_directory = tmp_path / "bin"
    bin_directory.mkdir()
    for program in PROGRAMS:
        path = bin_directory / program
        path.write_text(f"#!{sys.executable}\n{FAKE}")
        path.chmod(0o755)
    log = tmp_path / "log"

    def run(*args, **env):
        return subprocess.run(
            [sys.executable, str(DOCTOR), *args],
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

    run.without = without
    run.lines = lines
    return run


def test_on_a_machine_with_everything_every_area_is_well(doctor):
    result = doctor()

    assert result.returncode == 0, result.stdout + result.stderr
    assert marks(result.stdout) == {area.title: "✅" for area in AREAS}


# What each required area looks for, and the commands that install it on
# Ubuntu and on a Mac, where Apple's command line tools have some of them.
XCODE = "xcode-select --install"
APT = "sudo apt-get install -y"
REQUIRED = [
    ("git", "socpuppet's build", f"{APT} git", XCODE),
    ("c++", "socpuppet's build", f"{APT} build-essential", XCODE),
    (
        "dtc",
        "socpuppet's build",
        f"{APT} device-tree-compiler",
        "brew install dtc",
    ),
    ("curl", "the firmware's build", f"{APT} curl", "brew install curl"),
    ("make", "the firmware's build", f"{APT} build-essential", XCODE),
    ("iasl", "EDK2's build", f"{APT} acpica-tools", "brew install acpica"),
]


@pytest.mark.parametrize(
    ("program", "title", "on_linux", "on_a_mac"),
    REQUIRED,
    ids=[need[0] for need in REQUIRED],
)
def test_a_missing_program_fails_its_area_and_says_how_to_install_it(
    doctor, program, title, on_linux, on_a_mac
):
    doctor.without(program)

    result = doctor()

    assert result.returncode == 1
    assert marks(result.stdout)[title] == "❌"
    assert f"{program} is not installed" in result.stdout
    fix = on_linux if platform.system() == "Linux" else on_a_mac
    assert fix in result.stdout


def marks(output):
    """The mark each area's line of the output opens with, by its title."""
    found = {}
    for line in output.splitlines():
        mark, _, rest = line.partition(" ")
        for area in AREAS:
            if rest.strip().startswith(area.title):
                found[area.title] = mark
    return found


def test_a_missing_qbox_package_warns_without_failing_and_names_them_all(
    doctor,
):
    doctor.without("meson")
    doctor.without("bison")

    result = doctor(FAIL_ON="sdl2")

    assert result.returncode == 0, result.stdout
    assert marks(result.stdout)["QBox's packages"] == "⚠️"
    for problem in (
        "meson is not installed",
        "bison is not installed",
        "pkg-config cannot find sdl2",
    ):
        assert problem in result.stdout
    on_linux = platform.system() == "Linux"
    installer = APT if on_linux else "brew install"
    wanted = {
        apt if on_linux else brew
        for name, apt, brew in (*QBOX.PROGRAMS, *QBOX.LIBRARIES)
        if name in ("meson", "bison", "sdl2")
    }
    install = next(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith(installer)
    )
    assert set(install.removeprefix(installer).split()) == wanted


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
    doctor.without("docker")

    result = doctor()

    assert result.returncode == 0, result.stdout
    assert marks(result.stdout)["Docker"] == "⚠️"
    assert "docker is not installed" in result.stdout


def test_with_docker_not_answering_docker_warns_saying_what_to_try(doctor):
    result = doctor(FAIL_ON="info")

    assert result.returncode == 0, result.stdout
    assert marks(result.stdout)["Docker"] == "⚠️"
    assert "`docker info` fails" in result.stdout


def test_the_checks_that_wait_on_a_program_wait_at_the_same_time(doctor):
    slow = 1
    started = time.monotonic()

    result = doctor(SLOW=str(slow))

    took = time.monotonic() - started
    asked = len(doctor.lines())
    assert result.returncode == 0, result.stdout
    # One after another, the programs asked would take `asked` seconds.
    assert asked > 2
    assert took < asked * slow / 2


def test_with_areas_named_only_those_are_checked(doctor):
    result = doctor("edk2", "docker")

    assert marks(result.stdout) == {"EDK2's build": "✅", "Docker": "✅"}
    # Neither a site nor a library was asked after.
    assert not any(
        "https://" in line or "pkg-config" in line for line in doctor.lines()
    )


def test_an_unknown_area_is_refused_and_the_usage_names_every_area(doctor):
    result = doctor("spam")

    assert result.returncode == 2
    for area in AREAS:
        assert area.name in result.stderr


def test_as_json_each_area_says_its_problems_and_how_to_fix_them(doctor):
    doctor.without("iasl")
    doctor.without("docker")

    result = doctor("--json", "edk2", "docker", "network")

    assert result.returncode == 1
    on_linux = platform.system() == "Linux"
    assert json.loads(result.stdout) == {
        "areas": [
            {
                "name": "edk2",
                "title": "EDK2's build",
                "optional": False,
                "problems": ["iasl is not installed"],
                "fix": [
                    f"{APT} acpica-tools" if on_linux else "brew install acpica"
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
