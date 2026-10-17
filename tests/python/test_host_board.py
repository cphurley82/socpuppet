"""The host platform and the Zephyr board that is generated from it."""

import functools
import json
import re

import pytest

from devicetree_compiler import dtc_errors, needs_dtc
from socpuppet.boards.boot import ROM_BASE, from_rom
from socpuppet.boards.cpu_kit import (
    BOOT_FLASH_BASE,
    BOOT_FLASH_CONTROLLER_BASE,
    COMPUTE_DIE,
    PLIC_BASE,
    SYSCON_BASE,
    TIMER_BASE,
    TIMER_HZ,
    WATCHDOG_BASE,
)
from socpuppet.boards.drive import DEVICE_ID, VECTORS, VENDOR_ID
from socpuppet.boards.host import (
    ECAM_OFFSET,
    IMSIC_SUPERVISOR_BASE,
    IO_BASE,
    IO_SIZE,
    RAM_BASE,
    UART_SOURCE,
    WATCHDOG_SOURCE,
    drive_overlay,
    host,
)
from socpuppet.boards.manager import add_manager, stand_in_manager
from socpuppet.boards.ssd import DRIVE_BLOCKS_PER_NAND_BLOCK, add_ssd
from socpuppet.boards.virtio import (
    VIRTIO_FIRST_SOURCE,
    VIRTIO_SLOT_OFFSET,
    Virtio,
    virtio_overlay,
)
from socpuppet.components import (
    Aplic,
    Imsic,
    MachineTimer,
    SystemController,
    Watchdog,
)
from socpuppet.interrupt_map import InterruptEntry
from wiring import what_drives
from zephyr_module import (
    ZEPHYR_MODULE,
    clock_rate,
    the_identities_of_the_hosts_drive,
)


class TestTheZephyrBoardForTheHost:
    def test_its_devicetree_is_what_the_host_description_generates(self):
        checked_in = (
            ZEPHYR_MODULE / "boards/socpuppet/socpuppet_host/socpuppet_host.dts"
        )

        assert checked_in.read_text() == host().platform.devicetree()

    def test_its_clock_rate_is_the_rate_the_hosts_timer_counts_at(self):
        assert clock_rate() == TIMER_HZ


class TestTheHostsCpu:
    def test_is_rv64gc_with_supervisor_and_user_mode(self):
        cpu = host().cpu.component

        assert (cpu.xlen, cpu.isa, cpu.modes) == (64, "gc", "msu")


class TestTheHostsTimer:
    def test_is_at_the_address_every_socpuppet_cpu_has_its_timer_at(self):
        [timer] = [
            each
            for each in host().platform.address_map()
            if each.implementation == MachineTimer.implementation
        ]

        assert timer.address == TIMER_BASE


class TestTheHostsSystemController:
    def test_is_at_the_address_every_socpuppet_cpu_has_its_system_controller_at(
        self,
    ):
        [syscon] = [
            each
            for each in host().platform.address_map()
            if each.implementation == SystemController.implementation
        ]

        assert syscon.address == SYSCON_BASE

    def test_is_all_that_drives_the_cpus_reset(self):
        board = host()

        assert what_drives(board.platform, board.cpu.reset) == [
            board.syscon.reset.path
        ]

    def test_holds_the_cpu_for_nothing_when_the_host_has_no_manager(self):
        # 🎭 The stand-in link is up from the start, so there is nothing
        # to wait for.
        board = host()

        assert what_drives(board.platform, board.syscon.hold) == []

    def test_says_its_cpu_is_on_the_compute_die(self):
        assert host().syscon.component.die == COMPUTE_DIE

    def test_tells_the_boot_rom_to_look_where_every_socpuppet_cpu_has_its_flash(
        self,
    ):
        assert host().syscon.component.boot_address == BOOT_FLASH_BASE


class TestTheHostsWatchdog:
    def test_is_beside_the_system_controller_where_every_socpuppet_cpu_has_one(
        self,
    ):
        [wdt] = [
            each
            for each in host().platform.address_map()
            if each.implementation == Watchdog.implementation
        ]

        assert wdt.address == WATCHDOG_BASE

    def test_bites_the_system_controller_which_is_what_resets_the_cpu(self):
        board = host()

        assert what_drives(board.platform, board.syscon.bite) == [
            board.wdt.bite.path
        ]

    def test_interrupts_through_the_aplic_on_its_own_die(self):
        # A wire stays on its die, and the watchdog is on the CPU's.
        board = host()

        assert (
            InterruptEntry("compute.aplic", WATCHDOG_SOURCE, "compute.wdt.irq")
            in board.platform.interrupt_map()
        )


class TestTheHostAsItIsByDefault:
    def test_starts_its_cpu_in_its_ram_and_has_no_rom(self):
        # 🎭 Python is the boot ROM's stand-in: it puts the image in RAM.
        board = host()

        assert board.cpu.component.reset_vector == RAM_BASE
        assert board.rom is None


class TestTheHostDescribedToBootFromARom:
    def test_starts_its_cpu_in_a_rom_on_its_own_die(self):
        board = host(boot=from_rom)
        [rom] = [
            each
            for each in board.platform.address_map()
            if each.component == board.rom.path
        ]

        assert board.cpu.component.reset_vector == rom.address
        assert rom.group == "compute"

    def test_has_its_rom_where_a_boot_rom_is_linked_to_run(self):
        board = host(boot=from_rom)
        [rom] = [
            each
            for each in board.platform.address_map()
            if each.component == board.rom.path
        ]

        assert rom.address == ROM_BASE

    def test_shows_its_firmware_the_devicetree_the_host_always_has(self):
        # Which is why one image boots either way: firmware is not told
        # of the ROM that started it.
        assert (
            host(boot=from_rom).platform.devicetree()
            == host().platform.devicetree()
        )


class TestTheHostsBootFlash:
    def test_is_on_the_io_die_and_so_in_its_window(self):
        board = host()
        window = the_boot_flash_as_seen_by(board.cpu.socket, board)

        assert window.group == "io"
        assert IO_BASE <= window.address < IO_BASE + IO_SIZE

    def test_is_at_the_address_every_socpuppet_cpu_has_its_boot_flash_at(self):
        board = host()

        assert (
            the_boot_flash_as_seen_by(board.cpu.socket, board).address
            == BOOT_FLASH_BASE
        )

    def test_is_read_where_the_cpus_system_controller_says_to_boot_from(self):
        board = host()
        window = the_boot_flash_as_seen_by(board.cpu.socket, board)

        assert (
            window.address
            <= board.syscon.component.boot_address
            < (window.address + window.size)
        )

    def test_has_its_controllers_registers_where_every_socpuppet_cpu_has_them(
        self,
    ):
        board = host()
        [registers] = [
            each
            for each in board.platform.address_map()
            if each.component == board.boot_flash.path and each.port == "socket"
        ]

        assert registers.address == BOOT_FLASH_CONTROLLER_BASE


def the_boot_flash_as_seen_by(master, board):
    """The window of the host's boot flash in a bus master's address map."""
    [window] = [
        each
        for each in board.platform.address_map(via=master)
        if each.component == board.boot_flash.path and each.port == "xip"
    ]
    return window


class TestTheHostsInterruptController:
    def test_is_an_imsic_with_a_page_for_each_mode_where_qemus_virt_has_them(
        self,
    ):
        pages = {
            each.port: each.address
            for each in host().platform.address_map()
            if each.implementation == Imsic.implementation
        }

        # VIRT_IMSIC_M and VIRT_IMSIC_S in QEMU's hw/riscv/virt.c.
        assert pages == {"machine": 0x2400_0000, "supervisor": 0x2800_0000}


class TestTheHostsConsole:
    def test_its_interrupt_line_goes_to_an_aplic_on_its_own_die(self):
        # A wire cannot cross to the compute die, so the UART's stops at
        # an APLIC beside it, which sends a message for it.
        board = host()

        assert (
            InterruptEntry("io.aplic", UART_SOURCE, "io.uart.irq")
            in board.platform.interrupt_map()
        )

    def test_its_aplic_is_on_the_io_die_and_so_in_its_window(self):
        aplic = the_hosts_aplic_on("io")

        assert IO_BASE <= aplic.address < IO_BASE + IO_SIZE


class TestTheHostsAplics:
    """🎓 A wire stays on its die, so each die with a device that only has
    a wire has an APLIC of its own to send a message for it."""

    def test_there_is_one_on_each_die(self):
        assert sorted(each.group for each in the_hosts_aplics()) == [
            "compute",
            "io",
        ]

    def test_the_compute_dies_is_at_the_address_a_socpuppet_cpu_has_its_wired_interrupt_controller_at(
        self,
    ):
        # Which is where QEMU's `virt` machine has its APLIC, and where a
        # 32-bit socpuppet CPU has its PLIC.
        assert the_hosts_aplic_on("compute").address == PLIC_BASE

    def test_the_devicetree_names_the_imsic_as_where_the_messages_of_each_go(
        self,
    ):
        # It names where they go only if they get there, and at the
        # address the CPU has the page at.
        devicetree = host().platform.devicetree()

        for label in ("compute_aplic", "io_aplic"):
            assert "msi-parent = <&compute_imsic>;" in node_of(
                label, devicetree
            )

    def test_no_number_is_a_source_with_a_line_on_it_at_both(self):
        # Firmware knows an interrupt by one number, and finds the APLIC
        # for a number by which one has a device's line at that source.
        aplics = {each.component for each in the_hosts_aplics()}
        wired = [
            entry.number
            for entry in host().platform.interrupt_map()
            if entry.controller in aplics
        ]

        assert sorted(wired) == sorted(set(wired))


class TestTheHostDescribedForAMonitor:
    """🎓 With `sbi=True` the host is described for firmware that is a
    monitor in machine mode with an operating system below it, as OpenSBI
    is with Linux. Neither says where an APLIC that serves the operating
    system sends its messages: that is the platform's to know."""

    def test_both_its_aplics_send_to_the_supervisors_page(self):
        board = host(sbi=True)

        assert where_the_aplics_send(board) == {
            "compute": IMSIC_SUPERVISOR_BASE,
            "io": IMSIC_SUPERVISOR_BASE,
        }

    def test_without_it_neither_aplic_is_told(self):
        # Zephyr's driver says where, when it reads that nobody has.
        assert where_the_aplics_send(host()) == {"compute": 0, "io": 0}


#: More RAM than the host has unless it is told: Linux with its files in
#: memory wants more than 64 MiB.
MORE_RAM = 128 * 1024 * 1024


class TestTheHostsDevicetreeForLinux:
    @needs_dtc
    def test_the_devicetree_compiler_accepts_it(self, tmp_path):
        devicetree = host(sbi=True).platform.devicetree(dialect="linux")

        assert dtc_errors(devicetree, tmp_path) == ""

    def test_both_aplics_send_to_the_supervisors_imsic_node(self):
        devicetree = host(sbi=True).platform.devicetree(dialect="linux")

        for label in ("compute_aplic", "io_aplic"):
            assert "msi-parent = <&compute_imsic_s>;" in node_of(
                label, devicetree
            )


class TestTheHostDescribedWithMoreRam:
    def test_its_ram_is_that_size(self):
        [ram] = [
            each
            for each in host(ram=MORE_RAM).platform.address_map()
            if each.component == "compute.ram"
        ]

        assert ram.size == MORE_RAM

    def test_its_memory_node_says_how_much(self):
        devicetree = host(ram=MORE_RAM).platform.devicetree()

        assert f"reg = <0x0 {RAM_BASE:#x} 0x0 {MORE_RAM:#x}>;" in node_of(
            "compute_ram", devicetree
        )

    def test_less_than_64_mib_is_refused_with_a_rom(self):
        # The ROM keeps its stack at the top of the RAM it was written for.
        with pytest.raises(ValueError, match="64 MiB"):
            host(boot=from_rom, ram=32 * 1024 * 1024)


def where_the_aplics_send(board):
    """Where each of a host's APLICs is configured to send, by its die."""
    components = json.loads(board.platform.to_json())["components"]
    return {
        die: components[f"{die}.aplic"]["parameters"]["messages_to"]
        for die in ("compute", "io")
    }


def the_hosts_aplics():
    """The host's APLICs, as its CPU's address map has them."""
    return [
        each
        for each in host().platform.address_map()
        if each.implementation == Aplic.implementation
    ]


def the_hosts_aplic_on(die):
    """The one APLIC the host has on a die, as its CPU's address map has it."""
    [aplic] = [each for each in the_hosts_aplics() if each.group == die]
    return aplic


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

    def test_its_overlay_sends_the_root_complexs_messages_to_the_imsic(self):
        assert "msi-parent = <&compute_imsic>;" in drive_overlay()

    def test_its_overlay_sets_an_identity_aside_for_each_of_the_drives_vectors(
        self,
    ):
        # A message is an identity written to the IMSIC's page, and no
        # device comes with one. The board says which are the drive's, so
        # that what it leaves free for other things stays free.
        identities = the_identities_of_the_hosts_drive()

        assert len(identities) == VECTORS
        assert len(set(identities)) == VECTORS

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
    def test_the_ones_to_the_cpu_are_the_timers_and_the_imsics_two(self):
        # Every other interrupt comes as a message, to the IMSIC, the
        # drive's among them.
        board = host(drive_blocks=64)

        to_the_cpu = [
            each
            for each in board.platform.interrupt_map()
            if each.controller == board.cpu.path
        ]

        assert to_the_cpu == [
            InterruptEntry("compute.cpu", 7, "compute.timer.irq"),
            InterruptEntry("compute.cpu", 9, "compute.imsic.supervisor_irq"),
            InterruptEntry("compute.cpu", 11, "compute.imsic.irq"),
        ]

    def test_none_is_to_a_plic(self):
        # What makes a node a PLIC to firmware is what it is compatible
        # with, and the SoC's Kconfig looks for exactly this.
        devicetree = host(drive_blocks=64).platform.devicetree()

        assert 'compatible = "sifive,plic-1.0.0"' not in devicetree

    def test_each_stays_on_the_die_it_starts_on(self):
        # A die-to-die link carries transactions and messages, and no
        # wires. The drive's interrupts have to cross it, so they are
        # sent as messages, and stay messages until the IMSIC. The SSD
        # has lines of its own, on its own side of the PCIe link.
        board = host_with_the_ssd()

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
    def test_its_end_of_the_link_holds_its_cpu_through_the_system_controller(
        self,
    ):
        # A wire has one driver, and the CPU's reset has the system
        # controller for its own. So the link's end holds the CPU by a
        # line to the controller. What the line does can only be seen in
        # a run.
        board = host_with_a_manager()

        assert what_drives(board.platform, board.syscon.hold) == [
            board.link.a.reset.path
        ]
        assert what_drives(board.platform, board.cpu.reset) == [
            board.syscon.reset.path
        ]

    def test_its_manager_reaches_the_links_registers_and_shares_only_the_flash_with_its_cpu(
        self,
    ):
        # The manager has a bus of its own, as the management side of a
        # real IO die has. The one thing on both is the flash the two of
        # them boot from.
        board = host_with_a_manager()

        the_managers = ports_reached(board, via=board.manager.cpu.socket)
        the_cpus = ports_reached(board, via=board.cpu.socket)

        assert board.link.b.sideband.path in the_managers
        assert the_managers & the_cpus == {board.boot_flash.xip.path}

    def test_its_manager_finds_the_flash_where_its_cpu_does(self):
        # One flash, two CPUs, one address: each one's boot ROM looks in
        # the same place, further in or not.
        board = host_with_a_manager()

        assert (
            the_boot_flash_as_seen_by(board.manager.cpu.socket, board).address
            == the_boot_flash_as_seen_by(board.cpu.socket, board).address
        )

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


class TestTheHostWithAManagerThatHasACpu:
    def test_has_two_cpus_the_hosts_and_the_managers(self):
        board = host(manager=add_manager)

        assert {each.path for each in board.platform.bus_masters} == {
            "compute.cpu",
            "io.manager.cpu",
        }

    def test_its_two_cpus_are_told_they_are_on_different_dies(self):
        board = host(manager=add_manager)

        assert (
            board.syscon.component.die
            != board.manager.cpu_kit.syscon.component.die
        )

    def test_its_manager_is_told_to_boot_from_inside_the_flash_too(self):
        board = host(manager=add_manager)
        window = the_boot_flash_as_seen_by(board.manager.cpu.socket, board)
        boot_address = board.manager.cpu_kit.syscon.component.boot_address

        assert window.address <= boot_address < window.address + window.size

    def test_its_manager_boots_from_further_into_the_flash_than_its_cpu(self):
        # One flash holds both images, the host's first.
        board = host(manager=add_manager)

        assert (
            board.manager.cpu_kit.syscon.component.boot_address
            > board.syscon.component.boot_address
        )

    def test_its_managers_cpu_sees_the_zephyr_board_for_the_manager_less_its_scratch_memory(
        self,
    ):
        # Which is why firmware built for the manager's board runs in the
        # manager under this host, unchanged. Two things differ, and the
        # firmware is built from neither. The board has a scratch memory
        # for 🎭 its compute die to reach. And under the host the manager
        # is in a group of its own, which shows in its nodes' labels.
        checked_in = (
            ZEPHYR_MODULE
            / "boards/socpuppet/socpuppet_iomgr/socpuppet_iomgr.dts"
        ).read_text()
        board = host(manager=add_manager)

        seen = board.platform.devicetree(via=board.manager.cpu.socket)

        assert labelled_as_in_group("io", seen, was="io_manager") == (
            without_node("io_scratch", checked_in)
        )


def labelled_as_in_group(group, devicetree, was):
    """`devicetree` as it reads with its devices in another group.

    A node's label starts with the group its device is in, and nothing
    firmware is built from says the label: it finds a device by what the
    device is compatible with.
    """
    return devicetree.replace(f"{was}_", f"{group}_")


def without_node(label, devicetree):
    """`devicetree` with the node called `label` taken out."""
    lines, start, end = _span_of_node(label, devicetree)
    # The empty line after a node goes with it.
    if lines[end : end + 1] == ["\n"]:
        end += 1
    return "".join(lines[:start] + lines[end:])


def node_of(label, devicetree):
    """The node called `label` in `devicetree`, from its label to its brace."""
    lines, start, end = _span_of_node(label, devicetree)
    return "".join(lines[start:end])


def _span_of_node(label, devicetree):
    """The lines of `devicetree`, and where the node called `label` is in them."""
    lines = devicetree.splitlines(keepends=True)
    starts = [
        at
        for at, line in enumerate(lines)
        if line.lstrip().startswith(f"{label}:")
    ]
    assert len(starts) == 1, f"There should be one node called {label}."
    [start] = starts
    indent = lines[start][: -len(lines[start].lstrip())]
    end = lines.index(f"{indent}}};\n", start) + 1
    return lines, start, end


class TestTheHostAskedForADriveOfNoSize:
    def test_refuses_and_says_what_is_missing(self):
        with pytest.raises(ValueError, match="drive_blocks"):
            host(drive=add_ssd)


class TestTheHostWithNoDrive:
    def test_has_none(self):
        assert host().drive is None


class TestTheHostsVirtioSlots:
    def test_are_not_on_the_host_unless_asked_for(self):
        # So the board's devicetree, and every image built for it, stay as
        # they were.
        assert host().virtio is None

    def test_the_entropy_device_is_in_the_first_slot_in_the_io_window(self):
        board = host(virtio=Virtio())
        [slot] = [
            each
            for each in board.platform.address_map(via=board.cpu.socket)
            if each.component == board.virtio.rng.path
        ]

        assert slot.address == IO_BASE + VIRTIO_SLOT_OFFSET

    def test_the_entropy_device_interrupts_through_the_aplic_on_its_own_die(
        self,
    ):
        board = host(virtio=Virtio())

        assert (
            InterruptEntry("io.aplic", VIRTIO_FIRST_SOURCE, "io.rng.irq")
            in board.platform.interrupt_map()
        )

    def test_the_entropy_devices_dma_reaches_the_ram(self):
        board = host(virtio=Virtio())
        reached = board.platform.address_map(via=board.virtio.rng.dma)

        assert [
            each.address for each in reached if each.component == "compute.ram"
        ] == [RAM_BASE]

    def test_the_zephyr_shield_for_the_slots_has_what_the_host_generates(self):
        checked_in = (
            ZEPHYR_MODULE
            / "boards/shields/socpuppet_host_virtio/socpuppet_host_virtio.overlay"
        )

        # When this fails, the docstring of `virtio_overlay` has the command
        # that writes the file again.
        assert checked_in.read_text() == virtio_overlay()

    @needs_dtc
    def test_the_devicetree_compiler_accepts_the_host_with_the_slots(
        self, tmp_path
    ):
        board = host(virtio=Virtio(), sbi=True)

        assert dtc_errors(board.platform.devicetree(), tmp_path) == ""
        assert (
            dtc_errors(board.platform.devicetree(dialect="linux"), tmp_path)
            == ""
        )
