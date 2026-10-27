"""🔌 needs_cable, where the cable is required, as it is in CI's nightly runs."""

import os
from pathlib import Path

import pytest

from cable_area import what_the_cable_lacks

HERE = Path(__file__).resolve().parent
# Where a run in a process of its own finds cable_area.
PATH = (HERE,)

A_TEST_OVER_THE_CABLE = """
from cable_area import needs_cable

@needs_cable
def test_spam():
    pass
"""


@pytest.fixture
def run_apart(pytester, monkeypatch):
    """pytester, whose runs in a process of their own find cable_area."""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(map(str, PATH)))
    return pytester


@pytest.mark.skipif(
    what_the_cable_lacks() is None,
    reason="this machine lacks nothing for the cable",
)
class TestWhenTheCableIsRequiredAndThisMachineLacksIt:
    def test_the_run_fails_saying_what_it_lacks(self, run_apart, monkeypatch):
        monkeypatch.setenv("SOCPUPPET_REQUIRE_CABLE", "1")
        run_apart.makepyfile(A_TEST_OVER_THE_CABLE)

        result = run_apart.runpytest_subprocess()

        assert result.ret != 0
        result.stdout.fnmatch_lines([f"*{what_the_cable_lacks()}*"])
