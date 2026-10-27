"""The Python tests, run from a copy of tests/python alone.

tools/test_wheel.py runs them that way, on an installed wheel, so that what
they import is the package and not the source tree. The rest of the
checkout is not beside them there, and a test that reads a file of it
skips.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


class TestWhenTheExt4TestRunsFromACopyOfTestsPythonAlone:
    def test_it_skips_saying_the_checkouts_inittab_is_not_there(self, tmp_path):
        shutil.copytree(REPO / "tests" / "python", tmp_path / "tests")

        run = run_pytest(tmp_path, "tests/test_ext4_image.py")

        assert run.passed, run.output
        (reason,) = run.skip_reasons
        assert "firmware/rootfs/etc/inittab" in reason


class TestWhenTheCablesTestsRunFromACopyOfTestsPythonAlone:
    def test_they_skip_saying_this_is_no_checkout(self, tmp_path):
        shutil.copytree(REPO / "tests" / "python", tmp_path / "tests")

        run = run_pytest(tmp_path, "tests/test_ethernet_cable.py")

        assert run.passed, run.output
        assert run.skip_reasons
        for reason in run.skip_reasons:
            assert "this is no checkout" in reason


@dataclass
class Run:
    """How a run of pytest went: whether it passed, and what it said."""

    passed: bool
    output: str

    @property
    def skip_reasons(self) -> list[str]:
        """Why each skipped test was skipped, as `-rs` sums them up."""
        return [
            line for line in self.output.splitlines() if line.startswith("SKIP")
        ]


def run_pytest(directory, test):
    """Run one file of tests from `directory`, as the wheel's run would.

    The package is the source tree's, found as the wheel's would be,
    without the checkout's pyproject.toml to point pytest at it. None of
    CI's SOCPUPPET_REQUIRE_* variables is set, as cibuildwheel passes none.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("SOCPUPPET_REQUIRE_")
    }
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-rs", test],
        cwd=directory,
        env={**env, "PYTHONPATH": str(REPO / "python")},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    return Run(result.returncode == 0, result.stdout)
