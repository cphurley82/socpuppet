"""socpuppet's Zephyr module, as the tests find it."""

import pathlib
import re

import socpuppet

ZEPHYR_MODULE = pathlib.Path(socpuppet.__file__).parent / "zephyr_module"


def kconfig_default(name):
    """The number every socpuppet SoC gives Zephyr for a Kconfig option.

    `name` is the option without its `CONFIG_`, as the family's
    Kconfig.defconfig has it.
    """
    defaults = (ZEPHYR_MODULE / "soc/socpuppet/Kconfig.defconfig").read_text()
    default = re.search(
        rf"^config {re.escape(name)}\s+default (\d+)$", defaults, re.MULTILINE
    )
    assert default is not None, f"the family's Kconfig.defconfig has no {name}"
    return int(default.group(1))


def clock_rate():
    """How many times a second Zephyr is told the machine timer counts."""
    return kconfig_default("SYS_CLOCK_HW_CYCLES_PER_SEC")
