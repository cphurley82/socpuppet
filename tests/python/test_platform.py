import pytest

import socpuppet as sp


def thin_platform(writes):
    """A scripted master that writes through a pass-through link into a RAM."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.ScriptedBusMaster(writes=writes))
    link = platform.add("link", sp.PassThroughLink())
    ram = platform.add("ram", sp.Memory(size=0x100))
    platform.connect(cpu.socket, link.target)
    platform.connect(link.initiator, ram.socket)
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
        cpu = platform.add("cpu", sp.ScriptedBusMaster(writes=[]))
        ram = platform.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)
        platform.build()

        with pytest.raises(RuntimeError) as error:
            platform.connect(cpu.socket, ram.socket)

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
class TestWhenAPeekMissesEveryMemory:
    def test_the_error_names_the_address(self):
        platform = thin_platform(writes=[])
        platform.build()

        with pytest.raises(LookupError) as error:
            platform.peek32(0x1000)

        assert "0x1000" in str(error.value)


@pytest.mark.platform
class TestWhenAPlatformHasTwoBusMasters:
    def test_a_peek_through_a_named_port_sees_what_that_master_sees(self):
        platform, first_cpu, second_cpu = two_masters_each_with_a_ram()
        platform.build()
        platform.poke32(0x10, 0xAAAA, via=first_cpu.socket)
        platform.poke32(0x10, 0xBBBB, via=second_cpu.socket)

        assert platform.peek32(0x10, via=first_cpu.socket) == 0xAAAA

    def test_a_peek_that_names_no_port_is_refused_and_the_error_asks_for_one(self):
        platform, _, _ = two_masters_each_with_a_ram()
        platform.build()

        with pytest.raises(ValueError) as error:
            platform.peek32(0x10)

        assert "via=" in str(error.value)


def two_masters_each_with_a_ram():
    platform = sp.Platform()
    cpus = []
    for name in ("first", "second"):
        group = platform.group(name)
        cpu = group.add("cpu", sp.ScriptedBusMaster(writes=[]))
        ram = group.add("ram", sp.Memory(size=0x100))
        platform.connect(cpu.socket, ram.socket)
        cpus.append(cpu)
    return platform, *cpus
