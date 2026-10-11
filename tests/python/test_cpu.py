"""A CPU in a platform that is described and driven from Python."""

import re

import pytest

import socpuppet as sp

RESET_VECTOR = 0x100


def cpu_and_ram(**described):
    """A CPU and nothing else but a RAM for its program.

    The CPU is a 64-bit one, and `described` is anything more to describe
    it with.
    """
    platform = sp.Platform()
    cpu = platform.add(
        "cpu", sp.DbtRiseCpu(xlen=64, reset_vector=RESET_VECTOR, **described)
    )
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


# The same, by way of a floating-point register: the value goes into one
# and comes back out before it is stored. A core with no floating point
# stops at the move, which it has no such instruction for, and stores
# nothing.
MOVE_0X5A_THROUGH_A_FLOATING_POINT_REGISTER_THEN_SLEEP = b"".join(
    word.to_bytes(4, "little")
    for word in (
        0x00000297,  # auipc   t0, 0
        0x00100313,  # li      t1, 1
        0x00D31313,  # slli    t1, t1, 13     the bit that switches
        0x30032073,  # csrs    mstatus, t1    floating point on
        0x05A00313,  # li      t1, 0x5a
        0xF2030053,  # fmv.d.x ft0, t1
        0xE20003D3,  # fmv.x.d t2, ft0
        0x2072A023,  # sw      t2, 0x200(t0)
        0x10500073,  # wfi
        0xFFDFF06F,  # j       -4
    )
)


@pytest.mark.platform
class TestWhenACpuIsDescribedAsRv64gcWithSupervisorAndUserMode:
    def test_a_program_can_use_a_floating_point_register(self):
        # The one core with floating point is also the one with supervisor
        # mode, so the two are asked for together.
        platform = cpu_and_ram(isa="gc", modes="msu")
        platform.build()
        platform.poke(
            RESET_VECTOR, MOVE_0X5A_THROUGH_A_FLOATING_POINT_REGISTER_THEN_SLEEP
        )

        # Ten instructions, a microsecond's worth: ten is far more than
        # they need.
        platform.run(sp.us(10))

        assert platform.peek32(RESET_VECTOR + 0x200) == 0x5A


class TestWhenACpuIsDescribedAsACoreThereIsNot:
    @pytest.mark.parametrize(
        ("described", "named"),
        [
            pytest.param(
                {"xlen": 64, "isa": "spam"},
                'isa="spam"',
                id="an-isa-unheard-of",
            ),
            pytest.param(
                {"xlen": 64, "modes": "mu"},
                'modes="mu"',
                id="machine-and-user-without-supervisor",
            ),
            pytest.param(
                {"xlen": 64, "isa": "gc"},
                'isa="gc", modes="m"',
                id="gc-in-machine-mode-only",
            ),
            pytest.param(
                {"xlen": 64, "modes": "msu"},
                'isa="imac", modes="msu"',
                id="imac-with-supervisor-mode",
            ),
            pytest.param(
                {"xlen": 32, "isa": "gc", "modes": "msu"},
                'xlen=32, isa="gc", modes="msu"',
                id="gc-at-32-bits",
            ),
        ],
    )
    def test_it_is_refused_by_name_and_the_error_says_which_cores_there_are(
        self, described, named
    ):
        with pytest.raises(ValueError, match=re.escape(named)) as error:
            sp.DbtRiseCpu(reset_vector=RESET_VECTOR, **described)

        assert 'isa="imac", modes="m" with xlen=32 or 64' in str(error.value)
        assert 'isa="gc", modes="msu" with xlen=64' in str(error.value)
