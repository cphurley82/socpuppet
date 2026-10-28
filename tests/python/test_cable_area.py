"""🔌 needs_cable, where the cable is required, as it is in CI's nightly runs."""

import pytest

import processes
from cable_area import what_the_cable_lacks

A_TEST_OVER_THE_CABLE = """
from cable_area import needs_cable

@needs_cable
def test_spam():
    pass
"""


@pytest.fixture
def run_apart(pytester, monkeypatch):
    """pytester, whose runs in a process of their own find cable_area.

    And the package cable_area asks: python/ in a checkout, which only
    this run's own configuration names, or wherever the wheel was
    installed. Both are on this run's path, which is what
    `processes.environment` hands a fresh interpreter.
    """
    monkeypatch.setenv("PYTHONPATH", processes.environment()["PYTHONPATH"])
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
