"""The firmware a host's CPUs are given, and the one way a test gives it.

A host has up to three CPUs, each with an image of its own: the host's,
the IO die's manager's, and the SSD's. A test says which image each has,
and `boot` builds the platform and puts every image where its CPU will
start.

🎭 Python is the stand-in for a boot ROM here: an image is written
straight into its CPU's RAM before anything runs.
"""

import socpuppet as sp
from disk_access import IMAGE as DISK_TEST
from manager_firmware import IMAGE as MANAGER
from ssd_zephyr_firmware import IMAGE as SSD

__all__ = [
    "DISK_TEST",
    "GREETING",
    "HELLO_WORLD",
    "MANAGER",
    "SHELL",
    "SSD",
    "SYNCHRONIZATION",
    "boot",
]

#: Zephyr's own samples, built for the board `socpuppet_host`.
HELLO_WORLD = "hello_world_socpuppet_host.elf"
SYNCHRONIZATION = "synchronization_socpuppet_host.elf"
SHELL = "shell_module_socpuppet_host.elf"
#: What `hello_world` prints.
GREETING = "Hello World! socpuppet_host"


def boot(board, firmware, *, host, manager=None, ssd=None):
    """Build a host and load an image for each CPU that is given one.

    `firmware` is the fixture that finds an image by its file's name. A
    manager or an SSD that is given no image is one with no CPU: 🎭 a
    script, a stand-in, or none at all.

    Returns the story the consoles of those CPUs tell, as a transcript
    that has heard nothing yet.
    """
    platform = board.platform
    platform.build()
    # ⚠️ A host can have three bus masters, so each image is loaded
    # through the CPU whose firmware it is.
    platform.load_elf(firmware(host), via=board.cpu.socket)
    consoles = {}
    if manager is not None:
        platform.load_elf(firmware(manager), via=board.manager.cpu.socket)
        consoles["manager"] = board.manager.cpu_kit.uart
    if ssd is not None:
        platform.load_elf(firmware(ssd), via=board.drive.ssd.cpu.socket)
        consoles["ssd"] = board.drive.ssd.cpu_kit.uart
    consoles["host"] = board.uart
    return sp.Transcript(platform, consoles)
