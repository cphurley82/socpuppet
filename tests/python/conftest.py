import os
import pathlib

import pytest

pytest_plugins = ["pytester", "socpuppet.pytest_plugin"]


@pytest.fixture
def firmware(pytestconfig):
    """Find a firmware image that `firmware/build.sh` built, by file name.

    The images are in SOCPUPPET_FIRMWARE_DIR, or in build/firmware at the
    top of the repository when that is not set. A test whose image is missing is skipped, with the
    command that builds it. Where the images must be there (in CI), set
    SOCPUPPET_REQUIRE_FIRMWARE and the test fails instead.
    """
    directory = pathlib.Path(
        os.environ.get(
            "SOCPUPPET_FIRMWARE_DIR", pytestconfig.rootpath / "build/firmware"
        )
    )

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
