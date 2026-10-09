"""socpuppet's Zephyr module, as the tests find it."""

import pathlib
import re

import socpuppet

ZEPHYR_MODULE = pathlib.Path(socpuppet.__file__).parent / "zephyr_module"


def clock_rate():
    """How many times a second Zephyr is told the machine timer counts.

    It is one number for every socpuppet SoC:
    CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC.
    """
    defaults = (ZEPHYR_MODULE / "soc/socpuppet/Kconfig.defconfig").read_text()
    rate = re.search(
        r"config SYS_CLOCK_HW_CYCLES_PER_SEC\s+default (\d+)", defaults
    )
    assert rate is not None, "the family's Kconfig.defconfig gives no rate"
    return int(rate.group(1))
