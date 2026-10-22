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
    """Run one file of tests from `directory`, with the source tree's package.

    The package is found as the wheel's would be, without the checkout's
    pyproject.toml to point pytest at it.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-rs", test],
        cwd=directory,
        env={**os.environ, "PYTHONPATH": str(REPO / "python")},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
    )
    return Run(result.returncode == 0, result.stdout)
