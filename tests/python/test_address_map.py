"""🧦 The address map of a description: what answers where, and to whom."""

import socpuppet as sp


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
            (entry.address, entry.component)
            for entry in platform.address_map()
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
        ] == [("uart", "socket", "ns16550"), ("ram", "socket", "memory")]


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

        assert (entry.port, entry.size) == ("ecam", 0x10_0000)
