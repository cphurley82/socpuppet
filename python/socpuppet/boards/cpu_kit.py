"""What a RISC-V CPU has around it on a socpuppet board.

A CPU on its own can do nothing: it needs a memory to run from, somewhere
to print, a timer to count time with, an interrupt controller for its
devices' lines, a system controller, which owns its reset and tells it
where to boot from, and a watchdog, which resets it when its firmware has
hung. Every board that has a CPU of its own wants the same six, at the
same addresses, which is what lets them share one SoC in
Zephyr (`socpuppet_rv32`) and what makes a devicetree for one board read
like a devicetree for another.

    🧠 cpu ─▶ bus ─┬─▶ sram     the firmware, loaded and run from here
                   ├─▶ uart     its console
                   ├─▶ timer    ─▶ the CPU's timer interrupt, and its `time`
                   ├─▶ plic     ─▶ the CPU's interrupt, from the devices' lines
                   ├─▶ syscon   ─▶ the CPU's reset
                   └─▶ wdt      ─▶ the system controller, when it bites

`add_cpu_kit()` puts the seven on a board's bus and wires them up. The board
says which of its devices' lines go on which of the interrupt
controller's sources, and where its CPU boots from; everything else is the
same every time.

The host's CPU is a 64-bit one with other things around it, and has the
system controller and the watchdog in common with these:
`add_system_controller()` and `add_watchdog()` are the parts of the kit
it takes.

The flash a CPU boots from is not in the kit, because the host's two CPUs
share one: `add_boot_flash()` is for a board whose CPU has a flash to
itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from socpuppet.components import (
    DbtRiseCpu,
    MachineTimer,
    Memory,
    Ns16550,
    Plic,
    SpiFlash,
    SystemController,
    Watchdog,
)
from socpuppet.placed import Placed, PlacedRouter, PlacedUart, Port
from socpuppet.platform import Group, Platform

#: The system controller: which die the CPU is on, where it boots from,
#: why it was last reset. QEMU's `virt` machine has its reset device here.
SYSCON_BASE = 0x0010_0000
#: The watchdog, beside the system controller it bites.
WATCHDOG_BASE = 0x0010_1000
#: The flash a CPU boots from, which its system controller's boot address
#: is inside. It is one address for every socpuppet CPU, so that a boot ROM
#: finds its flash in the same place on every board. 4 MiB is room for two
#: images, which the IO die's flash holds.
BOOT_FLASH_BASE = 0x1020_0000
BOOT_FLASH_SIZE = 4 * 1024 * 1024
#: The registers of the flash's SPI controller, which no firmware uses yet.
BOOT_FLASH_CONTROLLER_BASE = 0x100D_0000
#: The dies of the chiplet host, by the number each one's system
#: controller gives its CPU. A board of one die, as the SSD is, is die 0.
COMPUTE_DIE = 0
IO_DIE = 1
#: Where each image is in the IO die's flash, which holds two: the host's
#: from its start, and the IO die's manager's from half way through.
HOST_IMAGE_OFFSET = 0
MANAGER_IMAGE_OFFSET = 0x20_0000
#: The machine timer, and how many times a second it counts. The firmware
#: has to be told the same number: CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC in
#: Zephyr.
TIMER_BASE = 0x0200_0000
TIMER_HZ = 10_000_000
#: The interrupt controller.
PLIC_BASE = 0x0C00_0000
#: The UART, which is the firmware's console.
UART_BASE = 0x1000_0000
#: The memory the firmware is loaded into, and where the CPU starts at its
#: first instruction.
#: ⚠️ It has to stay below any other memory on the same bus. A devicetree
#: tells firmware which memory is its own (`zephyr,sram`), and of two
#: memories the generator names the one at the lower address.
SRAM_BASE = 0x2000_0000
SRAM_SIZE = 256 * 1024


class CpuKit(NamedTuple):
    """What a board's CPU has around it, when it is a real one."""

    #: Where the firmware is loaded, and runs from.
    sram: Placed
    #: The firmware's console: `uart.output` is what it has printed.
    uart: PlacedUart
    timer: Placed
    plic: Placed
    #: The system controller, which drives the CPU's reset.
    syscon: Placed
    #: The watchdog, which has the system controller reset the CPU when
    #: firmware stops feeding it.
    wdt: Placed


def add_cpu_kit(
    platform: Platform,
    place: Platform | Group,
    bus: PlacedRouter,
    *,
    sources: Mapping[int, Port],
    gdb_port: int = 0,
    die: int = COMPUTE_DIE,
    boot_address: int = BOOT_FLASH_BASE,
) -> tuple[Placed, CpuKit]:
    """Put a 32-bit CPU on `bus`, with what a CPU needs around it.

    `sources` says which of the interrupt controller's sources each of the
    board's device lines goes to, numbered from 1 (source 0 means "no
    interrupt"). The watchdog's interrupt takes the source after the
    highest of them. With a `gdb_port`, the CPU listens for a debugger on that
    TCP port and waits for one to attach before it executes anything.

    `die` and `boot_address` are what the CPU's system controller tells
    it: which die it is on, and where its boot ROM finds its image. Left
    out, they are the first die and the start of the flash, which is right
    for a board with one of each.

    💡 A CPU has one interrupt input for all of its devices, and asks the
    controller which of them it was.
    """
    cpu = place.add(
        "cpu", DbtRiseCpu(xlen=32, reset_vector=SRAM_BASE, gdb_port=gdb_port)
    )
    sram = place.add("sram", Memory(size=SRAM_SIZE))
    uart = place.add("uart", Ns16550())
    timer = place.add("timer", MachineTimer(frequency_hz=TIMER_HZ))
    plic = place.add("plic", Plic())
    syscon = add_system_controller(
        platform, place, bus, cpu, die=die, boot_address=boot_address
    )
    bus.map(timer.socket, base=TIMER_BASE)
    bus.map(plic.socket, base=PLIC_BASE)
    bus.map(uart.socket, base=UART_BASE)
    bus.map(sram.socket, base=SRAM_BASE)
    for source, line in sources.items():
        platform.connect(line, getattr(plic, f"source{source}"))
    after_the_boards_own = max(sources) + 1
    wdt = add_watchdog(
        platform,
        place,
        bus,
        syscon,
        irq=getattr(plic, f"source{after_the_boards_own}"),
    )
    platform.connect(plic.irq, cpu.irq)
    platform.connect(timer.irq, cpu.timer_irq)
    # The CPU's `time` register is the timer's count.
    platform.connect(cpu.time, timer.time)
    return cpu, CpuKit(
        sram=sram, uart=uart, timer=timer, plic=plic, syscon=syscon, wdt=wdt
    )


def add_system_controller(
    platform: Platform,
    place: Platform | Group,
    bus: PlacedRouter,
    cpu: Placed,
    *,
    die: int,
    boot_address: int,
) -> Placed:
    """Put a CPU's system controller on `bus`, driving the CPU's reset.

    Every socpuppet CPU has one, at `SYSCON_BASE`. `die` and
    `boot_address` are what it tells the CPU: which die it is on, and
    where its boot ROM finds its image.

    💡 A wire has one driver. A CPU's reset has more than one reason to
    rise, so the system controller drives it and each reason is an input
    there: connect what holds the CPU to the returned controller's `hold`.
    """
    syscon = place.add(
        "syscon", SystemController(die=die, boot_address=boot_address)
    )
    bus.map(syscon.socket, base=SYSCON_BASE)
    platform.connect(syscon.reset, cpu.reset)
    return syscon


def add_watchdog(
    platform: Platform,
    place: Platform | Group,
    bus: PlacedRouter,
    syscon: Placed,
    *,
    irq: Port,
) -> Placed:
    """Put a CPU's watchdog on `bus`, biting the CPU's system controller.

    Every socpuppet CPU has one, at `WATCHDOG_BASE`. When firmware stops
    feeding it, its `bite` rises and the system controller `syscon`
    resets the CPU. `irq` is where its interrupt line goes: a source of
    the CPU's interrupt controller.
    """
    wdt = place.add("wdt", Watchdog())
    bus.map(wdt.socket, base=WATCHDOG_BASE)
    platform.connect(wdt.bite, syscon.bite)
    platform.connect(wdt.irq, irq)
    return wdt


def add_boot_flash(place: Platform | Group, bus: PlacedRouter) -> Placed:
    """Put the flash a CPU boots from on `bus`, for a CPU with one to itself.

    It is read like memory at `BOOT_FLASH_BASE`, where the CPU's system
    controller says its image is, and its controller's registers are at
    `BOOT_FLASH_CONTROLLER_BASE`. Fill it before the first run:
    `platform.load_binary(image, at=BOOT_FLASH_BASE, via=cpu.socket)`.

    The host's two CPUs share one flash, and the host places that itself.
    """
    flash = place.add("boot_flash", SpiFlash(size=BOOT_FLASH_SIZE))
    bus.map(flash.xip, base=BOOT_FLASH_BASE)
    bus.map(flash.socket, base=BOOT_FLASH_CONTROLLER_BASE)
    return flash
