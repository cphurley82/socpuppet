"""The Python tests, run from a copy of tests/python alone.

tools/test_wheel.py runs them that way, on an installed wheel, so that what
they import is the package and not the source tree. The rest of the
checkout is not beside them there, and a test that reads a file of it
skips.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from socpuppet import SlirpUnavailable, slirp

REPO = Path(__file__).resolve().parents[2]


def load_tool(name):
    """Import a tool of tools/ as a module."""
    path = REPO / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# tools/test_wheel.py, for how it lays its copy of the tests out.
test_wheel = load_tool("test_wheel")


def libslirp_loads_here() -> bool:
    """Whether this machine has a libslirp the package can load."""
    try:
        slirp.version()
    except SlirpUnavailable:
        return False
    return True


LIBSLIRP_LOADS_HERE = libslirp_loads_here()
SSH_AND_SCP_ARE_HERE = all(shutil.which(program) for program in ("ssh", "scp"))
needs_libslirp = pytest.mark.skipif(
    not LIBSLIRP_LOADS_HERE, reason="this machine lacks libslirp"
)
needs_the_cable = pytest.mark.skipif(
    not (LIBSLIRP_LOADS_HERE and SSH_AND_SCP_ARE_HERE),
    reason="this machine lacks libslirp, ssh or scp",
)


class TestWhenTheExt4TestRunsFromACopyOfTestsPythonAlone:
    def test_it_skips_saying_the_checkouts_inittab_is_not_there(self, tmp_path):
        shutil.copytree(REPO / "tests" / "python", tmp_path / "tests")

        run = run_pytest(tmp_path, "tests/test_ext4_image.py")

        assert run.passed, run.output
        (reason,) = run.skip_reasons
        assert "firmware/rootfs/etc/inittab" in reason


class TestWhenTheFrontDoorTestRunsFromACopyOfTestsPythonAlone:
    def test_it_skips_saying_the_checkouts_readme_is_not_there(self, tmp_path):
        shutil.copytree(REPO / "tests" / "python", tmp_path / "tests")

        run = run_pytest(tmp_path, "tests/test_front_door.py")

        # 💡 Skipped whole, it has no tests to run: alone, that is pytest's
        # NO_TESTS_COLLECTED, and among the rest of tests/python it is a pass.
        assert run.exit_code == pytest.ExitCode.NO_TESTS_COLLECTED, run.output
        (reason,) = run.skip_reasons
        assert "README.md here" in reason


class TestWhenTheCablesTestsRunFromACopyOfTestsPythonAlone:
    """They ask the package what the cable lacks, not the checkout's doctor."""

    @needs_the_cable
    def test_they_run_and_pass_where_this_machine_has_the_cable(self, tmp_path):
        shutil.copytree(REPO / "tests" / "python", tmp_path / "tests")

        run = run_pytest(tmp_path, "tests/test_ethernet_cable.py")

        assert run.passed, run.output
        assert run.skip_reasons == []

    @needs_libslirp
    def test_where_ssh_is_not_on_the_path_they_skip_saying_so(self, tmp_path):
        shutil.copytree(REPO / "tests" / "python", tmp_path / "tests")

        run = run_pytest(
            tmp_path, "tests/test_ethernet_cable.py", without_ssh=True
        )

        assert run.passed, run.output
        assert run.skip_reasons
        for reason in run.skip_reasons:
            assert "ssh is not installed" in reason


class TestWhenTheFrontDoorRunsFromACopyLaidOutByTheWheelsTest:
    """tools/test_wheel.py puts the pages and the examples beside the tests."""

    def test_its_excerpts_are_checked_and_none_skips(self, tmp_path):
        test_wheel.copy_as_checked_in(tmp_path)

        run = run_pytest(
            tmp_path,
            "tests/python/test_front_door.py::"
            "test_a_block_that_does_not_import_socpuppet_is_an_excerpt_of_a_file_named_beside_it",
        )

        assert run.passed, run.output
        assert run.skip_reasons == []


@dataclass
class Run:
    """How a run of pytest went: how it ended, and what it said."""

    exit_code: int
    output: str

    @property
    def passed(self) -> bool:
        """Whether every test it collected passed, or was skipped."""
        return self.exit_code == pytest.ExitCode.OK

    @property
    def skip_reasons(self) -> list[str]:
        """Why each skipped test was skipped, as `-rs` sums them up."""
        return [
            line for line in self.output.splitlines() if line.startswith("SKIP")
        ]


def run_pytest(directory, test, without_ssh=False):
    """Run one file of tests from `directory`, as the wheel's run would.

    The package is the source tree's, found as the wheel's would be,
    without the checkout's pyproject.toml to point pytest at it. None of
    CI's SOCPUPPET_REQUIRE_* variables is set, as cibuildwheel passes none.
    `without_ssh` runs it with a PATH that holds no programs at all, as a
    machine with no ssh would.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("SOCPUPPET_REQUIRE_")
    }
    if without_ssh:
        env["PATH"] = str(directory)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-rs", test],
        cwd=directory,
        env={**env, "PYTHONPATH": str(REPO / "python")},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    return Run(result.returncode, result.stdout)
