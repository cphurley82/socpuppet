"""The SSD as a board: how it is described, before anything is simulated."""

import json
import pathlib

import pytest

import socpuppet as sp
from devicetree_compiler import dtc_errors, needs_dtc
from processes import run_socpuppet
from socpuppet.boards import ssd as boards_ssd
from socpuppet.boards.cpu_kit import SRAM_BASE
from socpuppet.boards.drive import DEVICE_ID, NVME_CLASS, VENDOR_ID
from socpuppet.boards.scripted_host import ECAM_BASE, idle_host
from socpuppet.boards.ssd import (
    DMA_SOURCE,
    FLASH_SOURCE,
    FRONTEND_SOURCE,
    ssd,
    stand_in_firmware,
)
from socpuppet.pcie_host import PcieFunction
from zephyr_module import ZEPHYR_MODULE, clock_rate

SSD_BOARD = ZEPHYR_MODULE / "boards/socpuppet/socpuppet_ssd"
SSD_DESCRIPTION = pathlib.Path(boards_ssd.__file__)


class TestTheZephyrBoardForTheSsd:
    # The firmware's view of the SSD is its own CPU's: the host is not in
    # it. The command is the one that writes the file again.
    def test_its_devicetree_is_what_the_devicetree_command_prints(self):
        printed = run_socpuppet(
            "devicetree", str(SSD_DESCRIPTION), "--via", "ssd.cpu.socket"
        ).stdout

        assert (SSD_BOARD / "socpuppet_ssd.dts").read_text() == printed

    def test_its_clock_rate_is_the_rate_the_ssds_timer_counts_at(self):
        timer = ssd(host=idle_host).ssd.cpu_kit.timer.component

        assert clock_rate() == timer.parameters["frequency_hz"]

    @needs_dtc
    def test_the_devicetree_compiler_accepts_it(self, tmp_path):
        board = (SSD_BOARD / "socpuppet_ssd.dts").read_text()

        assert dtc_errors(board, tmp_path) == ""


class TestAnSsdOfSoManyBlocks:
    # A NAND page is eight of the drive's blocks, and 64 pages make a NAND
    # block: 512 of the drive's blocks.
    def test_has_a_nand_of_that_many_blocks_in_whole_nand_blocks(self):
        board = ssd(
            host=idle_host, blocks=2048, firmware=stand_in_firmware().script
        )

        assert board.ssd.nand.component.parameters == {
            "blocks": 4,
            "pages_per_block": 64,
            "page_size": 4096,
        }

    @pytest.mark.parametrize("blocks", [100, 513])
    def test_is_refused_if_that_is_not_whole_nand_blocks(self, blocks):
        with pytest.raises(
            ValueError, match=rf"\b{blocks} blocks were asked for"
        ) as refused:
            ssd(
                host=idle_host,
                blocks=blocks,
                firmware=stand_in_firmware().script,
            )

        assert "512, or a multiple of it" in str(refused.value)

    def test_is_refused_if_that_is_no_blocks_at_all(self):
        with pytest.raises(ValueError, match="at least one"):
            ssd(host=idle_host, blocks=0, firmware=stand_in_firmware().script)


class TestAnSsdWithNoScriptForItsFirmware:
    # It has a CPU of its own, and what a CPU needs.

    def test_has_a_32_bit_cpu_that_starts_at_the_start_of_its_sram(self):
        cpu = ssd(host=idle_host).ssd.cpu.component

        assert isinstance(cpu, sp.DbtRiseCpu)
        assert cpu.parameters["xlen"] == 32
        assert cpu.parameters["reset_vector"] == SRAM_BASE

    def test_gives_its_cpu_the_gdb_port_asked_for(self):
        board = ssd(host=idle_host, gdb_port=1234)

        assert board.ssd.cpu.component.parameters["gdb_port"] == 1234

    def test_has_an_sram_a_uart_a_timer_and_an_interrupt_controller(self):
        kit = ssd(host=idle_host).ssd.cpu_kit

        assert isinstance(kit.sram.component, sp.Memory)
        assert isinstance(kit.uart.component, sp.Ns16550)
        assert isinstance(kit.timer.component, sp.MachineTimer)
        assert isinstance(kit.plic.component, sp.Plic)

    def test_gives_each_of_its_three_devices_a_plic_source_of_its_own(self):
        board = ssd(host=idle_host)

        connections = json.loads(board.platform.to_json())["connections"]

        assert {
            each["source"]: each["sink"]
            for each in connections
            if each["sink"].startswith("ssd.plic.source")
        } == {
            "ssd.frontend.cpu_irq": f"ssd.plic.source{FRONTEND_SOURCE}",
            "ssd.dma.irq": f"ssd.plic.source{DMA_SOURCE}",
            "ssd.flash.irq": f"ssd.plic.source{FLASH_SOURCE}",
        }
        assert len({FRONTEND_SOURCE, DMA_SOURCE, FLASH_SOURCE}) == 3

    def test_sends_the_plic_and_the_timer_to_the_cpu(self):
        board = ssd(host=idle_host)

        connections = json.loads(board.platform.to_json())["connections"]

        assert {
            each["sink"]: each["source"]
            for each in connections
            if each["sink"].startswith("ssd.cpu.")
        } == {
            "ssd.cpu.irq": "ssd.plic.irq",
            "ssd.cpu.timer_irq": "ssd.timer.irq",
        }


class TestAnSsdWithAScriptForItsFirmware:
    # 🎭 The script is in the CPU's place, and needs none of what a CPU
    # does: the frontend's line goes straight to it.

    def test_has_the_script_where_its_cpu_would_be_and_no_cpu_kit(self):
        board = ssd(host=idle_host, firmware=stand_in_firmware().script)

        assert isinstance(board.ssd.cpu.component, sp.ScriptedBusMaster)
        assert board.ssd.cpu_kit is None

    def test_is_refused_a_gdb_port_and_told_there_is_no_cpu_to_debug(self):
        with pytest.raises(ValueError, match=r"gdb_port=1234") as refused:
            ssd(
                host=idle_host,
                firmware=stand_in_firmware().script,
                gdb_port=1234,
            )

        assert "a debugger attaches to a CPU" in str(refused.value)


@pytest.mark.platform
class TestWhenAHostScansThePcieBusTheSsdIsOn:
    # So that a host, and its driver, cannot tell the two apart by looking.
    def test_it_finds_what_the_stand_in_drive_says_it_is(self):
        found = []

        def host():
            found.extend((yield from sp.PcieHost(ecam=ECAM_BASE).scan()))

        board = ssd(host=host, firmware=stand_in_firmware().script)
        board.platform.build()

        board.platform.run()

        assert found == [
            PcieFunction(
                bus=0,
                device=0,
                function=0,
                vendor_id=VENDOR_ID,
                device_id=DEVICE_ID,
                class_code=NVME_CLASS,
            )
        ]


class TestTheScriptedHostInFrontOfTheSsd:
    # So that a script written for one host finds its way around the other.
    def test_has_its_devices_where_the_real_host_board_has_them(self):
        from socpuppet.boards import host, scripted_host

        assert scripted_host.RAM_BASE == host.RAM_BASE
        assert scripted_host.MSI_BASE == host.MSI_BASE
        assert scripted_host.ECAM_BASE == host.IO_BASE + host.ECAM_OFFSET
        assert (
            scripted_host.PCIE_WINDOW_BASE
            == host.IO_BASE + host.PCIE_WINDOW_OFFSET
        )
