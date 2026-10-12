import os
import pathlib

import pytest

pytest_plugins = ["pytester", "socpuppet.pytest_plugin"]


def firmware_directory(pytestconfig):
    """Where `firmware/build.sh` left what it built and what it fetched."""
    return pathlib.Path(
        os.environ.get(
            "SOCPUPPET_FIRMWARE_DIR", pytestconfig.rootpath / "build/firmware"
        )
    )


@pytest.fixture
def firmware(pytestconfig):
    """Find a firmware image that `firmware/build.sh` built, by file name.

    The images are in SOCPUPPET_FIRMWARE_DIR, or in build/firmware at the
    top of the repository when that is not set. A test whose image is missing is skipped, with the
    command that builds it. Where the images must be there (in CI), set
    SOCPUPPET_REQUIRE_FIRMWARE and the test fails instead.
    """
    directory = firmware_directory(pytestconfig)

    def find(name):
        image = directory / name
        if image.exists():
            return image
        missing = (
            f"There is no {image}. Build the firmware with "
            "`firmware/build.sh`, which takes a few minutes the first time."
        )
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            pytest.fail(missing)
        pytest.skip(missing)

    return find


@pytest.fixture
def zephyr_tree(pytestconfig):
    """Zephyr's own sources, where `firmware/build.sh` fetched them.

    They are beside the images. A test that reads one of Zephyr's files is
    skipped where they are not, whatever SOCPUPPET_REQUIRE_FIRMWARE says:
    the images travel from one CI job to the next, and Zephyr does not.
    ⚠️ So CI's `test` job skips such a test, and its `twister` job, which
    has Zephyr, is the one that runs it.
    """
    tree = firmware_directory(pytestconfig) / "zephyr"
    if not tree.is_dir():
        pytest.skip(
            f"There is no {tree}. `firmware/build.sh` fetches Zephyr, which "
            "takes a few minutes the first time."
        )
    return tree
