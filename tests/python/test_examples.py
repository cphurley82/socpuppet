"""The examples, where what they do depends on what is around them.

Each example is also run as a test of its own (tests/python/CMakeLists.txt).
"""

import pathlib

import pytest

from processes import run_file

# ctest's code for "could not be run here", which is not a failure.
COULD_NOT_RUN = 77


@pytest.fixture
def host_hello(pytestconfig):
    """The example that boots Zephyr on the host."""
    example = pathlib.Path(pytestconfig.rootpath) / "examples/host_hello.py"
    if not example.exists():
        pytest.skip(
            "The examples are not here: these tests are being run away "
            "from the source tree, against an installed socpuppet."
        )
    return example


class TestWhenTheHostExampleFindsNoFirmware:
    def test_it_says_how_to_build_it_and_counts_as_not_run(
        self, host_hello, tmp_path
    ):
        result = run_file(
            host_hello,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
            SOCPUPPET_REQUIRE_FIRMWARE="",
        )

        assert result.returncode == COULD_NOT_RUN
        assert "firmware/build.sh" in result.stdout

    def test_it_looks_where_it_is_told_the_firmware_is(
        self, host_hello, tmp_path
    ):
        result = run_file(
            host_hello,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
            SOCPUPPET_REQUIRE_FIRMWARE="",
        )

        assert str(tmp_path) in result.stdout

    def test_it_fails_where_the_firmware_is_required(
        self, host_hello, tmp_path
    ):
        result = run_file(
            host_hello,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
            SOCPUPPET_REQUIRE_FIRMWARE="1",
        )

        assert result.returncode == 1
        assert "firmware/build.sh" in result.stderr
