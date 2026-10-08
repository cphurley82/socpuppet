import contextlib

import pytest

import socpuppet as sp
from scripts import writing
from socpuppet.trace import wants_color

RAM_BASE = 0x8000_0000
UNMAPPED = 0x4000


def routed_platform(writes):
    """A scripted master in front of a router with one RAM at RAM_BASE."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(writing(writes)))
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=0x100))
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    return platform


@pytest.mark.platform
class TestWhenAMasterWritesToAMappedAddress:
    def test_peek_at_that_address_returns_the_value(self):
        platform = routed_platform(writes=[(RAM_BASE + 0x10, 0xC0FFEE)])
        platform.build()

        platform.run()

        assert platform.peek32(RAM_BASE + 0x10) == 0xC0FFEE


@pytest.mark.platform
class TestWhenAMasterOnAnotherInputOfTheRouterWritesToAMappedAddress:
    def test_the_first_master_finds_the_write_at_that_address(self):
        platform = sp.Platform()
        first = platform.add("first", sp.ScriptedBusMaster())
        second = platform.add(
            "second",
            sp.ScriptedBusMaster(writing([(RAM_BASE + 0x10, 0xC0FFEE)])),
        )
        bus = platform.add("bus", sp.Router())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(first.socket, bus.target)
        platform.connect(second.socket, bus.add_input())
        bus.map(ram.socket, base=RAM_BASE)
        platform.build()

        platform.run()

        assert platform.peek32(RAM_BASE + 0x10, via=first.socket) == 0xC0FFEE


@pytest.mark.platform
class TestWhenAMasterWritesToAnAddressNothingIsMappedAt:
    # The router logs the miss, and the master then stops the run.
    def test_a_warning_naming_the_address_is_logged(self, capfd):
        platform = routed_platform(writes=[(UNMAPPED, 1)])
        platform.build()

        with contextlib.suppress(sp.BusError):
            platform.run()

        assert f"{UNMAPPED:#x}" in capfd.readouterr().out

    def test_the_log_carries_no_color_codes_when_output_is_not_a_terminal(
        self, capfd
    ):
        platform = routed_platform(writes=[(UNMAPPED, 1)])
        platform.build()

        with contextlib.suppress(sp.BusError):
            platform.run()

        assert "\x1b[" not in capfd.readouterr().out


class TestWhenOutputGoesToATerminal:
    def test_the_log_is_colored(self):
        assert wants_color(is_terminal=True, environment={})

    def test_the_log_is_not_colored_if_no_color_is_set(self):
        assert not wants_color(is_terminal=True, environment={"NO_COLOR": "1"})


class TestWhenOutputDoesNotGoToATerminal:
    def test_the_log_is_not_colored(self):
        assert not wants_color(is_terminal=False, environment={})


class TestWhenTwoMappedRangesOverlap:
    def test_the_second_is_refused_and_the_error_names_both_targets(self):
        platform = sp.Platform()
        bus = platform.add("bus", sp.Router())
        first = platform.add("first_ram", sp.Memory(size=0x100))
        second = platform.add("second_ram", sp.Memory(size=0x100))
        bus.map(first.socket, base=0x1000)

        with pytest.raises(ValueError, match=r"first_ram\.socket") as error:
            bus.map(second.socket, base=0x10FF)

        assert "second_ram.socket" in str(error.value)


class TestWhenATargetWithNoSizeOfItsOwnIsMapped:
    def test_it_is_refused_and_the_error_asks_for_a_size(self):
        platform = sp.Platform()
        bus = platform.add("bus", sp.Router())
        link = platform.link("link", sp.PassThroughLink())

        with pytest.raises(ValueError, match=r"link\.a\.target") as error:
            bus.map(link.a.target, base=0x1000)

        assert "size" in str(error.value)


@pytest.mark.platform
class TestWhenARangeIsMappedAfterThePlatformIsBuilt:
    def test_it_is_refused_and_the_router_is_left_as_it_was(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, bus.target)
        bus.map(ram.socket, base=0)
        platform.build()

        with pytest.raises(RuntimeError):
            bus.map(ram.socket, base=0x1000)

        assert bus.component.ports == ("target", "out0")


@pytest.mark.platform
class TestWhenAWindowOfAStatedSizeIsMappedOntoALink:
    def test_an_access_inside_it_crosses_the_link_at_its_offset(self):
        platform = sp.Platform()
        near = platform.group("near")
        far = platform.group("far")
        cpu = near.add("cpu", sp.ScriptedBusMaster())
        near_bus = near.add("bus", sp.Router())
        link = platform.link("link", sp.PassThroughLink(), near, far)
        far_bus = far.add("bus", sp.Router())
        ram = far.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, near_bus.target)
        near_bus.map(link.a.target, base=0x1000_0000, size=0x1_0000)
        platform.connect(link.b.initiator, far_bus.target)
        far_bus.map(ram.socket, base=0x2000)
        platform.build()

        platform.poke32(0x1000_2010, 0xC0FFEE)

        assert platform.peek32(0x1000_2010) == 0xC0FFEE
