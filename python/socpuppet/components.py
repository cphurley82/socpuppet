"""The catalogue of components a platform can be described with.

Each class here describes one implementation in the C++ registry: its name
there, its parameters and its ports. Describing a platform uses only these
classes, so it works without loading the simulator.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator
from typing import TYPE_CHECKING, NamedTuple, Protocol, override

if TYPE_CHECKING:
    from socpuppet import _core
    from socpuppet.ops import Operation

#: A script: a generator function that yields operations. What a read
#: returned is sent back into the generator. The type asks only for the
#: yields, so a script may be annotated as an Iterator or as any Generator.
Script = Callable[[], Iterator["Operation"]]


class DeviceNode(NamedTuple):
    """How a component appears in a devicetree: one node.

    A devicetree tells firmware what hardware exists and where.
    """

    #: The node's name, before the `@address`.
    name: str
    #: The node's registers, as (address, size) ranges. The first one's
    #: address is the one after the `@`.
    reg: tuple[tuple[int, int], ...]
    #: The node's other properties, one line each, such as
    #: `compatible = "x";`. The first should say what the device is.
    properties: tuple[str, ...]
    #: Whether the node goes under `soc`, with the other devices on the bus.
    #: Memory does not: by convention it sits at the top of the tree.
    on_bus: bool = True
    #: The `chosen` properties this node can fill, such as `zephyr,console`.
    chosen: tuple[str, ...] = ()


class Component(ABC):
    """One block of a platform, as described (not yet built)."""

    #: The name of the implementation in the C++ registry.
    implementation: str

    #: Whether the component is one whose view of memory a peek, a poke or
    #: the devicetree takes: a CPU or its stand-in. A device that only
    #: starts accesses for DMA is not one.
    is_bus_master: bool = False

    #: How many bytes of address space the component answers to, or None
    #: for a component that cannot be mapped onto a router.
    mapped_size: int | None = None

    def __init__(self, **parameters: int) -> None:
        self._parameters = parameters

    @property
    @abstractmethod
    def ports(self) -> tuple[str, ...]:
        """The names of the component's ports."""

    @property
    def parameters(self) -> dict[str, int]:
        """What the implementation is configured with, by name."""
        return self._parameters

    def configure(self, native: _core.Platform, path: str) -> None:
        """Hand the built component anything its parameters cannot carry.

        Most components have nothing to hand over, so this does nothing
        unless a component overrides it.
        """
        return

    def refuse_image(
        self, *, image: str, xlen: int, entry: int, path: str
    ) -> None:
        """Raise if a program image loaded through this component cannot run.

        `image` is the file, built for a word size of `xlen` bits and
        starting at `entry`. `path` is where this component is placed. Most
        components run no program and have no objection.
        """
        return

    def device_node(self, base: int) -> DeviceNode | None:
        """The devicetree node for this component mapped at `base`.

        None for a component that firmware has no driver for and need not
        know about.
        """
        return None

    def cpu_node(self, label: str) -> tuple[str, ...] | None:
        """This component's `cpu` node in a devicetree, labelled `label`.

        The node's lines, from `label: cpu@0 {` to its closing `};`. None
        for anything that is not a CPU.
        """
        return None

    def interrupt_input(self, port: str, label: str) -> str | None:
        """How a devicetree refers to an interrupt arriving at `port`.

        A device whose interrupt line is connected to this port gets
        `interrupts-extended = <...>` with what this returns inside, such
        as `&plic 5 1`. `label` is this component's own label. None if
        `port` is not an interrupt input.
        """
        return None

    def routes(self, port: str) -> Iterable[tuple[str, int]]:
        """Where an access arriving at `port` can go next.

        Yields (output port, base): an access at `base` comes out of that
        port as address 0. A component that answers accesses itself, like a
        memory, yields nothing.
        """
        return ()


class BehavioralNvme(Component):
    """🎭 Stand-in for an NVMe SSD.

    It answers the host itself: queues, Identify, reads and writes, kept in
    RAM. There is no CPU or firmware behind the curtain, and no PCIe around
    it either: `bar0` is the register block a PCIe endpoint would put
    behind its first base address register, `dma` is how it reads and
    writes the host's memory, and `irq0`, `irq1` and so on are its
    interrupt lines, one per vector.

    `blocks` is how many 512-byte blocks the drive holds. `vectors` is how
    many interrupt lines it has: the admin queue uses the first, and a host
    may give each I/O queue one of the others.
    """

    implementation = "behavioral_nvme"
    #: The controller registers take the first 4 KiB, and the doorbells
    #: come after them.
    mapped_size = 0x2000

    def __init__(self, *, blocks: int, vectors: int = 2) -> None:
        super().__init__(blocks=blocks, vectors=vectors)

    @property
    def ports(self) -> tuple[str, ...]:
        """The register block, the DMA port, and one port per interrupt line."""
        return (
            "bar0",
            "dma",
            *(f"irq{vector}" for vector in range(self.parameters["vectors"])),
        )


class DbtRiseCpu(Component):
    """A RISC-V CPU that runs real firmware.

    The model is DBT-RISE-RISCV (Minres), an instruction-set simulator: it
    executes the firmware's instructions one after another, the way the
    processor would. `xlen` is the width of its registers in bits, 32 or
    64 (XLEN is the RISC-V specification's name for it), and `reset_vector`
    is the address of the first instruction.

    With a `gdb_port`, the CPU listens for a debugger on that TCP port, and
    waits for one to attach before it executes anything. ⚠️ Only one CPU
    in a simulation can have one.

    It is an RV32IMAC or RV64IMAC core in machine mode only: no floating
    point, and no supervisor or user mode. Build firmware for it with
    `-march=rv32imac_zicsr_zifencei` or `-march=rv64imac_zicsr_zifencei`.
    """

    implementation = "dbt_rise_cpu"
    ports = ("socket", "irq", "timer_irq", "reset")
    is_bus_master = True

    def __init__(
        self, *, xlen: int, reset_vector: int, gdb_port: int = 0
    ) -> None:
        super().__init__(
            xlen=xlen, reset_vector=reset_vector, gdb_port=gdb_port
        )
        self.xlen = xlen
        self.reset_vector = reset_vector

    @override
    def cpu_node(self, label: str) -> tuple[str, ...]:
        # Every RISC-V CPU has an interrupt controller inside it: the
        # handful of interrupt inputs the core itself has. Devices refer to
        # it, not to the CPU, which is why it has a label of its own.
        return (
            f"{label}: cpu@0 {{",
            '\tdevice_type = "cpu";',
            '\tcompatible = "riscv";',
            "\treg = <0>;",
            f'\triscv,isa-base = "rv{self.xlen}i";',
            '\triscv,isa-extensions = "i", "m", "a", "c", "zicsr", "zifencei";',
            "",
            f"\t{label}_intc: interrupt-controller {{",
            '\t\tcompatible = "riscv,cpu-intc";',
            "\t\t#address-cells = <0>;",
            "\t\t#interrupt-cells = <1>;",
            "\t\tinterrupt-controller;",
            "\t};",
            "};",
        )

    @override
    def interrupt_input(self, port: str, label: str) -> str | None:
        # RISC-V numbers a CPU's interrupts by their bit in its
        # interrupt-pending register: 7 is the machine timer, 11 the
        # machine external interrupt.
        number = {"timer_irq": 7, "irq": 11}.get(port)
        return None if number is None else f"&{label}_intc {number}"

    @override
    def refuse_image(
        self, *, image: str, xlen: int, entry: int, path: str
    ) -> None:
        if xlen != self.xlen:
            raise ValueError(
                f"{image} is a {xlen}-bit image, and {path} is a "
                f"{self.xlen}-bit CPU. Build the firmware for a "
                f"{self.xlen}-bit core, or describe the CPU with xlen={xlen}."
            )
        if entry != self.reset_vector:
            raise ValueError(
                f"{image} starts at {entry:#x}, and {path} starts executing "
                f"at its reset vector, {self.reset_vector:#x}. Link the "
                "firmware to start there, or describe the CPU with "
                f"reset_vector={entry:#x}."
            )


class MachineTimer(Component):
    """The RISC-V machine timer, which gives an operating system its tick.

    It has a counter, `mtime`, that counts up `frequency_hz` times a second
    of simulated time, and a compare register, `mtimecmp`. Its `irq` is high
    for as long as the counter is at or past the compare value: connect it
    to a CPU's `timer_irq`. The registers are where SiFive's CLINT has them.
    The model is borrowed from VPV-Peripherals (the Minres ACLINT).
    """

    implementation = "machine_timer"
    ports = ("socket", "irq")
    #: As on the CLINT: `mtimecmp` at 0x4000 and `mtime` at 0xBFF8.
    mapped_size = 0x1_0000

    def __init__(self, *, frequency_hz: int = 10_000_000) -> None:
        super().__init__(frequency_hz=frequency_hz)

    @override
    def device_node(self, base: int) -> DeviceNode:
        mtime = base + 0xBFF8
        mtimecmp = base + 0x4000
        return DeviceNode(
            "timer",
            ((mtime, 8), (mtimecmp, 8)),
            (
                'compatible = "riscv,machine-timer";',
                'reg-names = "mtime", "mtimecmp";',
            ),
        )


class Memory(Component):
    """A flat RAM of `size` bytes."""

    implementation = "memory"
    ports = ("socket",)

    def __init__(self, *, size: int) -> None:
        super().__init__(size=size)
        self.mapped_size = size

    @override
    def device_node(self, base: int) -> DeviceNode:
        return DeviceNode(
            "memory",
            ((base, self.parameters["size"]),),
            ('device_type = "memory";',),
            on_bus=False,
            chosen=("zephyr,sram",),
        )


class Ns16550(Component):
    """A 16550-style UART: the serial port a firmware's console prints through.

    What the firmware transmits is kept, and the placed UART's `output`
    reads it. The model is borrowed from VPV-Peripherals (the PULPino UART).
    Nothing is ever received yet, and the interrupt is not connected.
    """

    implementation = "ns16550"
    ports = ("socket",)
    #: The 16550's eight registers, one byte each.
    mapped_size = 8

    @override
    def device_node(self, base: int) -> DeviceNode:
        return DeviceNode(
            "uart",
            ((base, self.mapped_size),),
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
        )


class PassThroughLinkEndpoint(Component):
    """🎭 One end of a pass-through link.

    `Platform.link()` places these in pairs.
    """

    implementation = "pass_through_link_endpoint"
    ports = ("target", "initiator", "peer_initiator", "peer_target")

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int]]:
        # Out to the other endpoint, or in from it.
        return (
            (("peer_initiator", 0),)
            if port == "target"
            else (("initiator", 0),)
        )


class LinkModel(Protocol):
    """A kind of link, which `Platform.link()` can place."""

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        ...


class PassThroughLink:
    """🎭 Stand-in for the die-to-die link.

    It passes every transaction on, unchanged. Hand it to `Platform.link()`.
    It keeps the real link's shape (one
    endpoint per die, traffic both ways) and leaves out everything else: no
    training, no latency, no errors.
    """

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        return PassThroughLinkEndpoint()


class Plic(Component):
    """The RISC-V platform-level interrupt controller (PLIC).

    It is where the interrupt lines of a platform's devices meet. Connect a
    device's interrupt to one of `source1` to `source31`, and `irq` to the
    CPU's `irq`. The firmware gives each source a priority and enables the
    ones it wants. The model is borrowed from VPV-Peripherals.
    """

    implementation = "plic"
    #: The PLIC numbers its sources from 1. 0 means "no interrupt".
    SOURCES = 31
    ports = (
        "socket",
        "irq",
        *(f"source{number}" for number in range(1, SOURCES + 1)),
    )
    #: The PLIC's registers are spread over 64 MB of address space.
    mapped_size = 0x400_0000

    @override
    def device_node(self, base: int) -> DeviceNode:
        return DeviceNode(
            "interrupt-controller",
            ((base, self.mapped_size),),
            (
                'compatible = "sifive,plic-1.0.0";',
                "#address-cells = <0>;",
                # An interrupt is named by two numbers: source and priority.
                "#interrupt-cells = <2>;",
                "interrupt-controller;",
                "riscv,max-priority = <7>;",
                # Source 0, which means "none", counts as one.
                f"riscv,ndev = <{self.SOURCES + 1}>;",
            ),
        )

    @override
    def interrupt_input(self, port: str, label: str) -> str | None:
        if not port.startswith("source"):
            return None
        # The source's number, and the priority the firmware gives it unless
        # it chooses another: 1, the lowest that can interrupt.
        return f"&{label} {port.removeprefix('source')} 1"


class ScriptedBusMaster(Component):
    """🎭 Stand-in for a CPU.

    It plays a script of bus operations instead of running firmware.
    `script` is a generator function that yields operations (see
    `socpuppet.ops`). It is called again after each reset, so the script
    starts over. With no script, the master does nothing.
    """

    implementation = "scripted_bus_master"
    ports = ("socket", "irq", "timer_irq", "reset")
    is_bus_master = True

    def __init__(self, script: Script | None = None) -> None:
        super().__init__()
        if script is not None and not inspect.isgeneratorfunction(script):
            if inspect.isgenerator(script):
                raise TypeError(
                    "A script must be a generator function, and this is a "
                    "generator that has already been started. Pass the "
                    "function itself, without calling it: "
                    "ScriptedBusMaster(script), not "
                    "ScriptedBusMaster(script())."
                )
            raise TypeError(
                f"A script must be a generator function, and {script!r} "
                "never yields. Write it as a function that yields operations, "
                "such as `yield sp.write32(address, value)`."
            )
        self.script = script

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        if self.script is not None:
            native.set_script(path, self.script)


class Router(Component):
    """An address decoder.

    It sends each access to the target mapped at its address. The model is
    `scc::router` from SystemC-Components. Map targets onto it with `map()`
    and give a second source of accesses an input of its own with
    `add_input()`, both on the placed router.
    """

    implementation = "router"

    def __init__(self) -> None:
        self._inputs = 1
        # (base, size, label), one per output
        self._ranges: list[tuple[int, int, str]] = []

    @property
    def ports(self) -> tuple[str, ...]:
        """One port per input, then one output port per mapped range.

        The first input is `target`, and the ones added after it are `in1`,
        `in2` and so on.
        """
        return (
            "target",
            *(f"in{index}" for index in range(1, self._inputs)),
            *(f"out{index}" for index in range(len(self._ranges))),
        )

    @property
    def parameters(self) -> dict[str, int]:
        """The address map, flattened to the form the simulator takes.

        That form is name -> number: "inputs" and "outputs", then
        "out<N>.base" and "out<N>.size" per output.
        """
        flat = {"inputs": self._inputs, "outputs": len(self._ranges)}
        for index, (base, size, _) in enumerate(self._ranges):
            flat[f"out{index}.base"] = base
            flat[f"out{index}.size"] = size
        return flat

    @override
    def routes(self, port: str) -> Iterator[tuple[str, int]]:
        for index, (base, _, _) in enumerate(self._ranges):
            yield f"out{index}", base

    def add_input(self) -> str:
        """Add an input for one more source of accesses.

        Returns the input's port name.
        """
        self._inputs += 1
        return f"in{self._inputs - 1}"

    def add_output(self, base: int, size: int, label: str) -> str:
        """Add an output for the range [base, base + size).

        Returns the output's port name. `label` says what the range leads
        to, for error messages.
        """
        for other_base, other_size, other_label in self._ranges:
            if base < other_base + other_size and other_base < base + size:
                other_end = other_base + other_size - 1
                raise ValueError(
                    f"{label} at {base:#x}..{base + size - 1:#x} overlaps "
                    f"{other_label} at {other_base:#x}..{other_end:#x}. "
                    "Each address can lead to only one target."
                )
        self._ranges.append((base, size, label))
        return f"out{len(self._ranges) - 1}"
