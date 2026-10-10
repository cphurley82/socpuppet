"""🧦 The IO-die manager board: what is where, and what reaches what."""

import json
import pathlib

import pytest

from devicetree_compiler import dtc_errors, needs_dtc
from processes import run_socpuppet
from socpuppet.boards import io_manager as boards_io_manager
from socpuppet.boards.cpu_kit import SRAM_BASE
from socpuppet.boards.io_manager import (
    LINK_SOURCE,
    RAM_BASE,
    SCRATCH_BASE,
    io_manager,
    stand_in_manager,
)
from zephyr_module import ZEPHYR_MODULE, clock_rate

IOMGR_BOARD = ZEPHYR_MODULE / "boards/socpuppet/socpuppet_iomgr"
IOMGR_DESCRIPTION = pathlib.Path(boards_io_manager.__file__)


def nothing():
    """🎭 A compute die that does nothing at all."""
    yield from ()


def a_board_with_a_scripted_manager():
    """The board with 🎭 a script in the manager's place and an idle die."""
    return io_manager(compute=nothing, manager=stand_in_manager().script)


class TestWhenTheBoardIsDescribed:
    def test_the_compute_dies_cpu_takes_its_reset_from_its_end_of_the_link(
        self,
    ):
        # What that reset does is tested where it can be seen: the compute
        # die reaches nothing until the manager lets it go
        # (test_io_manager.py, test_m5a_exit.py). This is that the line
        # comes from the link and from nowhere else.
        board = a_board_with_a_scripted_manager()

        connections = json.loads(board.platform.to_json())["connections"]

        assert (
            board.link.a.reset.path,
            board.compute.reset.path,
        ) in [(one["source"], one["sink"]) for one in connections]


@pytest.mark.platform
class TestWhenTheBoardIsBuilt:
    def test_both_dies_reach_the_scratch_at_the_same_address(self):
        board = a_board_with_a_scripted_manager()
        board.platform.build()

        board.platform.poke32(SCRATCH_BASE, 0x5EED, via=board.manager.socket)

        assert (
            board.platform.peek32(SCRATCH_BASE, via=board.compute.socket)
            == 0x5EED
        )

    def test_the_compute_dies_memory_is_its_own_and_not_the_other_dies(self):
        board = a_board_with_a_scripted_manager()
        board.platform.build()

        board.platform.poke32(RAM_BASE, 0x5EED, via=board.compute.socket)

        # The window onto the IO die stops below the compute die's memory,
        # so the manager's bus has nothing at that address at all.
        with pytest.raises(LookupError):
            board.platform.peek32(RAM_BASE, via=board.manager.socket)


class TestWhenTheManagerIsARealCpu:
    def test_it_is_a_32_bit_core_that_starts_in_the_sram(self):
        board = io_manager(compute=nothing)

        assert board.manager.component.parameters == {
            "xlen": 32,
            "reset_vector": SRAM_BASE,
            "gdb_port": 0,
        }

    def test_it_has_the_kit_every_socpuppet_cpu_has(self):
        board = io_manager(compute=nothing)

        assert board.cpu_kit is not None

    def test_the_links_line_is_on_a_source_of_its_interrupt_controller(self):
        board = io_manager(compute=nothing)

        connections = json.loads(board.platform.to_json())["connections"]

        assert ("io.d2d.irq", f"io.plic.source{LINK_SOURCE}") in [
            (one["source"], one["sink"]) for one in connections
        ]


class TestTheZephyrBoardForTheManager:
    # The firmware's view is the manager's own CPU's: the compute die is
    # not in it. The command is the one that writes the file again.
    def test_its_devicetree_is_what_the_devicetree_command_prints(self):
        printed = run_socpuppet(
            "devicetree", str(IOMGR_DESCRIPTION), "--via", "io.cpu.socket"
        ).stdout

        assert (IOMGR_BOARD / "socpuppet_iomgr.dts").read_text() == printed

    def test_its_clock_rate_is_the_rate_the_managers_timer_counts_at(self):
        kit = io_manager(compute=nothing).cpu_kit
        assert kit is not None

        assert clock_rate() == kit.timer.component.parameters["frequency_hz"]

    @needs_dtc
    def test_the_devicetree_compiler_accepts_it(self, tmp_path):
        board = (IOMGR_BOARD / "socpuppet_iomgr.dts").read_text()

        assert dtc_errors(board, tmp_path) == ""
