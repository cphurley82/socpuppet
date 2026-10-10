"""The IO die's manager firmware, as a test runs it.

The image is `iomgr_socpuppet_iomgr.elf`: the Zephyr application in
`firmware/iomgr`, built for the board `socpuppet_iomgr`. It is the same
image on the IO manager board and in the manager under the host.
"""

IMAGE = "iomgr_socpuppet_iomgr.elf"
#: What the firmware says as it goes, in the order it says it.
TRAINING = "iomgr: training the D2D link"
LINK_UP = "iomgr: D2D link up"
RELEASED = "iomgr: compute die released"
WENT_DOWN = "iomgr: the D2D link went down"
WOULD_NOT_TRAIN = "iomgr: the D2D link would not train"


def console_of(board):
    """The manager's console, which is where its firmware prints."""
    assert board.manager.cpu_kit is not None
    return board.manager.cpu_kit.uart


def what_the_manager_said(console):
    """The firmware's own lines, without Zephyr's banner above them."""
    return [
        line
        for line in console.output.splitlines()
        if line.startswith("iomgr:")
    ]
