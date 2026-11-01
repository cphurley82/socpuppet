"""🧦 A wheel alone, with nothing built, boots real firmware.

The images come from the release this socpuppet pins, over the network, the
first time they are asked for, or from a mirror that SOCPUPPET_IMAGES_URL
names. So these need that release to be published, which main's first run to
pass with these firmware sources does. Without it, or without the network,
they are skipped, unless SOCPUPPET_REQUIRE_FIRMWARE says the images must be
there, as it does in CI.
"""

import contextlib
import os

import pytest

import socpuppet as sp
from cast import FW_JUMP_BIN, GREETING, HELLO_WORLD, LINUX_BIN, ROOTFS_EXT4
from devicetree_compiler import needs_dtc
from linux_shell import LONG_ENOUGH
from socpuppet import images, linux
from socpuppet.boards.host import host

#: Simulated time for Zephyr's `hello_world` to speak: far more than it needs.
SAYS_HELLO_WITHIN = sp.ms(100)


@pytest.fixture
def nothing_built(tmp_path, monkeypatch):
    """Nothing fetched yet, and no checkout anywhere to be seen."""
    monkeypatch.delenv("SOCPUPPET_FIRMWARE_DIR", raising=False)
    monkeypatch.setenv("SOCPUPPET_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)


@contextlib.contextmanager
def the_images_can_be_had():
    """Go on if they can be fetched here, or else skip, or where they must be,
    fail."""
    try:
        yield
    except images.Unavailable as unavailable:
        if os.environ.get("SOCPUPPET_REQUIRE_FIRMWARE"):
            pytest.fail(str(unavailable))
        pytest.skip(str(unavailable))


def in_the_cache():
    """The images fetched so far, by name."""
    return {
        path.name
        for path in images.directory().iterdir()
        if not path.name.startswith(".")
    }


@pytest.mark.long
@pytest.mark.platform
def test_zephyrs_hello_world_is_fetched_alone_and_boots(nothing_built):
    with the_images_can_be_had():
        image = images.find(HELLO_WORLD)
    board = host()
    board.platform.build()
    board.platform.load_elf(image)

    said = board.platform.run_until(
        lambda: GREETING in board.uart.output, timeout=SAYS_HELLO_WITHIN
    )

    assert said, board.uart.output
    assert in_the_cache() == {HELLO_WORLD}


@needs_dtc
@pytest.mark.long
@pytest.mark.platform
def test_linux_is_fetched_with_only_what_it_needs_and_reaches_its_prompt(
    nothing_built,
):
    with the_images_can_be_had():
        board = linux.host_with_linux()

    prompted = board.platform.run_until(
        lambda: linux.PROMPT.search(board.virtio.console.output),
        timeout=LONG_ENOUGH,
    )

    assert prompted, board.virtio.console.output
    assert in_the_cache() == {FW_JUMP_BIN, LINUX_BIN, ROOTFS_EXT4}
