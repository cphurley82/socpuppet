"""The catalogue of components a platform can be described with.

Each class here describes one implementation in the C++ registry: its name
there, its parameters and its ports. Describing a platform uses only these
classes, so it works without loading the simulator.

A component's parameters are its fields, written as a dataclass's are, and
its ports are a tuple of `PortSpec`:

    class MachineTimer(Component):
        implementation = "machine_timer"
        port_specs = (target("socket"), wire_out("irq"))

        frequency_hz: int = 10_000_000
"""

from __future__ import annotations

import dataclasses
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator, Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    NamedTuple,
    Protocol,
    dataclass_transform,
    override,
)

from socpuppet.placed import Placed, PlacedRouter, PlacedUart
from socpuppet.regs import dma_engine

if TYPE_CHECKING:
    from socpuppet import _core
    from socpuppet.address_map import Reached
    from socpuppet.ops import Operation
    from socpuppet.platform import Platform

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


def cells(value: int) -> str:
    """A 64-bit value as two 32-bit devicetree cells, high half first."""
    return f"{value >> 32:#x} {value & 0xFFFF_FFFF:#x}"


class PortSpec(NamedTuple):
    """One port of a component: its name, and what it connects to."""

    name: str
    #: "bus" for a memory-mapped socket, and "wire" for a single line, such
    #: as an interrupt or a reset.
    kind: Literal["bus", "wire"]
    #: "source" for where a connection is driven from (a bus master's
    #: socket, or the port driving a wire), and "sink" for where it arrives.
    role: Literal["source", "sink"]
    #: Whether the port must be connected before the platform is built.
    required: bool = True


def initiator(name: str, required: bool = True) -> PortSpec:
    """A socket that accesses go out of.

    🎓 "Initiator" is TLM's word for whoever starts a transaction.
    """
    return PortSpec(name, "bus", "source", required)


def target(name: str, required: bool = True) -> PortSpec:
    """A socket that accesses arrive at."""
    return PortSpec(name, "bus", "sink", required)


def wire_out(name: str, required: bool = True) -> PortSpec:
    """A line the component drives."""
    return PortSpec(name, "wire", "source", required)


def wire_in(name: str) -> PortSpec:
    """A line the component reads. Left unconnected, it reads as low."""
    return PortSpec(name, "wire", "sink", required=False)


def not_a_parameter(default: Any) -> Any:
    """A field the simulator is not configured with, and its default.

    For what a component is handed that is not a number, such as a script.
    """
    return dataclasses.field(
        default=default, kw_only=False, metadata={"parameter": False}
    )


@dataclass_transform(
    kw_only_default=True,
    eq_default=False,
    field_specifiers=(dataclasses.field, not_a_parameter),
)
class Component(ABC):
    """One block of a platform, as described (not yet built).

    A subclass is a dataclass without saying so: each annotated attribute
    is a parameter, given by keyword, and one with a value has a default.
    A keyword the class does not have is refused when the component is
    created.
    """

    #: The name of the implementation in the C++ registry.
    implementation: ClassVar[str]

    #: Whether the component is one whose view of memory a peek, a poke or
    #: the devicetree takes: a CPU or its stand-in. A device that only
    #: starts accesses for DMA is not one.
    is_bus_master: ClassVar[bool] = False

    #: How many bytes of address space the component answers to, or None
    #: for a component that cannot be mapped onto a router.
    mapped_size: int | None = None

    def size_at(self, port: str) -> int | None:
        """How many bytes of address space the component answers to at `port`.

        It is `mapped_size`, whichever port, unless a component with more
        than one register block says otherwise. None means the component
        has no size of its own there.
        """
        return self.mapped_size

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Two components are the same only if they are one object, so that
        # two memories of one size can be told apart.
        dataclasses.dataclass(kw_only=True, eq=False)(cls)

    @property
    @abstractmethod
    def port_specs(self) -> tuple[PortSpec, ...]:
        """The component's ports."""

    @property
    def ports(self) -> tuple[str, ...]:
        """The names of the component's ports."""
        return tuple(spec.name for spec in self.port_specs)

    @property
    def parameters(self) -> dict[str, int]:
        """What the implementation is configured with, by name."""
        return {
            each.name: getattr(self, each.name)
            for each in dataclasses.fields(self)  # type: ignore[arg-type]
            if each.metadata.get("parameter", True)
        }

    def place(self, platform: Platform, path: str) -> Placed:
        """This component at `path` in `platform`, with its ports."""
        return Placed(platform, path, self)

    def configure(self, native: _core.Platform, path: str) -> None:
        """Hand the built component anything its parameters cannot carry.

        Most components have nothing to hand over, so this does nothing
        unless a component overrides it.
        """
        return

    def located_parameters(
        self, path: str, address_of: Callable[[str], int | None]
    ) -> dict[str, int]:
        """The parameters that depend on where the component ended up.

        They are worked out from the description, and added to
        `parameters`. `path` is where the component is placed, and
        `address_of(port)` is the address at which a bus master finds one
        of its ports, or None if none can reach it. Most components have
        none, and an override raises if the description does not yet say
        enough.
        """
        return {}

    def refuse_image(
        self, *, image: str, xlen: int, entry: int, path: str
    ) -> None:
        """Raise if a program image loaded through this component cannot run.

        `image` is the file, built for a word size of `xlen` bits and
        starting at `entry`. `path` is where this component is placed. Most
        components run no program and have no objection.
        """
        return

    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode | None:
        """The devicetree node for this component, where a bus master finds it.

        `reached` has each of the component's ports that the bus master can
        reach, by name: the address it finds the port at, and how many
        bytes of it can be reached there. None is returned for a component
        that firmware has no driver for and need not know about.
        """
        return None

    def cpu_node(self, label: str) -> tuple[str, ...] | None:
        """This component's `cpu` node in a devicetree, labelled `label`.

        The node's lines, from `label: cpu@0 {` to its closing `};`. None
        for anything that is not a CPU.
        """
        return None

    def interrupt_number(self, port: str) -> int | None:
        """Which of this component's interrupts a line arriving at `port` is.

        The number is what firmware knows the line by. None if `port` is
        not an interrupt input, or is one with no number.
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

    def routes(self, port: str) -> Iterable[tuple[str, int, int | None]]:
        """Where an access arriving at `port` can go next.

        Yields (output port, base, size): an access at `base` comes out of
        that port as address 0, and `size` is how many bytes from there on
        go the same way, or None if all do. A component that answers
        accesses itself, like a memory, yields nothing.
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

    blocks: int
    vectors: int = 2

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """The register block, the DMA port, and one port per interrupt line."""
        return (
            target("bar0"),
            initiator("dma"),
            # A host need not use every vector.
            *(
                wire_out(f"irq{vector}", required=False)
                for vector in range(self.vectors)
            ),
        )


#: What a CPU and its stand-in both have: the socket their accesses go out
#: of, and their three inputs.
_CPU_PORTS = (
    initiator("socket"),
    wire_in("irq"),
    wire_in("timer_irq"),
    wire_in("reset"),
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
    port_specs = _CPU_PORTS
    is_bus_master = True

    xlen: int
    reset_vector: int
    gdb_port: int = 0

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
    def interrupt_number(self, port: str) -> int | None:
        # RISC-V numbers a CPU's interrupts by their bit in its
        # interrupt-pending register: 7 is the machine timer, 11 the
        # machine external interrupt.
        return {"timer_irq": 7, "irq": 11}.get(port)

    @override
    def interrupt_input(self, port: str, label: str) -> str | None:
        number = self.interrupt_number(port)
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


class DmaEngine(Component):
    """The part of an SSD's controller that copies to and from the host.

    🎓 DMA is direct memory access: a device reading and writing memory by
    itself. The SSD's CPU says where in the host's memory, where in the
    SSD's own, and how many bytes, and the engine copies them one way or
    the other. `cpu` is its register block, `host` is how it reaches the
    host's memory, `local` the SSD's own, and `irq` is high while it has
    something to tell the CPU, if the CPU asked to be told.
    """

    implementation = "dma_engine"
    port_specs = (
        target("cpu"),
        initiator("host"),
        initiator("local"),
        # Firmware may poll the status register and leave the line alone.
        wire_out("irq", required=False),
    )
    #: What the engine's register map says it takes.
    mapped_size = dma_engine.SIZE

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        return DeviceNode(
            "dma-controller",
            ((reached["cpu"].address, self.mapped_size),),
            ('compatible = "socpuppet,dma-engine";',),
        )


class FlashController(Component):
    """The part of an SSD's controller that works the NAND flash chip.

    The SSD's CPU says which page of the chip, and where the page is in the
    SSD's own memory, and the controller moves it one way or the other, or
    erases a block. `cpu` is its register block, `local` is how it reads
    and writes the SSD's memory, `nand` is the chip, and `irq` is high
    while it has something to tell the CPU, if the CPU asked to be told.
    """

    implementation = "flash_controller"
    port_specs = (
        target("cpu"),
        initiator("local"),
        initiator("nand"),
        # Firmware may poll the status register and leave the line alone.
        wire_out("irq", required=False),
    )
    #: Twelve 32-bit registers, three of them reserved.
    mapped_size = 0x30

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        return DeviceNode(
            "nand-controller",
            ((reached["cpu"].address, self.mapped_size),),
            ('compatible = "socpuppet,flash-controller";',),
        )


class IdealNand(Component):
    """🎭 Stand-in for a NAND flash chip.

    🎓 NAND flash is what an SSD keeps its data in. It is read and
    programmed a page at a time and erased a block at a time, a block
    being many pages. `page_size` is a page in bytes, `pages_per_block`
    how many make a block, and `blocks` how many blocks the chip has.

    This one is ideal: nothing takes any time, and a page can be
    programmed again without its block being erased first, which no real
    chip allows. A flash controller reaches it through `socket`.
    """

    implementation = "ideal_nand"
    port_specs = (target("socket"),)

    blocks: int
    pages_per_block: int = 64
    page_size: int = 4096


class MachineTimer(Component):
    """The RISC-V machine timer, which gives an operating system its tick.

    It has a counter, `mtime`, that counts up `frequency_hz` times a second
    of simulated time, and a compare register, `mtimecmp`. Its `irq` is high
    for as long as the counter is at or past the compare value: connect it
    to a CPU's `timer_irq`. The registers are where SiFive's CLINT has them.
    The model is borrowed from VPV-Peripherals (the Minres ACLINT).
    """

    implementation = "machine_timer"
    port_specs = (target("socket"), wire_out("irq"))
    #: As on the CLINT: `mtimecmp` at 0x4000 and `mtime` at 0xBFF8.
    mapped_size = 0x1_0000

    frequency_hz: int = 10_000_000

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        base = reached["socket"].address
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
    port_specs = (target("socket"),)

    size: int

    def __post_init__(self) -> None:
        self.mapped_size = self.size

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        socket = reached["socket"]
        size = (
            self.size if socket.limit is None else min(self.size, socket.limit)
        )
        return DeviceNode(
            "memory",
            # A memory mapped through a smaller range is, to the firmware, a
            # memory of that size.
            ((socket.address, size),),
            ('device_type = "memory";',),
            on_bus=False,
            chosen=("zephyr,sram",),
        )


class MsiPlicBridge(Component):
    """Turns message-signalled interrupts into lines, for a PLIC.

    A PCIe device interrupts by writing a message to an address the host
    chose, and a PLIC only has lines. Map this where the host has those
    messages sent, and connect `irq0`, `irq1` and so on to sources of the
    PLIC. A message's data is the number of a vector, and that vector's
    line pulses: it rises, and falls again by itself. `vectors` is how many
    lines there are.
    """

    implementation = "msi_plic_bridge"
    #: One 32-bit register.
    mapped_size = 4

    vectors: int

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """The register, and one port per interrupt line."""
        return (
            target("socket"),
            *(wire_out(f"irq{vector}") for vector in range(self.vectors)),
        )

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        return DeviceNode(
            "msi-controller",
            ((reached["socket"].address, self.mapped_size),),
            (
                'compatible = "socpuppet,msi-plic-bridge";',
                # What a devicetree marks anything that takes interrupt
                # messages with.
                "msi-controller;",
            ),
        )


class MsiReceiver(Component):
    """🎭 Stand-in for what takes a host's message-signalled interrupts.

    A PCIe device interrupts by writing a message to an address the host
    chose. Map this where the host has those messages sent, and connect
    `irq` to the host. A message's data is the number of a vector, 0 to
    31. `irq` is high while any vector is waiting, and reading the
    register returns the waiting vectors, one bit each, and clears them.
    """

    implementation = "msi_receiver"
    port_specs = (target("socket"), wire_out("irq"))
    #: One 32-bit register.
    mapped_size = 4


class Ns16550(Component):
    """A 16550-style UART: the serial port a firmware's console prints through.

    What the firmware transmits is kept, and the placed UART's `output`
    reads it. The model is borrowed from VPV-Peripherals (the PULPino UART).
    Nothing is ever received yet, and the interrupt is not connected.
    """

    implementation = "ns16550"
    port_specs = (target("socket"),)
    #: The 16550's eight registers, one byte each.
    mapped_size = 8

    @override
    def place(self, platform: Platform, path: str) -> PlacedUart:
        return PlacedUart(platform, path, self)

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        return DeviceNode(
            "uart",
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
        )


class NvmeFrontend(Component):
    """The NVMe frontend of an SSD's controller.

    The hardware between the host and the SSD's firmware: it keeps the
    queues, and the firmware makes the decisions. It fetches each command
    the host submits and holds it for the SSD's CPU, and when the firmware
    says how the command went it posts the completion and interrupts the
    host.

    To the host it is an NVMe function with no PCIe around it, as
    `BehavioralNvme` is: `bar0` is its register block, `dma` is how it
    reads and writes the host's memory, and `irq0`, `irq1` and so on are
    its interrupt lines, one per vector. To the SSD's own CPU it is a
    device on its bus: `cpu` is a second register block, and `cpu_irq` is
    high while the frontend has something to tell the CPU that the CPU
    asked to be told.

    `vectors` is how many interrupt lines it has for the host: the admin
    queue uses the first, and firmware gives each I/O queue the one the
    host asked for.
    """

    implementation = "nvme_frontend"
    #: The host's register block: the controller registers take the first
    #: 4 KiB, and the doorbells come after them.
    BAR0_SIZE: ClassVar[int] = 0x2000
    #: The CPU's register block: fourteen registers, then the 64 bytes of
    #: the command that is waiting.
    CPU_SIZE: ClassVar[int] = 0x80

    vectors: int = 2

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """Two register blocks, the DMA port, and the interrupt lines."""
        return (
            target("bar0"),
            initiator("dma"),
            target("cpu"),
            # Firmware may poll the status register and leave the line alone.
            wire_out("cpu_irq", required=False),
            # A host need not use every vector.
            *(
                wire_out(f"irq{vector}", required=False)
                for vector in range(self.vectors)
            ),
        )

    @override
    def size_at(self, port: str) -> int | None:
        return {"bar0": self.BAR0_SIZE, "cpu": self.CPU_SIZE}.get(port)

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode | None:
        # The node is for the SSD's own firmware, which reaches the CPU's
        # register block. A host finds the other one by scanning its PCIe
        # bus, as an NVMe drive's.
        cpu = reached.get("cpu")
        if cpu is None:
            return None
        return DeviceNode(
            "nvme-frontend",
            ((cpu.address, self.CPU_SIZE),),
            ('compatible = "socpuppet,nvme-frontend";',),
        )


class PassThroughLinkEndpoint(Component):
    """🎭 One end of a pass-through link.

    `Platform.link()` places these in pairs.
    """

    implementation = "pass_through_link_endpoint"
    # The die's side may be left unconnected in either direction. The other
    # side is the other endpoint.
    port_specs = (
        target("target", required=False),
        initiator("initiator", required=False),
        initiator("peer_initiator"),
        target("peer_target"),
    )

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int, int | None]]:
        # Out to the other endpoint, or in from it.
        return (
            (("peer_initiator", 0, None),)
            if port == "target"
            else (("initiator", 0, None),)
        )


class D2dLinkEndpoint(Component):
    """One end of the die-to-die (D2D) link, in the style of UCIe.

    `Platform.link()` places these in pairs. There are two paths between
    the dies, as there are on real hardware. The mainband (`target` and
    `initiator`) is the wide one that carries the dies' traffic, and it
    carries nothing until the link has been trained. The sideband is the
    narrow management one, which is up from the start: `sideband` is the
    link's own registers, as this die's firmware reaches them.

    `reset` is the line this end holds on its own die until the other die
    writes a zero to this end's reset register, and `irq` is how the link
    tells this die's firmware that something has happened.
    """

    implementation = "d2d_link_endpoint"
    #: What the register block takes, which is UCIe's Link DVSEC and the
    #: blocks it points at.
    REGISTERS_SIZE: ClassVar[int] = 0x100
    # Everything on the die's own side is optional: a die may only send,
    # only receive, or leave the link's registers unmapped. Both peer
    # sides are the other endpoint.
    port_specs = (
        target("target", required=False),
        initiator("initiator", required=False),
        initiator("peer_initiator"),
        target("peer_target"),
        target("sideband", required=False),
        initiator("sideband_peer_initiator"),
        target("sideband_peer_target"),
        wire_out("reset", required=False),
        wire_out("irq", required=False),
    )

    #: How long the link takes to carry anything across.
    latency_ns: int = 20
    #: How many bytes of it go in a nanosecond.
    bytes_per_ns: int = 16
    #: How long training takes, once UCIe's 4 ms reset hold is over.
    training_ns: int = 1_000_000

    @override
    def size_at(self, port: str) -> int | None:
        # Only the registers have a size of their own. A window onto the
        # other die is as big as whoever maps it says.
        return self.REGISTERS_SIZE if port == "sideband" else None

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int, int | None]]:
        if port == "target":
            return (("peer_initiator", 0, None),)
        if port == "peer_target":
            return (("initiator", 0, None),)
        # The registers are where an access stops, not something it
        # crosses.
        return ()

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode | None:
        registers = reached.get("sideband")
        if registers is None:
            return None
        return DeviceNode(
            "ucie-link",
            ((registers.address, self.REGISTERS_SIZE),),
            (
                'compatible = "socpuppet,ucie-link";',
                # Zephyr's reset controller class: one number names which
                # line to let go, and this link has one, the other die.
                "#reset-cells = <1>;",
            ),
        )


class LinkModel(Protocol):
    """A kind of link, which `Platform.link()` can place."""

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        ...

    def peer_pairs(self) -> Iterable[tuple[str, str]]:
        """The ports that join two endpoints, as (source, sink) names.

        `Platform.link()` connects each pair in both directions.
        """
        ...


@dataclasses.dataclass(frozen=True, kw_only=True)
class D2dLink:
    """The die-to-die link, in the style of UCIe.

    Hand it to `Platform.link()`. It has to be trained before its mainband
    carries anything, which the firmware on one of the dies does through
    the link's registers (`D2dLinkEndpoint`).

    💡 The times are plain numbers of nanoseconds: `latency_ns` is how long
    a crossing takes, `bytes_per_ns` how wide the link is, and
    `training_ns` how long SBINIT to ACTIVE takes after UCIe's 4 ms reset
    hold.
    """

    latency_ns: int = D2dLinkEndpoint.latency_ns
    bytes_per_ns: int = D2dLinkEndpoint.bytes_per_ns
    training_ns: int = D2dLinkEndpoint.training_ns

    def endpoint(self) -> Component:
        """A new endpoint, for one end of the link."""
        return D2dLinkEndpoint(
            latency_ns=self.latency_ns,
            bytes_per_ns=self.bytes_per_ns,
            training_ns=self.training_ns,
        )

    def peer_pairs(self) -> Iterable[tuple[str, str]]:
        """The mainband and the sideband, each joining the two ends."""
        return (
            ("peer_initiator", "peer_target"),
            ("sideband_peer_initiator", "sideband_peer_target"),
        )


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

    def peer_pairs(self) -> Iterable[tuple[str, str]]:
        """Just the one path: everything crosses the same way."""
        return (("peer_initiator", "peer_target"),)


class PcieEndpoint(Component):
    """What stands between a PCIe link and a function that knows no PCIe.

    The function, such as `BehavioralNvme`, has a register block, a DMA
    port and interrupt lines. The endpoint puts PCIe around them: it says
    what the device is, lets the host place the register block in its
    address map, and passes the function's DMA up the link.

    `vendor_id` and `device_id` say who made the device and which device it
    is, and `class_code` what kind of device it is, as three bytes: class,
    subclass and programming interface (0x010802 for an NVMe drive).
    `function_size` is how many bytes the function's register block takes,
    and `vectors` how many interrupt lines it has.
    """

    implementation = "pcie_endpoint"

    vendor_id: int
    device_id: int
    class_code: int
    function_size: int
    vectors: int

    def __post_init__(self) -> None:
        if not 1 <= self.vectors <= 2048:
            raise ValueError(
                f"A PCIe endpoint has 1 to 2048 interrupt vectors, which is "
                f"what an MSI-X table can hold, and {self.vectors} were "
                "asked for."
            )

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """The link, the function's three kinds of port, one line per vector."""
        return (
            target("from_host"),
            initiator("to_host"),
            initiator("bar0"),
            target("dma"),
            *(wire_in(f"irq{vector}") for vector in range(self.vectors)),
        )


class PcieRootComplex(Component):
    """Where a host's bus meets a PCIe link.

    The host reaches the device on the link through two windows that are
    mapped onto its bus: `ecam`, the configuration window, and `mmio`, the
    memory window. Whatever the device sends up the link (DMA, and
    interrupts as messages) comes out of `dma`.

    💡 The root complex has to know the address at which the host sees the
    start of the memory window, because a bus hands a target offsets into
    its window, and the device compares addresses on the host's bus. It
    works that out from where the window is mapped, so there is nothing to
    tell it.
    """

    implementation = "pcie_root_complex"
    port_specs = (
        target("ecam"),
        target("mmio"),
        initiator("dma"),
        initiator("to_device"),
        target("from_device"),
    )

    @override
    def located_parameters(
        self, path: str, address_of: Callable[[str], int | None]
    ) -> dict[str, int]:
        mmio_base = address_of("mmio")
        if mmio_base is None:
            raise ValueError(
                f"The PCIe root complex at {path} needs to know where the "
                f"host sees its memory window, and no bus master can reach "
                f"{path}.mmio. Map it onto the host's bus with map(<the "
                "root complex>.mmio, base=..., size=...), and connect a "
                "bus master to that bus."
            )
        return {"mmio_base": mmio_base}

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode | None:
        ecam = reached.get("ecam")
        mmio = reached.get("mmio")
        # Firmware can do nothing with one window and not the other.
        if ecam is None or mmio is None:
            return None
        # With both in reach there is a router on the way to each, and a
        # router's range has a size.
        assert ecam.limit is not None
        assert mmio.limit is not None
        # Each bus has 1 MiB of the configuration window: 32 devices of 8
        # functions, with 4 KiB of registers each.
        buses = ecam.limit >> 20
        if buses == 0:
            raise ValueError(
                f"The configuration window at {ecam.port.path} is "
                f"{ecam.limit:#x} bytes, and a devicetree can only describe "
                "whole buses, which take 1 MiB each (0x100000). Map it with "
                "size=0x100000 or more."
            )
        return DeviceNode(
            "pcie",
            ((ecam.address, ecam.limit),),
            (
                'compatible = "socpuppet,pcie";',
                'device_type = "pci";',
                # An address on a PCIe bus is three cells: what kind of
                # space it is in, then the address, high half first.
                "#address-cells = <3>;",
                "#size-cells = <2>;",
                f"bus-range = <0 {buses - 1}>;",
                # The memory window. 0x2000000 says 32-bit memory space,
                # and a device's address there is the CPU's address for
                # it: the root complex does not translate.
                f"ranges = <0x2000000 {cells(mmio.address)} "
                f"{cells(mmio.address)} {cells(mmio.limit)}>;",
            ),
            chosen=("zephyr,pcie-controller",),
        )


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
    port_specs = (
        target("socket"),
        wire_out("irq"),
        *(wire_in(f"source{number}") for number in range(1, SOURCES + 1)),
    )
    #: The PLIC's registers are spread over 64 MB of address space.
    mapped_size = 0x400_0000

    @override
    def device_node(self, reached: Mapping[str, Reached]) -> DeviceNode:
        return DeviceNode(
            "interrupt-controller",
            ((reached["socket"].address, self.mapped_size),),
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
    def interrupt_number(self, port: str) -> int | None:
        if not port.startswith("source"):
            return None
        return int(port.removeprefix("source"))

    @override
    def interrupt_input(self, port: str, label: str) -> str | None:
        number = self.interrupt_number(port)
        # The source's number, and the priority the firmware gives it unless
        # it chooses another: 1, the lowest that can interrupt.
        return None if number is None else f"&{label} {number} 1"


class ScriptedBusMaster(Component):
    """🎭 Stand-in for a CPU.

    It plays a script of bus operations instead of running firmware.
    `script` is a generator function that yields operations (see
    `socpuppet.ops`). It is called again after each reset, so the script
    starts over. With no script, the master does nothing.
    """

    implementation = "scripted_bus_master"
    port_specs = _CPU_PORTS
    is_bus_master = True

    script: Script | None = not_a_parameter(None)

    def __post_init__(self) -> None:
        script = self.script
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

    def __post_init__(self) -> None:
        self._inputs = 1
        # (base, size, label), one per output
        self._ranges: list[tuple[int, int, str]] = []

    @override
    def place(self, platform: Platform, path: str) -> PlacedRouter:
        return PlacedRouter(platform, path, self)

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """One port per input, then one output port per mapped range.

        The first input is `target`, and the ones added after it are `in1`,
        `in2` and so on.
        """
        return (
            target("target"),
            *(target(f"in{index}") for index in range(1, self._inputs)),
            *(initiator(f"out{index}") for index in range(len(self._ranges))),
        )

    @property
    @override
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
    def routes(self, port: str) -> Iterator[tuple[str, int, int | None]]:
        for index, (base, size, _) in enumerate(self._ranges):
            yield f"out{index}", base, size

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
