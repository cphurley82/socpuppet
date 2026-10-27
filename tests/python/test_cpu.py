"""A CPU in a platform that is described and driven from Python."""

import re

import pytest

import socpuppet as sp
from socpuppet.boards.host import host
from socpuppet.boards.io_manager import io_manager
from socpuppet.boards.scripted_host import idle_host
from socpuppet.boards.ssd import ssd

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


# A program that goes 4,096 times round a loop of two instructions, reads
# its `time` register, stores what it read at 0x200 bytes past its own
# first instruction, and sleeps.
READ_TIME_AFTER_A_LOOP_THEN_SLEEP = b"".join(
    word.to_bytes(4, "little")
    for word in (
        0x00000297,  # auipc  t0, 0
        0x000013B7,  # lui    t2, 1          t2 = 4096
        0xFFF38393,  # addi   t2, t2, -1
        0xFE039EE3,  # bnez   t2, -4
        0xC0102373,  # rdtime t1             t1 = the `time` register
        0x2062A023,  # sw     t1, 0x200(t0)
        0x10500073,  # wfi
        0xFFDFF06F,  # j      -4
    )
)


def the_hosts_cpu():
    """The host board and its CPU."""
    board = host()
    return board.platform, board.cpu


def the_ssds_cpu():
    """The SSD board and its controller's CPU."""
    board = ssd(host=idle_host)
    return board.platform, board.ssd.cpu


def the_io_managers_cpu():
    """The IO manager board and the manager's CPU."""

    def nothing():
        """🎭 A compute die that does nothing at all."""
        yield from ()

    board = io_manager(compute=nothing)
    return board.platform, board.manager.cpu


@pytest.mark.platform
class TestWhenTheCpuOfABoardReadsItsTimeRegister:
    @pytest.mark.parametrize(
        "the_cpu_of", [the_hosts_cpu, the_ssds_cpu, the_io_managers_cpu]
    )
    def test_it_reads_what_its_timer_has_counted(self, the_cpu_of):
        platform, cpu = the_cpu_of()
        start = cpu.component.parameters["reset_vector"]
        platform.build()
        platform.poke(start, READ_TIME_AFTER_A_LOOP_THEN_SLEEP, via=cpu.socket)

        # 8,200 instructions take 820 us on the interpreter, and a little
        # over a millisecond on QBox's hart, which counts 128 ns each.
        platform.run(sp.ms(2))

        # Unconnected, `time` reads zero. The loop is there so that a
        # connected timer has counted well past that by the time the
        # program looks.
        assert platform.peek32(start + 0x200, via=cpu.socket) > 0


@pytest.mark.platform
class TestWhenTheCpuOfABoardFindsNothingToRunWhereItStarts:
    @pytest.mark.parametrize(
        "the_cpu_of", [the_hosts_cpu, the_ssds_cpu, the_io_managers_cpu]
    )
    def test_the_run_still_ends_when_its_time_is_up(self, the_cpu_of):
        platform, _ = the_cpu_of()
        platform.build()

        # 🎓 Nothing is loaded, so the CPU fetches zeros, which are no
        # instruction, and traps to mtvec, zero too, where nothing answers:
        # a trap on every fetch, for ever. Each costs the CPU time as an
        # instruction does, so the clock moves on and the run ends: any
        # length shows that, and ten microseconds is a few dozen traps.
        platform.run(sp.us(10))

        assert platform.time >= sp.us(10)
