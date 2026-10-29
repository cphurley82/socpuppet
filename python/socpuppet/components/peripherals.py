"""The peripherals: the timers, the system controller, UART, SPI, GPIO, I2C."""

from __future__ import annotations

import datetime
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, override

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    not_a_parameter,
    target,
    wire_in,
    wire_out,
)
from socpuppet.i2c import I2cDevice
from socpuppet.placed import PlacedGpio, PlacedUart
from socpuppet.regs import system_controller
from socpuppet.spi import SpiDevice

if TYPE_CHECKING:
    from socpuppet import _core
    from socpuppet.address_map import Reached
    from socpuppet.platform import Platform


class MachineTimer(Component):
    """The RISC-V machine timer, which gives an operating system its tick.

    It has a counter, `mtime`, that counts up `frequency_hz` times a second
    of simulated time, and a compare register, `mtimecmp`. Its `irq` is high
    for as long as the counter is at or past the compare value: connect it
    to a CPU's `timer_irq`. The registers are where SiFive's CLINT has them.
    The model is borrowed from VPV-Peripherals (the Minres ACLINT).

    A RISC-V CPU also has the count as a register of its own, `time`, which
    it reads with no bus access. Connect the CPU's `time` to the timer's
    `time` for that. Left unconnected, the CPU's `time` reads zero.
    """

    implementation = "machine_timer"
    port_specs = (
        target("socket"),
        # Where a CPU reads the count from as its own `time` register.
        target("time", required=False),
        wire_out("irq"),
    )
    #: As on the CLINT: `mtimecmp` at 0x4000 and `mtime` at 0xBFF8.
    mapped_size = 0x1_0000

    frequency_hz: int = 10_000_000

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        base = reached["socket"].address
        mtime = base + 0xBFF8
        mtimecmp = base + 0x4000
        return DeviceNode(
            "timer",
            ((mtime, 8), (mtimecmp, 8)),
            (
                # Zephyr's name for it, and the ACLINT's machine timer, which
                # is what OpenSBI looks for: an ACLINT is a CLINT cut into
                # its parts, and this is that part.
                'compatible = "riscv,machine-timer";'
                if dialect == "zephyr"
                else 'compatible = "riscv,aclint-mtimer";',
                'reg-names = "mtime", "mtimecmp";',
            ),
        )

    @override
    def timebase_frequency(self, port: str) -> int | None:
        return self.frequency_hz if port == "time" else None


class SystemController(Component):
    """A CPU's system controller: it answers for the CPU, and owns its reset.

    Its registers tell firmware which die its CPU is on (`die`), where its
    boot ROM finds the image to start (`boot_address`) and why the CPU was
    last reset, and two of them reset the CPU and switch it off.

    🎓 A wire has one driver, and a CPU's reset has more than one reason to
    rise. So connect `reset` to the CPU's `reset`, and each reason to an
    input here. `hold` keeps the CPU in reset for as long as it is high,
    which is how a die-to-die link holds the other die until the link is
    up. `bite` is a watchdog's line, and a rise of it resets the CPU. Either
    may be left unconnected.
    """

    implementation = "system_controller"
    port_specs = (
        target("socket"),
        wire_in("hold"),
        wire_in("bite"),
        wire_out("reset"),
    )
    #: What the controller's register map says it takes.
    mapped_size = system_controller.SIZE

    die: int = 0
    boot_address: int = 0

    def __post_init__(self) -> None:
        for name in ("die", "boot_address"):
            if not 0 <= getattr(self, name) < 1 << 32:
                raise ValueError(
                    f"A system controller's `{name}` is a register of 32 "
                    f"bits, and {getattr(self, name):#x} does not fit in "
                    "one."
                )

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return DeviceNode(
            "syscon",
            ((reached["socket"].address, self.mapped_size),),
            # `syscon` is the name Zephyr and Linux both have for a block
            # of registers that other drivers reach into. Ours comes first,
            # for a driver that knows which registers these are.
            ('compatible = "socpuppet,system-controller", "syscon";',),
            # `reset` is not an interrupt.
            interrupts=(),
        )

    @override
    def device_nodes(
        self, reached: Mapping[str, Reached], *, dialect: Dialect, label: str
    ) -> tuple[DeviceNode, ...]:
        nodes = super().device_nodes(reached, dialect=dialect, label=label)
        if dialect == "zephyr":
            return nodes
        # 🎓 How to reset the CPU and how to switch it off, for OpenSBI and
        # Linux: which `syscon` node to write, at which register, and what.
        # Each is a node of its own at the top of the tree.
        return (
            *nodes,
            *(
                DeviceNode(
                    name,
                    (),
                    (
                        f'compatible = "syscon-{name}";',
                        f"regmap = <&{label}>;",
                        f"offset = <{offset:#x}>;",
                        f"value = <{value:#x}>;",
                    ),
                    on_bus=False,
                    interrupts=(),
                    suffix=f"_{name}",
                )
                for name, offset, value in (
                    (
                        "reboot",
                        system_controller.RESET_REQUEST,
                        system_controller.RESET_REQUEST_RESET,
                    ),
                    (
                        "poweroff",
                        system_controller.POWER_OFF,
                        system_controller.POWER_OFF_OFF,
                    ),
                )
            ),
        )

    @override
    def why_a_poke_was_refused(self, path: str) -> str:
        return (
            f'"{path}" is a system controller, and a debugger looks at '
            "one and does not touch: the registers that can be written "
            "reset the CPU and switch it off. To do either, have firmware "
            "write RESET_REQUEST or POWER_OFF."
        )


#: The clock of SiFive's peripherals: 50 MHz. Its SPI and I2C controllers
#: make their buses' clocks from it, and Zephyr's drivers for them share
#: one number for it (`SIFIVE_PERIPHERAL_CLOCK_FREQUENCY`).
PERIPHERAL_CLOCK_HZ = 50_000_000


class SpiFlash(Component):
    """A flash of `size` bytes and its SPI controller: where firmware is kept.

    🎓 A boot ROM cannot be changed, so the firmware it starts is kept
    somewhere that can: a flash chip. The chip is on an SPI bus, behind a
    controller, and the controller also shows it to the CPU as if it were
    memory (execute in place, XIP), which is how a boot ROM reads it.

    Map `xip` where the CPU is to find the flash, and `socket`, the
    controller's own registers, somewhere else. Fill the flash before the
    first run with `platform.load_binary(image, at=<where xip is>)`. A write
    from the bus through `xip` fails: a flash is written by commands to its
    controller. A CPU whose firmware drives the controller may also want
    `irq`, its interrupt.

    The controller is SiFive's, borrowed from VPV-Peripherals, and the chip
    is socpuppet's own, of Winbond's W25Q kind. Its devicetree node is the
    controller's (`sifive,spi0`), with the chip inside it at chip select 0
    as a `jedec,spi-nor`, and a fixed clock of its own.
    """

    implementation = "spi_flash"
    # A CPU whose boot ROM reads the window, and which drives nothing else,
    # needs the controller's registers nowhere on its bus.
    port_specs = (
        target("socket", required=False),
        target("xip"),
        # The controller's interrupt, for its FIFOs' watermarks.
        wire_out("irq", required=False),
    )
    #: The most a flash holds: what three address bytes reach.
    LARGEST = 16 << 20
    #: The controller's chip selects. The flash's own chip is at 0.
    CHIP_SELECTS = 4
    #: The controller's clock: SiFive's peripherals' (`PERIPHERAL_CLOCK_HZ`).
    CLOCK_HZ = PERIPHERAL_CLOCK_HZ
    #: The fastest SPI clock: SiFive's controller divides its own by at
    #: least two to make it.
    FASTEST_HZ = CLOCK_HZ // 2
    #: The controller's registers take a page.
    mapped_size = 0x1000

    size: int
    #: 🧵 Devices on the flash's SPI bus beside its chip, by chip select:
    #: 1 to 3, since the chip is at 0.
    devices: Mapping[int, SpiDevice] = not_a_parameter(
        default=MappingProxyType({})
    )

    def __post_init__(self) -> None:
        if not (0 < self.size <= self.LARGEST and self.size.bit_count() == 1):
            raise ValueError(
                "A flash's size is a power of two, as every W25Q chip's is, "
                "and at most 16 MiB, the most three address bytes reach; "
                f"{self.size:#x} bytes were asked for."
            )
        for chip_select in self.devices:
            if chip_select not in range(1, self.CHIP_SELECTS):
                raise ValueError(
                    "A device on a flash's SPI bus goes at chip select 1 to "
                    "3: the flash's own chip is at 0, and its controller has "
                    f"four. One was put at {chip_select}."
                )

    @override
    def size_at(self, port: str) -> int | None:
        return self.size if port == "xip" else self.mapped_size

    @property
    @override
    def parameters(self) -> dict[str, int]:
        return {**super().parameters, "clock_hz": self.CLOCK_HZ}

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        for chip_select, device in self.devices.items():
            native.spi_flash_attach(path, chip_select, device)

    @override
    def device_nodes(
        self, reached: Mapping[str, Reached], *, dialect: Dialect, label: str
    ) -> tuple[DeviceNode, ...]:
        # A bus master that cannot reach the controller's registers cannot
        # drive it, as a boot ROM, which reads the window, has no need to.
        # ⚠️ Linux's spi-sifive also wants the controller's `irq` connected:
        # with no interrupt in the node, it does not take the controller.
        if "socket" not in reached:
            return ()
        # Zephyr's binding has the chip's JEDEC id and its size in the node,
        # where Linux reads both from the chip. The id is the one the chip
        # answers its Read JEDEC ID command with (JedecId in
        # spi_nor_chip.cpp), which Zephyr's spi_nor checks this against:
        # Winbond's maker code, the W25Q family, and the capacity as the
        # power of two of the size. Zephyr's binding counts the size in bits.
        capacity = self.size.bit_length() - 1
        zephyrs_chip = (
            (
                f"jedec-id = [ef 40 {capacity:02x}];",
                f"size = <{self.size * 8:#x}>;",
            )
            if dialect == "zephyr"
            else ()
        )
        # And Zephyr's names the controller's two ranges; Linux's does not.
        zephyrs_controller = (
            ('reg-names = "control", "mem";',) if dialect == "zephyr" else ()
        )
        clock_suffix = "_clock"
        clock_label = label + clock_suffix
        # On an SPI bus a device's address is its chip select, one cell and
        # no range of memory, so it is in the name and in `reg` by hand.
        chip = DeviceNode(
            "flash@0",
            (),
            (
                'compatible = "jedec,spi-nor";',
                "reg = <0>;",
                *zephyrs_chip,
                f"spi-max-frequency = <{self.FASTEST_HZ}>;",
            ),
            interrupts=(),
            suffix="_chip",
        )
        controller = DeviceNode(
            "spi",
            (
                (reached["socket"].address, self.mapped_size),
                (reached["xip"].address, self.size),
            ),
            (
                'compatible = "sifive,spi0";',
                *zephyrs_controller,
                f"clocks = <&{clock_label}>;",
                "#address-cells = <1>;",
                "#size-cells = <0>;",
            ),
            children=(chip,),
        )
        # 🎓 A clock that only ever runs at one rate is a fixed clock: a
        # node of its own that says the rate, which a driver reads to set
        # the bus's speed.
        clock = DeviceNode(
            clock_label,
            (),
            (
                'compatible = "fixed-clock";',
                "#clock-cells = <0>;",
                f"clock-frequency = <{self.CLOCK_HZ}>;",
            ),
            on_bus=False,
            interrupts=(),
            suffix=clock_suffix,
        )
        return (controller, clock)


class Watchdog(Component):
    """A watchdog timer: it resets the CPU when firmware stops feeding it.

    🎓 A watchdog is a counter firmware has to keep setting back to zero.
    Firmware that hangs stops, the count reaches a value firmware chose,
    and the watchdog bites. This is the one in SiFive's FE310, which
    Zephyr has a driver for (`sifive,wdt`).

    Connect `bite` to a system controller's `bite`, which is what resets
    the CPU. `irq` is its interrupt, for a watchdog that is told to say it
    has run out and not to reset: connect it to an interrupt controller's
    source. ⚠️ Zephyr's driver will not build for a watchdog whose node
    has no interrupt.

    The model is borrowed from VPV-Peripherals, with the watchdog itself
    added: it had the registers and nothing behind them.
    """

    implementation = "watchdog"
    port_specs = (
        target("socket"),
        wire_out("irq", required=False),
        wire_out("bite", required=False),
    )
    #: A page: the watchdog's registers, and those of the rest of the
    #: always-on block the model is of, which nothing here uses.
    mapped_size = 0x1000

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return DeviceNode(
            "watchdog",
            ((reached["socket"].address, self.mapped_size),),
            ('compatible = "sifive,wdt";',),
            # Zephyr's watchdog test and samples look for this name.
            aliases=("watchdog0",),
            # `bite` resets, and is no interrupt.
            interrupts=("irq",),
            # Zephyr's binding requires the property by this name.
            short_interrupts=True,
        )


class Gpio(Component):
    """A GPIO block: 32 general-purpose pins, each an output or an input.

    🎓 A pin of a chip that is for no one thing is a GPIO pin, a
    general-purpose input or output. Firmware makes it an output and
    drives it high or low, to light an LED, say, or makes it an input and
    reads what is on it, a button's state. This is the GPIO block of
    SiFive's FE310, which Zephyr (`gpio_sifive`) and Linux (`gpio-sifive`)
    have drivers for.

    Map `socket`, its registers, on a bus. `pins` is how many of the 32 a
    board brings out, from pin 0 up, which is what firmware is told it
    has. `irq0` and up are each a pin's interrupt: connect one for each
    pin brought out to an interrupt controller's source.

    🧵 Python is at the far end of the pins: once the platform is built,
    `level(pin)` says what a pin drives, `drive(pin, level)` drives one,
    and `on_change(listener)` is told of each change (`PlacedGpio`).
    `wires` joins pins before then: `{0: 1}` is a wire from pin 0 to pin
    1, so what the GPIO drives on pin 0 is on pin 1 too, as a board's
    loopback has it. `leds` are the pins a board has an LED on, which
    firmware is told of, the first as `led0`.

    The model is borrowed from VPV-Peripherals, with its pull-ups and its
    interrupts added: it had the registers and nothing behind them.
    """

    implementation = "gpio"
    #: The pins the block has, 0 to 31, whatever a board brings out.
    PINS = 32
    port_specs = (
        target("socket"),
        *(wire_out(f"irq{pin}", required=False) for pin in range(PINS)),
    )
    #: A page, for the registers.
    mapped_size = 0x1000

    #: How many of the block's pins a board brings out, from pin 0 up, which
    #: is what firmware is told it has.
    pins: int = not_a_parameter(default=PINS)
    #: 🧵 Wires between pins brought out, from a pin to the pin it drives.
    wires: Mapping[int, int] = not_a_parameter(default=MappingProxyType({}))
    #: The pins brought out that a board has an LED on, lit while high.
    leds: tuple[int, ...] = not_a_parameter(default=())

    def __post_init__(self) -> None:
        if self.pins not in range(1, self.PINS + 1):
            raise ValueError(
                f"A GPIO brings out 1 to {self.PINS} pins; {self.pins} were "
                "asked for."
            )
        for end, which in [
            *((out, "start") for out in self.wires),
            *((into, "end") for into in self.wires.values()),
        ]:
            if end not in range(self.pins):
                raise ValueError(
                    f"A wire joins pins the GPIO brings out, 0 to "
                    f"{self.pins - 1}; one was to {which} at pin {end}."
                )
        for led in self.leds:
            if led not in range(self.pins):
                raise ValueError(
                    f"An LED is on a pin the GPIO brings out, 0 to "
                    f"{self.pins - 1}; one was to be on pin {led}."
                )

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        if not self.wires:
            return
        wires = self.wires

        def carry(pin: int, level: bool | None) -> None:
            if pin in wires:
                native.gpio_drive(path, wires[pin], level)

        native.gpio_on_change(path, carry)

    @override
    def place(self, platform: Platform, path: str) -> PlacedGpio:
        return PlacedGpio(platform, path, self)

    @override
    def device_nodes(
        self, reached: Mapping[str, Reached], *, dialect: Dialect, label: str
    ) -> tuple[DeviceNode, ...]:
        nodes = super().device_nodes(reached, dialect=dialect, label=label)
        # No GPIO node (a bus master that cannot reach the GPIO), no LEDs:
        # each names the GPIO's node. Nor in Linux's tree: the stock kernel
        # has no LED drivers (`NEW_LEDS` is not set).
        if not nodes or not self.leds or dialect == "linux":
            return nodes
        # 🎓 A board's LEDs, each a pin it drives, lit while high (the
        # flags' 0). Zephyr's samples find the first by the name `led0`.
        # ⚠️ So of two GPIOs with LEDs, the first's is `led0`. The node is
        # named for its GPIO, as the binding allows, so the two do not
        # clash.
        leds = DeviceNode(
            f"{label}_leds",
            (),
            ('compatible = "gpio-leds";',),
            on_bus=False,
            interrupts=(),
            suffix="_leds",
            children=tuple(
                DeviceNode(
                    f"led_{number}",
                    (),
                    (f"gpios = <&{label} {pin} 0>;",),
                    aliases=(f"led{number}",),
                    interrupts=(),
                    suffix=f"_led{number}",
                )
                for number, pin in enumerate(self.leds)
            ),
        )
        return (*nodes, leds)

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
        # Linux's binding has the GPIO an interrupt controller too, two
        # cells to an interrupt: gpio-sifive hands out a pin's interrupt to
        # a driver of what is on the pin.
        linuxs_interrupts = (
            ("interrupt-controller;", "#interrupt-cells = <2>;")
            if dialect == "linux"
            else ()
        )
        return DeviceNode(
            "gpio",
            ((reached["socket"].address, self.mapped_size),),
            (
                'compatible = "sifive,gpio0";',
                "gpio-controller;",
                "#gpio-cells = <2>;",
                f"ngpios = <{self.pins}>;",
                *linuxs_interrupts,
            ),
            # Zephyr's binding requires the property by this name.
            short_interrupts=True,
        )


class I2cController(Component):
    """A controller of an I2C bus, and 🧵 Python's devices on the bus.

    🎓 I2C is a bus of two wires, a clock and a data line, that many small
    chips share: sensors, clocks, the memory on a board that says what the
    board is. The controller starts a transfer and sends the address of
    the chip it wants, then sends or receives bytes one at a time.

    This is the OpenCores I2C master core, which SiFive's chips have as
    their I2C block and Zephyr's `i2c_sifive` drives. Map `cpu`, its
    registers, on a bus; `irq` is its interrupt, up when a command is done
    if firmware asked for it. `devices` are on its bus, by their seven-bit
    address: Python's own (`socpuppet.i2c`), such as a `Ram`.

    The model is socpuppet's own, from the core's specification.
    """

    implementation = "i2c_controller"
    port_specs = (
        target("cpu"),
        # Firmware may poll the status and leave the line alone.
        wire_out("irq", required=False),
    )
    #: The controller's clock, which the bus's is made from: SiFive's
    #: peripherals' (`PERIPHERAL_CLOCK_HZ`).
    CLOCK_HZ = PERIPHERAL_CLOCK_HZ
    #: The bus's speed firmware is told to set: 100 kHz, I2C's standard
    #: mode, which every device on a bus can keep up with.
    BUS_HZ = 100_000
    #: The seven bits of an address reach this many devices.
    ADDRESSES = 128
    #: The registers take a page.
    mapped_size = 0x1000

    #: 🧵 Devices on the bus, by their seven-bit address.
    devices: Mapping[int, I2cDevice] = not_a_parameter(
        default=MappingProxyType({})
    )

    def __post_init__(self) -> None:
        for address in self.devices:
            if address not in range(self.ADDRESSES):
                raise ValueError(
                    "A device on an I2C bus is at a seven-bit address, 0 to "
                    f"{self.ADDRESSES - 1}. One was put at {address}."
                )

    @property
    @override
    def parameters(self) -> dict[str, int]:
        return {**super().parameters, "clock_hz": self.CLOCK_HZ}

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        for address, device in self.devices.items():
            native.i2c_controller_attach(path, address, device)

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
        # 🐧 The stock kernel has no driver for it: `I2C_OCORES` is not set.
        if dialect == "linux":
            return None
        return DeviceNode(
            "i2c",
            ((reached["cpu"].address, self.mapped_size),),
            (
                'compatible = "sifive,i2c0";',
                # 🎓 A device on the bus is known by its address, one cell,
                # and has no range of memory.
                "#address-cells = <1>;",
                "#size-cells = <0>;",
                f"clock-frequency = <{self.BUS_HZ}>;",
            ),
        )


class Rtc(Component):
    """A real-time clock: the time of day, and an alarm.

    🎓 A CPU counts time from when it started, and forgets it when it
    stops. A real-time clock keeps the date and time, on a battery of its
    own on a real board, and an operating system sets its own clock from
    it as it starts.

    This is the Goldfish real-time clock: not a chip, but the clock of
    Android's emulator, which QEMU's `virt` machine has too, and which
    Linux's `rtc-goldfish` drives. Map `cpu`, its registers, on a bus;
    `irq` is its interrupt, up when its alarm has gone off.

    `time` is what it reads as the simulation starts: a `datetime` with a
    time zone, or nanoseconds since 1970. It goes on with the simulated
    time, not the wall's. By default it is 1970 itself, as a clock whose
    battery was never in reads.
    """

    implementation = "rtc"
    port_specs = (
        target("cpu"),
        # Firmware that sets no alarm needs no line.
        wire_out("irq", required=False),
    )
    #: The registers take a page.
    mapped_size = 0x1000

    time: datetime.datetime | int = not_a_parameter(default=0)

    def __post_init__(self) -> None:
        if (
            isinstance(self.time, datetime.datetime)
            and self.time.tzinfo is None
        ):
            raise ValueError(
                f"A clock's time {self.time} has no time zone, so which "
                "moment it is cannot be told. Give it one: "
                "datetime.datetime(..., tzinfo=datetime.UTC)."
            )
        if self._time_ns < 0:
            raise ValueError(
                "A clock counts from 1970, and cannot be set before it; "
                f"{self.time} was asked for."
            )

    @property
    def _time_ns(self) -> int:
        """The time it is given, in nanoseconds since 1970."""
        if isinstance(self.time, datetime.datetime):
            since = self.time - datetime.datetime(
                1970, 1, 1, tzinfo=datetime.UTC
            )
            return since // datetime.timedelta(microseconds=1) * 1_000
        return self.time

    @property
    @override
    def parameters(self) -> dict[str, int]:
        return {**super().parameters, "time_ns": self._time_ns}

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return DeviceNode(
            "rtc",
            ((reached["cpu"].address, self.mapped_size),),
            ('compatible = "google,goldfish-rtc";',),
            # Zephyr's own test of a clock looks for this name.
            aliases=("rtc",),
        )


class Ns16550(Component):
    """A 16550-style UART: the serial port a firmware's console prints through.

    What the firmware transmits is kept, and the placed UART's `output`
    reads it. What it is to receive is typed with the placed UART's
    `write`. The model is borrowed from VPV-Peripherals (the PULPino UART).

    `irq` is high while an interrupt the firmware enabled is pending: a
    received byte is waiting, or the transmit register has emptied. A
    console that is polled leaves it unconnected.
    """

    implementation = "ns16550"
    port_specs = (target("socket"), wire_out("irq", required=False))
    #: The 16550's eight registers, one byte each.
    mapped_size = 8

    @override
    def place(self, platform: Platform, path: str) -> PlacedUart:
        return PlacedUart(platform, path, self)

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return DeviceNode(
            # Linux's bindings name a node by what it is, generically.
            "uart" if dialect == "zephyr" else "serial",
            ((reached["socket"].address, self.mapped_size),),
            (
                'compatible = "ns16550";',
                # The registers are one byte apart.
                "reg-shift = <0>;",
                # The clock a real 16550 divides down to get its baud rate.
                # A driver wants to know it. The model sends each byte the
                # instant it is written, so the number changes nothing.
                "clock-frequency = <3686400>;",
            ),
            chosen=("zephyr,console", "zephyr,shell-uart"),
            # Zephyr's 16550 driver is one that asks.
            short_interrupts=True,
        )
