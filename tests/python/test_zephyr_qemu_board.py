"""Zephyr, built for its stock QEMU boards, booting on a socpuppet CPU.

The boards are Zephyr's `qemu_riscv64` and `qemu_riscv32`, which expect the
memory map of QEMU's `virt` machine. Nothing here is socpuppet's own board
yet: this is the shortest path from a real firmware image to its greeting.
"""

import pytest

import socpuppet as sp

# Where QEMU's `virt` machine puts things.
RAM_BASE = 0x8000_0000
UART_BASE = 0x1000_0000
TIMER_BASE = 0x0200_0000
INTERRUPT_CONTROLLER_BASE = 0x0C00_0000


def virt_machine(*, xlen):
    """A CPU, RAM and a UART where a `virt` machine has them.

    🎭 The timer and the interrupt controller are stood in for by plain
    memories: the firmware can set them up, and nothing ever comes of it.
    """
    platform = sp.Platform()
    cpu = platform.add("cpu", sp.DbtRiseCpu(xlen=xlen, reset_vector=RAM_BASE))
    bus = platform.add("bus", sp.Router())
    # The boards are told they have 256 MB, and put a stack at the top of it.
    ram = platform.add("ram", sp.Memory(size=256 * 1024 * 1024))
    uart = platform.add("uart", sp.Ns16550())
    timer = platform.add("timer", sp.Memory(size=0x1_0000))
    # The real interrupt controller's registers span 64 MB. Its settings for
    # one CPU all sit in the first 4 MB, which is all a stand-in needs.
    interrupts = platform.add("interrupts", sp.Memory(size=0x40_0000))
    platform.connect(cpu.socket, bus.target)
    bus.map(ram.socket, base=RAM_BASE)
    bus.map(uart.socket, base=UART_BASE)
    bus.map(timer.socket, base=TIMER_BASE)
    bus.map(interrupts.socket, base=INTERRUPT_CONTROLLER_BASE)
    return platform, uart


@pytest.mark.platform
class TestWhenZephyrsHelloWorldBootsOnA64BitCpu:
    def test_it_prints_its_greeting(self, firmware):
        platform, uart = virt_machine(xlen=64)
        platform.build()
        platform.load_elf(firmware("hello_world_qemu_riscv64.elf"))

        # The greeting comes after about 70,000 instructions, which is 7 ms
        # of simulated time at the CPU's 100 ns an instruction. 50 ms leaves
        # room for a slower boot and still ends a run that never prints.
        platform.run_until(
            lambda: "Hello World! qemu_riscv64" in uart.output,
            timeout=sp.ms(50),
        )

        assert "Hello World! qemu_riscv64" in uart.output
