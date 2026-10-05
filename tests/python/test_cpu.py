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


# A program in RISC-V machine code. It stores the word 0x5A at 0x200 bytes
# past its own first instruction, wherever it is loaded, and then sleeps.
STORE_0X5A_THEN_SLEEP = b"".join(
    word.to_bytes(4, "little")
    for word in (
        0x00000297,  # auipc t0, 0          t0 = this instruction's address
        0x05A00313,  # li    t1, 0x5a
        0x2062A023,  # sw    t1, 0x200(t0)
        0x10500073,  # wfi                  sleep until an interrupt
        0xFFDFF06F,  # j     -4             and sleep again if one comes
    )
)


@pytest.mark.platform
class TestWhenACpuRunsAProgramPokedIntoMemory:
    def test_a_peek_sees_what_the_program_stored(self):
        platform = cpu_and_ram()
        platform.build()
        platform.poke(RESET_VECTOR, STORE_0X5A_THEN_SLEEP)

        # Five instructions: ten microseconds is far more than they need.
        platform.run(sp.us(10))

        assert platform.peek32(RESET_VECTOR + 0x200) == 0x5A
