"""The host platform and the Zephyr board that is generated from it."""

import pathlib
import re

import socpuppet
from socpuppet.boards.host import TIMER_HZ, host

ZEPHYR_MODULE = pathlib.Path(socpuppet.__file__).parent / "zephyr_module"


class TestTheZephyrBoardForTheHost:
    def test_its_devicetree_is_what_the_host_description_generates(self):
        checked_in = (
            ZEPHYR_MODULE / "boards/socpuppet/socpuppet_host/socpuppet_host.dts"
        )

        assert checked_in.read_text() == host().platform.devicetree()

    def test_its_clock_rate_is_the_rate_the_hosts_timer_counts_at(self):
        defaults = (
            ZEPHYR_MODULE / "soc/socpuppet/Kconfig.defconfig"
        ).read_text()

        rate = re.search(
            r"config SYS_CLOCK_HW_CYCLES_PER_SEC\s+default (\d+)", defaults
        )

        assert rate is not None
        assert int(rate.group(1)) == TIMER_HZ
