"""🩺 needs_pciem, where pciem is required, as it is in CI's guest."""

import pytest

import processes
from pciem_area import what_pciem_lacks

A_TEST_OF_A_REAL_HOST = """
from pciem_area import needs_pciem

@needs_pciem
def test_spam():
    pass
"""


@pytest.fixture
def run_apart(pytester, monkeypatch):
    """pytester, whose runs in a process of their own find pciem_area.

    And socpuppet, which pciem_area asks: both are on this run's path,
    which is what `processes.environment` hands a fresh interpreter.
    """
    monkeypatch.setenv("PYTHONPATH", processes.environment()["PYTHONPATH"])
    return pytester


@pytest.mark.skipif(
    what_pciem_lacks() is None, reason="this machine lacks nothing for pciem"
)
class TestWhenPciemIsRequiredAndThisMachineLacksIt:
    def test_the_run_fails_saying_what_it_lacks(self, run_apart, monkeypatch):
        monkeypatch.setenv("SOCPUPPET_REQUIRE_PCIEM", "1")
        run_apart.makepyfile(A_TEST_OF_A_REAL_HOST)

        result = run_apart.runpytest_subprocess()

        assert result.ret != 0
        result.stdout.fnmatch_lines([f"*{what_pciem_lacks()}*"])
