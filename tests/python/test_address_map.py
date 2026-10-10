"""🧦 The address map of a description: what answers where, and to whom."""

import pytest

import socpuppet as sp
from socpuppet.address_map import Window


def two_devices_on_a_bus():
    """A CPU's stand-in with a UART at 0x1000 and a RAM at 0x8000 on its bus."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster())
    bus = platform.add("bus", sp.Router())
    ram = platform.add("ram", sp.Memory(size=0x400))
    uart = platform.add("uart", sp.Ns16550())
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=0x8000)
    bus.map(uart.socket, base=0x1000)
    return platform


class TestWhenAMasterReachesTwoDevicesThroughARouter:
    def test_the_map_has_each_where_it_was_mapped_lowest_address_first(self):
        platform = two_devices_on_a_bus()

        assert [
            (entry.address, entry.component) for entry in platform.address_map()
        ] == [(0x1000, "uart"), (0x8000, "ram")]

    def test_each_entry_says_how_many_bytes_answer_there(self):
        platform = two_devices_on_a_bus()

        sizes = {
            entry.component: entry.size for entry in platform.address_map()
        }

        assert sizes == {"uart": sp.Ns16550().mapped_size, "ram": 0x400}

    def test_each_entry_names_the_port_that_answers_and_its_model(self):
        platform = two_devices_on_a_bus()

        assert [
            (entry.component, entry.port, entry.implementation)
            for entry in platform.address_map()
        ] == [
            ("uart", "socket", sp.Ns16550.implementation),
            ("ram", "socket", sp.Memory.implementation),
        ]


class TestWhenAMemoryIsMappedThroughARangeSmallerThanItself:
    def test_its_entry_is_as_big_as_the_range(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        ram = platform.add("ram", sp.Memory(size=0x10000))
        platform.connect(cpu.socket, bus.target)
        bus.map(ram.socket, base=0x8000_0000, size=0x4000)

        (entry,) = platform.address_map()

        assert entry.size == 0x4000


class TestWhenSomethingWithNoSizeOfItsOwnIsMapped:
    def test_its_entry_is_as_big_as_the_range_it_was_given(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        root_complex = platform.add("rc", sp.PcieRootComplex())
        platform.connect(cpu.socket, bus.target)
        bus.map(root_complex.ecam, base=0x1000_0000, size=0x10_0000)

        (entry,) = platform.address_map()

        assert entry.size == 0x10_0000


def a_uart_on_another_die(window_base):
    """A UART at 0x40 on the IO die's bus, which the compute die's bus has
    0x1000 bytes of from `window_base` on, across a link."""
    platform = sp.Platform()
    compute = platform.group("compute")
    io = platform.group("io")
    cpu = compute.add("cpu", sp.ScriptedBusMaster())
    compute_bus = compute.add("bus", sp.Router())
    link = platform.link("d2d", sp.PassThroughLink(), compute, io)
    io_bus = io.add("bus", sp.Router())
    uart = io.add("uart", sp.Ns16550())
    platform.connect(cpu.socket, compute_bus.target)
    compute_bus.map(link.a.target, base=window_base, size=0x1000)
    platform.connect(link.b.initiator, io_bus.target)
    io_bus.map(uart.socket, base=0x40)
    return platform


class TestWhenADeviceIsBehindAWindowOntoAnotherBus:
    def test_its_address_is_counted_from_where_the_window_starts(self):
        platform = a_uart_on_another_die(window_base=0x1000_0000)

        (entry,) = platform.address_map()

        assert entry.address == 0x1000_0040

    def test_its_entry_names_the_window_it_is_reached_through(self):
        platform = a_uart_on_another_die(window_base=0x1000_0000)

        (entry,) = platform.address_map()

        assert entry.windows == (
            Window(bus="compute.bus", address=0x1000_0000, size=0x1000),
        )

    def test_a_window_that_starts_anywhere_but_zero_translates(self):
        platform = a_uart_on_another_die(window_base=0x1000_0000)

        (entry,) = platform.address_map()

        assert [window.translates for window in entry.windows] == [True]


class TestWhenAWindowStartsAtAddressZero:
    def test_what_is_behind_it_keeps_its_own_address_and_nothing_translates(
        self,
    ):
        platform = a_uart_on_another_die(window_base=0)

        (entry,) = platform.address_map()

        assert entry.address == 0x40
        assert [window.translates for window in entry.windows] == [False]


class TestWhenADeviceIsOnTheMastersOwnBus:
    def test_its_entry_has_no_windows(self):
        platform = two_devices_on_a_bus()

        assert [entry.windows for entry in platform.address_map()] == [(), ()]


class TestWhenARangeLeadsOverALinkStraightToADevice:
    def test_the_range_is_a_window_though_no_bus_is_behind_it(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        link = platform.link("link", sp.PassThroughLink())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, bus.target)
        bus.map(link.a.target, base=0x2000, size=0x80)
        platform.connect(link.b.initiator, ram.socket)

        (entry,) = platform.address_map()

        assert entry.windows == (Window(bus="bus", address=0x2000, size=0x80),)


def a_ram_behind_two_windows(*, inner_base, inner_size=0x1000):
    """A RAM on the bus `far`, behind a window of the bus `middle`, which
    is itself behind 0x8000 bytes of the master's bus `near` at 0x1_0000."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster())
    near = platform.add("near", sp.Router())
    middle = platform.add("middle", sp.Router())
    far = platform.add("far", sp.Router())
    ram = platform.add("ram", sp.Memory(size=0x10))
    platform.connect(cpu.socket, near.target)
    near.map(middle.target, base=0x1_0000, size=0x8000)
    middle.map(far.target, base=inner_base, size=inner_size)
    far.map(ram.socket, base=0x300)
    return platform


class TestWhenADeviceIsBehindTwoWindows:
    def test_its_entry_names_both_the_masters_own_bus_first(self):
        platform = a_ram_behind_two_windows(inner_base=0x2000)

        (entry,) = platform.address_map()

        assert [window.bus for window in entry.windows] == ["near", "middle"]

    def test_the_inner_windows_address_is_where_the_master_finds_it(self):
        platform = a_ram_behind_two_windows(inner_base=0x2000)

        (entry,) = platform.address_map()

        assert [window.address for window in entry.windows] == [
            0x1_0000,
            0x1_2000,
        ]

    def test_an_inner_window_at_zero_on_its_own_bus_still_translates(self):
        # What is behind it is not where the master's addresses say, which
        # is what the master's firmware has to know.
        platform = a_ram_behind_two_windows(inner_base=0)

        (entry,) = platform.address_map()

        assert [window.translates for window in entry.windows] == [True, True]

    def test_an_inner_window_is_no_bigger_than_the_one_it_is_inside(self):
        platform = a_ram_behind_two_windows(inner_base=0, inner_size=0x10_0000)

        (entry,) = platform.address_map()

        assert [window.size for window in entry.windows] == [0x8000, 0x8000]


class TestWhenAPlatformHasGroups:
    def test_each_entry_says_which_group_its_component_is_in(self):
        platform = a_uart_on_another_die(window_base=0x1000_0000)

        (entry,) = platform.address_map()

        assert entry.group == "io"

    def test_a_component_in_a_nested_group_is_in_the_inner_one(self):
        platform = sp.Platform()
        storage = platform.group("io").group("storage")
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        ram = storage.add("ram", sp.Memory(size=0x10))
        platform.connect(cpu.socket, ram.socket)

        (entry,) = platform.address_map()

        assert entry.group == "io.storage"

    def test_a_component_outside_every_group_has_none(self):
        platform = sp.Platform()
        cpu = platform.group("compute").add("cpu", sp.ScriptedBusMaster())
        ram = platform.add("ram", sp.Memory(size=0x10))
        platform.connect(cpu.socket, ram.socket)

        (entry,) = platform.address_map()

        assert entry.group is None


class TestWhenAPlatformHasTwoBusMasters:
    def two_masters_with_a_ram_each(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)
        other_cpu = platform.add("other_cpu", sp.ScriptedBusMaster())
        other_ram = platform.add("other_ram", sp.Memory(size=0x200))
        platform.connect(other_cpu.socket, other_ram.socket)
        return platform, other_cpu

    def test_the_map_is_the_view_from_the_named_one(self):
        platform, other_cpu = self.two_masters_with_a_ram_each()

        (entry,) = platform.address_map(via=other_cpu.socket)

        assert entry.component == "other_ram"

    def test_a_map_that_names_no_port_is_refused_and_the_error_asks_for_one(
        self,
    ):
        platform, _ = self.two_masters_with_a_ram_each()

        with pytest.raises(ValueError, match="via="):
            platform.address_map()
