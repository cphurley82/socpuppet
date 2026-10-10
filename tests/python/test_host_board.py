"""The host platform and the Zephyr board that is generated from it."""

import json
import re

import pytest

from devicetree_compiler import dtc_errors, needs_dtc
from socpuppet.boards.cpu_kit import TIMER_HZ
from socpuppet.boards.drive import DEVICE_ID, VENDOR_ID
from socpuppet.boards.host import (
    ECAM_OFFSET,
    IO_BASE,
    MSI_SOURCE,
    drive_overlay,
    host,
)
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd
from zephyr_module import ZEPHYR_MODULE, clock_rate


class TestTheZephyrBoardForTheHost:
    def test_its_devicetree_is_what_the_host_description_generates(self):
        checked_in = (
            ZEPHYR_MODULE / "boards/socpuppet/socpuppet_host/socpuppet_host.dts"
        )

        assert checked_in.read_text() == host().platform.devicetree()

    def test_its_clock_rate_is_the_rate_the_hosts_timer_counts_at(self):
        assert clock_rate() == TIMER_HZ


class TestTheZephyrShieldForTheHostsDrive:
    def test_its_overlay_is_what_the_host_description_generates(self):
        checked_in = (
            ZEPHYR_MODULE
            / "boards/shields/socpuppet_host_drive/socpuppet_host_drive.overlay"
        )

        # When this fails, the docstring of `drive_overlay` has the command
        # that writes the file again.
        assert checked_in.read_text() == drive_overlay()

    def test_its_overlay_is_the_same_with_the_ssd_as_with_the_stand_in(self):
        # Which is why firmware built for the host with a drive runs with
        # either drive, unchanged.
        assert drive_overlay(host_with_the_ssd()) == drive_overlay()

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


class TestTheHostWithTheSsd:
    def test_has_two_cpus_the_hosts_and_the_ssds(self):
        board = host_with_the_ssd()

        assert {each.path for each in board.platform.bus_masters} == {
            "compute.cpu",
            "ssd.cpu",
        }

    def test_its_ssds_cpu_sees_the_devicetree_of_the_zephyr_board_for_the_ssd(
        self,
    ):
        # Which is why firmware built for the SSD's board runs in the SSD
        # under this host, unchanged.
        checked_in = (
            ZEPHYR_MODULE / "boards/socpuppet/socpuppet_ssd/socpuppet_ssd.dts"
        )
        board = host_with_the_ssd()

        seen = board.platform.devicetree(via=board.drive.ssd.cpu.socket)

        assert seen == checked_in.read_text()

    def test_its_cpu_sees_the_devicetree_it_sees_with_the_stand_in_drive(self):
        board = host_with_the_ssd()
        with_the_stand_in = host(drive_blocks=64)

        seen = board.platform.devicetree(via=board.cpu.socket)

        assert seen == with_the_stand_in.platform.devicetree()

    def test_its_cpu_sees_the_address_map_it_sees_with_the_stand_in_drive(self):
        board = host_with_the_ssd()
        with_the_stand_in = host(drive_blocks=64)

        seen = board.platform.address_map(via=board.cpu.socket)

        assert seen == with_the_stand_in.platform.address_map()


def host_with_the_ssd():
    """The host with the SSD.

    No test here cares how big the SSD is, and one NAND block is the
    smallest an SSD comes.
    """
    return host(drive_blocks=DRIVE_BLOCKS_PER_NAND_BLOCK, drive=add_ssd)


class TestTheHostAskedForADriveOfNoSize:
    def test_refuses_and_says_what_is_missing(self):
        with pytest.raises(ValueError, match="drive_blocks"):
            host(drive=add_ssd)


class TestTheHostWithNoDrive:
    def test_has_none(self):
        assert host().drive is None
