"""The host platform and the Zephyr board that is generated from it."""

import json
import pathlib
import re

import pytest

import socpuppet
from devicetree_compiler import dtc_errors, needs_dtc
from socpuppet.boards.host import (
    ECAM_OFFSET,
    IO_BASE,
    MSI_SOURCE,
    TIMER_HZ,
    drive_overlay,
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


class TestTheZephyrShieldForTheHostsDrive:
    def test_its_overlay_is_what_the_host_description_generates(self):
        checked_in = (
            ZEPHYR_MODULE
            / "boards/shields/socpuppet_host_drive/socpuppet_host_drive.overlay"
        )

        # When this fails, the docstring of `drive_overlay` has the command
        # that writes the file again.
        assert checked_in.read_text() == drive_overlay()

    def test_its_overlay_names_the_drive_as_the_drive_names_itself(self):
        overlay = drive_overlay()

        assert f"vendor-id = <{VENDOR_ID:#x}>;" in overlay
        assert f"device-id = <{DEVICE_ID:#x}>;" in overlay

    def test_its_overlay_sends_the_root_complexs_messages_to_the_bridge(self):
        assert "msi-parent = <&compute_msi>;" in drive_overlay()

    def test_its_overlay_has_every_device_the_drive_adds_to_the_host(self):
        added = labels(host(drive_blocks=64).platform.devicetree()) - labels(
            host().platform.devicetree()
        )

        assert added
        assert added <= labels(drive_overlay())

    @needs_dtc
    def test_the_devicetree_compiler_accepts_the_board_with_its_overlay(
        self, tmp_path
    ):
        board = (
            ZEPHYR_MODULE / "boards/socpuppet/socpuppet_host/socpuppet_host.dts"
        ).read_text()

        assert dtc_errors(board + drive_overlay(), tmp_path) == ""


def labels(devicetree):
    """The labels of the nodes in devicetree source: `io_uart` and so on."""
    return set(re.findall(r"^\s*(\w+): ", devicetree, re.MULTILINE))


class TestTheHostWithADrive:
    def test_has_an_ssd_of_the_size_asked_for(self):
        board = host(drive_blocks=4096)

        assert board.drive is not None
        assert board.drive.ssd.nvme.component.parameters["blocks"] == 4096

    def test_gives_each_of_the_drives_vectors_a_plic_source_of_its_own(self):
        board = host(drive_blocks=64)

        connections = json.loads(board.platform.to_json())["connections"]

        assert {
            each["source"]: each["sink"]
            for each in connections
            if each["source"].startswith("compute.msi.irq")
        } == {
            "compute.msi.irq0": f"compute.plic.source{MSI_SOURCE}",
            "compute.msi.irq1": f"compute.plic.source{MSI_SOURCE + 1}",
        }

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
