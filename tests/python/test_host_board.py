"""The host platform and the Zephyr board that is generated from it."""

import json
import pathlib
import re

import pytest

import socpuppet
from socpuppet.boards.host import (
    ECAM_OFFSET,
    IO_BASE,
    MSI_SOURCE,
    TIMER_HZ,
    host,
)
from socpuppet.boards.ssd import DEVICE_ID, VENDOR_ID

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


class TestTheHostWithADrive:
    def test_has_an_ssd_of_the_size_asked_for(self):
        board = host(drive_blocks=4096)

        assert board.drive is not None
        assert board.drive.nvme.component.parameters["blocks"] == 4096

    def test_sends_the_drives_interrupt_messages_to_a_plic_source(self):
        board = host(drive_blocks=64)

        connections = json.loads(board.platform.to_json())["connections"]

        assert {
            "source": "compute.msi.irq",
            "sink": f"compute.plic.source{MSI_SOURCE}",
            "trace": False,
        } in connections

    @pytest.mark.platform
    def test_shows_the_drive_in_the_configuration_window(self):
        board = host(drive_blocks=64)
        board.platform.build()

        # A function's first register holds who made it and which device it
        # is. The first bus has room for 32 devices, each with 4 KiB of the
        # window, and the drive is the first.
        ids = board.platform.peek32(IO_BASE + ECAM_OFFSET)

        assert ids == DEVICE_ID << 16 | VENDOR_ID


class TestTheHostWithNoDrive:
    def test_has_none(self):
        assert host().drive is None
