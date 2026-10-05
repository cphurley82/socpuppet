"""A CPU in a platform that is described and driven from Python."""

import pytest

import socpuppet as sp

RESET_VECTOR = 0x100


def cpu_and_ram():
    """A CPU and nothing else but a RAM for its program."""
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=64, reset_vector=RESET_VECTOR))
    ram = platform.add("ram", sp.Memory(size=0x1000))
    platform.connect(cpu.socket, ram.socket)
    return platform


@pytest.mark.platform
class TestWhenAPlatformsOnlyBusMasterIsACpu:
    def test_a_peek_that_names_no_port_looks_through_the_cpu(self):
        platform = cpu_and_ram()
        platform.build()
        platform.poke32(0x20, 0xC0FFEE)

        assert platform.peek32(0x20) == 0xC0FFEE
