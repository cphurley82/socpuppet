"""The examples, where what they do depends on what is around them.

Each example is also run as a test of its own (tests/python/CMakeLists.txt).
"""

import pathlib

import pytest

from processes import run_file

# ctest's code for "could not be run here", which is not a failure.
COULD_NOT_RUN = 77


@pytest.fixture(
    params=[
        "host_hello.py",
        "ssd_firmware_hello.py",
        "host_and_ssd_hello.py",
    ]
)
def example(request, pytestconfig):
    """An example that boots firmware: each test here is run with each."""
    example = pathlib.Path(pytestconfig.rootpath) / "examples" / request.param
    if not example.exists():
        pytest.skip(
            "The examples are not here: these tests are being run away "
            "from the source tree, against an installed socpuppet."
        )
    return example


class TestWhenAnExampleThatBootsFirmwareFindsNone:
    def test_it_says_how_to_build_it_and_counts_as_not_run(
        self, example, tmp_path
    ):
        result = run_file(
            example,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
            SOCPUPPET_REQUIRE_FIRMWARE="",
        )

        assert result.returncode == COULD_NOT_RUN
        assert "firmware/build.sh" in result.stdout

    def test_it_looks_where_it_is_told_the_firmware_is(self, example, tmp_path):
        result = run_file(
            example,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
            SOCPUPPET_REQUIRE_FIRMWARE="",
        )

        assert str(tmp_path) in result.stdout

    def test_it_fails_where_the_firmware_is_required(self, example, tmp_path):
        result = run_file(
            example,
            SOCPUPPET_FIRMWARE_DIR=str(tmp_path),
            SOCPUPPET_REQUIRE_FIRMWARE="1",
        )

        assert result.returncode == 1
        assert "firmware/build.sh" in result.stderr
