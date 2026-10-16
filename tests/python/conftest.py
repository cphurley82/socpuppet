import os
import pathlib

import pytest

pytest_plugins = ["pytester", "socpuppet.pytest_plugin"]


def firmware_directory(pytestconfig):
    """Where `firmware/build.py` left what it built and what it fetched."""
    return pathlib.Path(
        os.environ.get(
            "SOCPUPPET_FIRMWARE_DIR", pytestconfig.rootpath / "build/firmware"
        )
    )


@pytest.fixture
def firmware(pytestconfig):
    """Find a firmware image that `firmware/build.py` built, by file name.

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
            "`uv run firmware/build.py`, which takes a few minutes the "
            "first time."
        )
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            pytest.fail(missing)
        pytest.skip(missing)

    return find


@pytest.fixture
def zephyr_tree(pytestconfig):
    """Zephyr's own sources, where `firmware/build.py` fetched them.

    They are beside the images. A test that reads one of Zephyr's files is
    skipped where they are not, whatever SOCPUPPET_REQUIRE_FIRMWARE says:
    the images travel from one CI job to the next, and Zephyr does not.
    ⚠️ So CI's `test` job skips such a test, and its `twister` job, which
    has Zephyr, is the one that runs it.
    """
    tree = firmware_directory(pytestconfig) / "zephyr"
    if not tree.is_dir():
        pytest.skip(
            f"There is no {tree}. `firmware/build.py` fetches Zephyr, which "
            "takes a few minutes the first time."
        )
    return tree


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "not_on_qbox(reason): a test of the host that QBox's CPU does not "
        "pass, and why. It is skipped with the reason when SOCPUPPET_CPU is "
        "qbox_cpu, which the qbox test preset sets (docs/models/qbox-cpu.md).",
    )
    config.addinivalue_line(
        "markers",
        "long: a test that boots real firmware, for seconds or most of a "
        "minute. The long tests are collected first.",
    )


def pytest_collection_modifyitems(items):
    """Put the long tests first, and the rest in the order they were in.

    pytest-xdist hands the tests out to its workers in this order. Started
    last, a long test would keep the whole run waiting while every other
    worker sat idle.
    """
    items.sort(key=lambda item: item.get_closest_marker("long") is None)


def pytest_runtest_setup(item):
    fate = item.get_closest_marker("not_on_qbox")
    if fate is not None and os.environ.get("SOCPUPPET_CPU") == "qbox_cpu":
        pytest.skip(f"on QBox: {fate.args[0]}")
