import os
import pathlib

import pytest

from socpuppet import _core

pytest_plugins = ["pytester", "socpuppet.pytest_plugin"]


def firmware_directory(pytestconfig):
    """Where `firmware/build.py` left what it built and what it fetched."""
    return pathlib.Path(
        os.environ.get(
            "SOCPUPPET_FIRMWARE_DIR", pytestconfig.rootpath / "build/firmware"
        )
    )


@pytest.fixture(scope="session")
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


@pytest.fixture
def dtc_is_not_installed(tmp_path, monkeypatch):
    """A PATH on which dtc, the devicetree compiler, is nowhere to be found.

    A directory that is not there, and not an empty PATH, which the
    operating system reads as the current directory.
    """
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))


def pytest_configure(config):
    _stop_if_qbox_cpu_is_asked_for_and_not_in_this_build()
    config.addinivalue_line(
        "markers",
        "not_on_qbox(reason): a test of the host that QBox's CPU does not "
        "pass, and why. It is skipped with the reason when SOCPUPPET_CPU is "
        "qbox_cpu, which the qbox test preset sets (docs/models/qbox-cpu.md).",
    )
    config.addinivalue_line(
        "markers",
        "only_on_qbox(reason): a test of something QBox's CPU has and the "
        "DBT-RISE CPU has not, and what. It is skipped with the reason unless "
        "SOCPUPPET_CPU is qbox_cpu.",
    )
    config.addinivalue_line(
        "markers",
        "long: a test that takes seconds, or most of a minute, on its own: "
        "the boots of OpenSBI, UEFI and Linux. The long tests are collected "
        "first, so that none of them starts last. `-m 'not long'` leaves "
        "them out, as the fast test preset does.",
    )
    config.addinivalue_line(
        "markers",
        "representative(area): a long test that boots for its area "
        "(linux, uefi, ...) on every push, as the quick test preset runs "
        "them with `-m representative`; the rest of the long tests run "
        "every night (CMakePresets.json).",
    )


def _stop_if_qbox_cpu_is_asked_for_and_not_in_this_build():
    """Stop before any test when SOCPUPPET_CPU asks for QBox's CPU and this build has none.

    QBox's is the one CPU a build can lack (docs/development.md). One line,
    not a failure of every test that builds a host: the extension
    in python/socpuppet/ is a copy the last tree built left there
    (docs/development.md), so a run on QBox's CPU after a build of the dev
    tree would fail each of them the same way.
    """
    if os.environ.get("SOCPUPPET_CPU") == "qbox_cpu" and not _core.has_qbox:
        pytest.exit(
            "SOCPUPPET_CPU is qbox_cpu, but this build of socpuppet has no "
            "qbox_cpu: the extension in python/socpuppet/ is the dev tree's. "
            "Build the qbox tree, `uv run cmake --build --preset qbox`, which "
            "leaves its own there.",
            returncode=pytest.ExitCode.USAGE_ERROR,
        )


def pytest_collection_modifyitems(config, items):
    """Skip for the CPU, and put the long tests first.

    pytest-xdist hands the tests out to its workers in this order. Started
    last, a long test would keep the whole run waiting while every other
    worker sat idle. The rest stay in the order they were in.
    """
    _skip_for_the_cpu(items)
    items.sort(key=lambda item: item.get_closest_marker("long") is None)


def _skip_for_the_cpu(items):
    """Mark to skip the tests that SOCPUPPET_CPU's CPU does not run.

    💡 A skip marker, not pytest.skip() at setup: socpuppet.pytest_plugin
    runs a `platform` test that has one in pytest's own process, so none
    is started only to skip there.
    """
    on_qbox = os.environ.get("SOCPUPPET_CPU") == "qbox_cpu"
    for item in items:
        not_on = item.get_closest_marker("not_on_qbox")
        if not_on is not None and on_qbox:
            item.add_marker(
                pytest.mark.skip(reason=f"on QBox: {not_on.args[0]}")
            )
        only_on = item.get_closest_marker("only_on_qbox")
        if only_on is not None and not on_qbox:
            item.add_marker(
                pytest.mark.skip(reason=f"not on QBox: {only_on.args[0]}")
            )
