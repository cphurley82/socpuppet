"""A ROM on a platform: loaded before the first run, and read from then on.

What the model does with each kind of access is held by its contract, in
C++ (`tests/cpp/contracts/rom_contract.h`). These tests are of what a
description and a script see of it.
"""

import pytest

import socpuppet as sp

ROM_BASE = 0x1000


def master_with_a_rom(script=None):
    """A bus master with a ROM of 256 bytes at ROM_BASE on its bus."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(script))
    bus = platform.add("bus", sp.Router())
    rom = platform.add("rom", sp.Rom(size=0x100))
    platform.connect(cpu.socket, bus.target)
    bus.map(rom.socket, base=ROM_BASE)
    return platform


@pytest.mark.platform
class TestWhenARomIsPokedBeforeTheFirstRun:
    def test_its_bus_master_reads_what_was_poked(self):
        read = []

        def script():
            read.append((yield sp.read32(ROM_BASE + 0x10)))

        platform = master_with_a_rom(script)
        platform.build()
        platform.poke32(ROM_BASE + 0x10, 0xC0FFEE)

        platform.run()

        assert read == [0xC0FFEE]


@pytest.mark.platform
class TestWhenARomsBusMasterWritesToIt:
    def test_the_run_stops_with_a_bus_error_that_gives_the_address(self):
        def script():
            yield sp.write32(ROM_BASE + 0x10, 0xDEAD_BEEF)

        platform = master_with_a_rom(script)
        platform.build()

        with pytest.raises(sp.BusError, match="0x1010"):
            platform.run()


@pytest.mark.platform
class TestWhenARomIsPokedAfterItsBusMasterHasReadIt:
    def test_the_poke_is_refused_and_the_rom_keeps_what_it_had(self):
        platform = a_rom_its_master_has_read()

        with pytest.raises(PermissionError):
            platform.poke32(ROM_BASE + 0x10, 0xDEAD_BEEF)

        assert platform.peek32(ROM_BASE + 0x10) == 0xC0FFEE

    def test_the_error_names_the_rom_and_says_when_to_load_it(self):
        platform = a_rom_its_master_has_read()

        with pytest.raises(PermissionError) as refused:
            platform.poke32(ROM_BASE + 0x10, 0xDEAD_BEEF)

        assert '"rom"' in str(refused.value)
        assert "before the first run" in str(refused.value)


def a_rom_its_master_has_read():
    """A built platform whose ROM holds 0xC0FFEE at 0x10, run to its end."""

    def script():
        yield sp.read32(ROM_BASE)

    platform = master_with_a_rom(script)
    platform.build()
    platform.poke32(ROM_BASE + 0x10, 0xC0FFEE)
    platform.run()
    return platform
