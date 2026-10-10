"""The host platform and the Zephyr board that is generated from it."""

import functools
import json
import re

import pytest

from devicetree_compiler import dtc_errors, needs_dtc
from socpuppet.boards.cpu_kit import TIMER_BASE, TIMER_HZ
from socpuppet.boards.drive import DEVICE_ID, VENDOR_ID
from socpuppet.boards.host import (
    ECAM_OFFSET,
    IO_BASE,
    MSI_SOURCE,
    drive_overlay,
    host,
)
from socpuppet.boards.io_manager import add_manager, stand_in_manager
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd
from socpuppet.components import MachineTimer
from zephyr_module import ZEPHYR_MODULE, clock_rate


class TestTheZephyrBoardForTheHost:
    def test_its_devicetree_is_what_the_host_description_generates(self):
        checked_in = (
            ZEPHYR_MODULE / "boards/socpuppet/socpuppet_host/socpuppet_host.dts"
        )

        assert checked_in.read_text() == host().platform.devicetree()

    def test_its_clock_rate_is_the_rate_the_hosts_timer_counts_at(self):
        assert clock_rate() == TIMER_HZ


class TestTheHostsTimer:
    def test_is_at_the_address_every_socpuppet_cpu_has_its_timer_at(self):
        [timer] = [
            each
            for each in host().platform.address_map()
            if each.implementation == MachineTimer.implementation
        ]

        assert timer.address == TIMER_BASE


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


class TestTheInterruptLinesOfTheHostWithADrive:
    def test_each_stays_on_the_die_it_starts_on(self):
        # A die-to-die link carries transactions and messages, and no
        # wires. The drive's interrupts have to cross it, so they are
        # sent as messages and become lines on the compute die.
        board = host(drive_blocks=64)

        crossing = [
            each
            for each in board.platform.interrupt_map()
            if die_of(each.line) != die_of(each.controller)
        ]

        assert crossing == []


def die_of(path):
    """The die a component or a port is on: `compute` of `compute.cpu`."""
    return path.split(".")[0]


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


class TestTheHostWithAManager:
    def test_its_cpu_takes_its_reset_from_its_end_of_the_link(self):
        # This is that the line comes from the link and from nowhere
        # else. What the line does can only be seen in a run.
        board = host_with_a_manager()

        connections = json.loads(board.platform.to_json())["connections"]

        assert (board.link.a.reset.path, board.cpu.reset.path) in [
            (each["source"], each["sink"]) for each in connections
        ]

    def test_its_manager_reaches_the_links_registers_and_nothing_its_cpu_does(
        self,
    ):
        # The manager has a bus of its own, as the management side of a
        # real IO die has.
        board = host_with_a_manager()

        the_managers = ports_reached(board, via=board.manager.cpu.socket)
        the_cpus = ports_reached(board, via=board.cpu.socket)

        assert board.link.b.sideband.path in the_managers
        assert the_managers & the_cpus == set()

    def test_its_cpu_sees_the_devicetree_it_sees_with_no_manager(self):
        # Which is why firmware built for the host runs across the real
        # link, unchanged.
        board = host_with_a_manager()

        seen = board.platform.devicetree(via=board.cpu.socket)

        assert seen == host().platform.devicetree()

    @pytest.mark.platform
    def test_can_be_built_with_a_drive_that_its_cpu_then_finds(self):
        # A root complex is told where its memory window is when the
        # platform is built, and a platform refuses to say where a port
        # is when two bus masters find it at different addresses.
        board = host_with_a_manager(drive_blocks=64)
        board.platform.build()

        ids = board.platform.peek32(IO_BASE + ECAM_OFFSET, via=board.cpu.socket)

        assert ids == DEVICE_ID << 16 | VENDOR_ID


def ports_reached(board, via):
    """The paths of the ports that answer a master: `io.uart.socket`."""
    return {
        f"{each.component}.{each.port}"
        for each in board.platform.address_map(via=via)
    }


def host_with_a_manager(drive_blocks=None):
    """The host with 🎭 the script for a manager on its IO die."""
    return host(
        drive_blocks=drive_blocks,
        manager=functools.partial(
            add_manager, script=stand_in_manager().script
        ),
    )


class TestTheHostAskedForADriveOfNoSize:
    def test_refuses_and_says_what_is_missing(self):
        with pytest.raises(ValueError, match="drive_blocks"):
            host(drive=add_ssd)


class TestTheHostWithNoDrive:
    def test_has_none(self):
        assert host().drive is None
