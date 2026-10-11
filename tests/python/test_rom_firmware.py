"""The boot ROM's sources say where things are, and the boards say the same.

`firmware/rom` is a program with no devicetree: where its CPU has a UART,
a system controller and the top of its RAM is written in a header for each
kind of board, and where it is linked to run from is in its linker script.
Nothing in a build says so when one of those is not where a board has it.
The ROM would be silent, or would not run at all.
"""

import pathlib
import re

import pytest

from socpuppet.boards import boot, cpu_kit, host

ROM = pathlib.Path(__file__).parents[2] / "firmware/rom"
#: The header of the host, which has the one 64-bit CPU, and the header of
#: the kit every 32-bit CPU has.
FOR_THE_HOST = "board_rv64.h"
FOR_A_32_BIT_CPU = "board_rv32.h"


def defined(name, header):
    """The number a header of the ROM's defines `name` as."""
    said = re.findall(
        rf"^#define {name}\s+(0x[0-9A-Fa-f]+)$",
        (ROM / header).read_text(),
        re.MULTILINE,
    )
    assert len(said) == 1, f"{header} should define {name} once"
    return int(said[0], 16)


def linked(what):
    """A number `rom.ld` gives for the ROM's memory: ORIGIN, or LENGTH."""
    said = re.search(rf"\b{what}\s*=\s*(\w+)", (ROM / "rom.ld").read_text())
    assert said is not None, f"rom.ld gives its memory no {what}"
    number = said.group(1)
    return int(number[:-1]) * 1024 if number.endswith("K") else int(number, 0)


@pytest.fixture(autouse=True)
def the_sources_are_here():
    if not ROM.exists():
        pytest.skip(
            "The ROM's sources are not here: these tests are being run "
            "away from the source tree, against an installed socpuppet."
        )


class TestWhereTheHostsBootRomHasItsCpusThings:
    def test_the_console_is_at_the_start_of_the_io_dies_window(self):
        assert defined("UART_BASE", FOR_THE_HOST) == (
            host.IO_BASE + host.UART_OFFSET
        )

    def test_the_system_controller_is_where_every_cpu_has_it(self):
        assert defined("SYSCON_BASE", FOR_THE_HOST) == cpu_kit.SYSCON_BASE

    def test_the_stack_starts_at_the_end_of_the_ram(self):
        assert defined("STACK_TOP", FOR_THE_HOST) == (
            host.RAM_BASE + host.RAM_SIZE
        )


class TestWhereA32BitCpusBootRomHasItsCpusThings:
    def test_the_console_is_where_the_kit_has_it(self):
        assert defined("UART_BASE", FOR_A_32_BIT_CPU) == cpu_kit.UART_BASE

    def test_the_system_controller_is_where_every_cpu_has_it(self):
        assert defined("SYSCON_BASE", FOR_A_32_BIT_CPU) == cpu_kit.SYSCON_BASE

    def test_the_stack_starts_at_the_end_of_the_sram(self):
        assert defined("STACK_TOP", FOR_A_32_BIT_CPU) == (
            cpu_kit.SRAM_BASE + cpu_kit.SRAM_SIZE
        )


class TestWhereTheBootRomIsLinkedToRunFrom:
    def test_it_starts_where_a_board_puts_its_rom(self):
        assert linked("ORIGIN") == boot.ROM_BASE

    def test_it_is_no_bigger_than_the_rom_a_board_has(self):
        assert linked("LENGTH") <= boot.ROM_SIZE
