import pytest

import socpuppet as sp
from scripts import writing


def thin_platform(writes):
    """A scripted master that writes through a pass-through link into a RAM."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(writing(writes)))
    link = platform.link("link", sp.PassThroughLink())
    ram = platform.add("ram", sp.Memory(size=0x100))
    platform.connect(cpu.socket, link.a.target)
    platform.connect(link.b.initiator, ram.socket)
    return platform


@pytest.mark.platform
class TestWhenADescribedPlatformIsBuiltAndRun:
    def test_peek_returns_what_the_master_wrote(self):
        platform = thin_platform(writes=[(0x10, 0xC0FFEE)])
        platform.build()

        platform.run()

        assert platform.peek32(0x10) == 0xC0FFEE


@pytest.mark.platform
class TestWhenASecondPlatformIsBuiltInOneProcess:
    def test_the_error_explains_the_one_kernel_rule_and_names_the_marker(self):
        first = thin_platform(writes=[])
        first.build()

        with pytest.raises(RuntimeError) as error:
            thin_platform(writes=[]).build()

        assert "only one Platform" in str(error.value)
        assert "SystemC kernel" in str(error.value)
        assert "@pytest.mark.platform" in str(error.value)


@pytest.mark.platform
class TestWhenThePlatformIsAlreadyBuilt:
    def test_adding_a_component_is_refused_and_the_error_says_why(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(RuntimeError) as error:
            platform.add("uart", sp.Memory(size=0x10))

        assert "already built" in str(error.value)

    def test_connecting_ports_is_refused_and_the_error_says_why(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)
        platform.build()

        with pytest.raises(RuntimeError) as error:
            platform.connect(cpu.socket, ram.socket)

        assert "already built" in str(error.value)

    def test_adding_a_router_input_is_refused_and_the_error_says_why(self):
        platform = sp.Platform()
        cpu = platform.add("cpu", sp.ScriptedBusMaster())
        bus = platform.add("bus", sp.Router())
        platform.connect(cpu.socket, bus.target)
        platform.build()

        with pytest.raises(RuntimeError) as error:
            bus.add_input()

        assert "already built" in str(error.value)

    def test_building_it_again_is_refused_and_the_error_says_why(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(RuntimeError) as error:
            platform.build()

        assert "already built" in str(error.value)


class TestWhenThePlatformIsNotBuiltYet:
    def test_running_it_is_refused_and_the_error_says_to_build_first(self):
        platform = thin_platform(writes=[])

        with pytest.raises(RuntimeError) as error:
            platform.run()

        assert "build()" in str(error.value)


@pytest.mark.platform
class TestWhenThePlatformRunsForADuration:
    def test_simulated_time_advances_by_that_duration(self):
        platform = thin_platform(writes=[])
        platform.build()

        platform.run(sp.ns(10))
        platform.run(sp.us(1))

        assert platform.time == sp.ns(10) + sp.us(1)


@pytest.mark.platform
class TestWhenMemoryIsPokedBeforeTheFirstRun:
    def test_peek_returns_the_poked_value(self):
        platform = thin_platform(writes=[])
        platform.build()

        platform.poke32(0x20, 0xC0FFEE)

        assert platform.peek32(0x20) == 0xC0FFEE


@pytest.mark.platform
class TestWhenBytesOfAnyLengthArePoked:
    def test_they_land_in_order_starting_at_the_poked_address(self):
        platform = thin_platform(writes=[])
        platform.build()

        platform.poke(0x20, bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66]))

        assert platform.peek32(0x20) == 0x44332211
        assert platform.peek32(0x22) == 0x66554433


@pytest.mark.platform
class TestWhenBytesOfAnyLengthArePeeked:
    def test_they_are_the_bytes_that_were_poked_there(self):
        platform = thin_platform(writes=[])
        platform.build()
        platform.poke(0x20, bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66]))

        assert platform.peek(0x21, 4) == bytes([0x22, 0x33, 0x44, 0x55])


@pytest.mark.platform
class TestWhenAPeekOfBytesMissesEveryMemory:
    def test_the_error_names_the_address_and_how_many_bytes(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(LookupError) as error:
            platform.peek(0x1000, 6)

        assert "0x1000" in str(error.value)
        assert "6-byte" in str(error.value)


@pytest.mark.platform
class TestWhenAPeekMissesEveryMemory:
    def test_the_error_names_the_address(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(LookupError) as error:
            platform.peek32(0x1000)

        assert "0x1000" in str(error.value)


@pytest.mark.platform
class TestWhenAPokeOfBytesMissesEveryMemory:
    def test_the_error_names_the_address_and_how_many_bytes(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(LookupError) as error:
            platform.poke(0x1000, bytes(6))

        assert "0x1000" in str(error.value)
        assert "6-byte" in str(error.value)


@pytest.mark.platform
class TestWhenAPlatformHasTwoBusMasters:
    def test_a_peek_through_a_named_port_sees_what_that_master_sees(self):
        platform, first_cpu, second_cpu = two_masters_each_with_a_ram()
        platform.build()
        platform.poke32(0x10, 0xAAAA, via=first_cpu.socket)
        platform.poke32(0x10, 0xBBBB, via=second_cpu.socket)

        assert platform.peek32(0x10, via=first_cpu.socket) == 0xAAAA

    def test_a_peek_that_names_no_port_is_refused_and_the_error_asks_for_one(
        self,
    ):
        platform, _, _ = two_masters_each_with_a_ram()
        platform.build()

        with pytest.raises(ValueError, match="via="):
            platform.peek32(0x10)


def two_masters_each_with_a_ram():
    platform = sp.Platform()
    cpus = []
    for name in ("first", "second"):
        group = platform.group(name)
        cpu = group.add("cpu", sp.ScriptedBusMaster())
        ram = group.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)
        cpus.append(cpu)
    return platform, *cpus


class TestWhenALinkIsPlacedBetweenTwoGroups:
    def test_each_group_gets_an_endpoint_named_after_the_link(self):
        platform = sp.Platform()

        link = platform.link(
            "d2d",
            sp.PassThroughLink(),
            platform.group("compute"),
            platform.group("io"),
        )

        assert (link.a.path, link.b.path) == ("compute.d2d", "io.d2d")


@pytest.mark.platform
class TestWhenADeviceOnTheFarDieWritesBackAcrossALink:
    """The path a device's DMA takes into the host's memory.

    compute die                                     IO die
    cpu ─▶ bus ─▶ ram
            ▲
            └── link endpoint ◀══ link endpoint ◀── device
    """

    def test_the_near_dies_master_finds_the_write_in_its_memory(self):
        ram_base = 0x8000_0000
        platform = sp.Platform()
        compute = platform.group("compute")
        io = platform.group("io")
        cpu = compute.add("cpu", sp.ScriptedBusMaster())
        bus = compute.add("bus", sp.Router())
        ram = compute.add("ram", sp.Memory(size=0x100))
        d2d = platform.link("d2d", sp.PassThroughLink(), compute, io)
        device = io.add(
            "device",
            sp.ScriptedBusMaster(writing([(ram_base + 0x10, 0xC0FFEE)])),
        )
        platform.connect(cpu.socket, bus.target)
        bus.map(ram.socket, base=ram_base)
        platform.connect(device.socket, d2d.b.target)
        platform.connect(d2d.a.initiator, bus.add_input())
        platform.build()

        platform.run()

        assert platform.peek32(ram_base + 0x10, via=cpu.socket) == 0xC0FFEE


@pytest.mark.platform
class TestWhenAQuantumIsDescribed:
    def test_the_built_simulation_runs_with_that_quantum(self):
        from socpuppet import _core

        platform = thin_platform(writes=[])
        platform.quantum = sp.us(7)

        platform.build()

        assert _core.global_quantum_in_picoseconds() == sp.us(7)


@pytest.mark.platform
class TestWhenNoQuantumIsDescribed:
    def test_the_simulation_runs_with_a_hundred_microseconds(self):
        from socpuppet import _core

        platform = thin_platform(writes=[])

        platform.build()

        assert _core.global_quantum_in_picoseconds() == sp.us(100)


class TestWhenTheQuantumIsChangedAfterBuilding:
    @pytest.mark.platform
    def test_it_is_refused_and_the_error_says_why(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(RuntimeError, match="already built"):
            platform.quantum = sp.us(7)


@pytest.mark.platform
class TestWhenAComponentIsGivenAParameterItDoesNotTake:
    def test_building_is_refused_and_the_error_names_the_parameter(self):
        platform = sp.Platform()
        platform.add("plic", sp.Plic(sources=8))

        with pytest.raises(ValueError, match='"plic" has no "sources"'):
            platform.build()
