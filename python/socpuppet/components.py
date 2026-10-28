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
import os
from abc import ABC, abstractmethod
from collections.abc import (
    Callable,
    Collection,
    Iterable,
    Iterator,
    Mapping,
)
from types import MappingProxyType
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

from socpuppet import fuse, ninep
from socpuppet.placed import (
    Placed,
    PlacedBlock,
    PlacedConsole,
    PlacedNand,
    PlacedNet,
    PlacedPciemHost,
    PlacedRouter,
    PlacedUart,
)
from socpuppet.regs import (
    dma_engine,
    flash_controller,
    nvme_frontend,
    system_controller,
    ucie_link,
    virtio_mmio,
)
from socpuppet.spi import SpiDevice

#: Whose bindings a devicetree is written in. 🎓 A devicetree says what
#: hardware there is, and each operating system's drivers look for their
#: own names, numbers of cells and shapes of nodes: its bindings. Zephyr's
#: are what socpuppet's boards are built with, and Linux's are what OpenSBI
#: and Linux read, and EDK2 after them.
type Dialect = Literal["zephyr", "linux"]

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
    #: address is the one after the `@`. A node with none has no `@`.
    reg: tuple[tuple[int, int], ...]
    #: The node's other properties, one line each, such as
    #: `compatible = "x";`. The first should say what the device is.
    properties: tuple[str, ...]
    #: Whether the node goes under `soc`, with the other devices on the bus.
    #: Memory does not: by convention it sits at the top of the tree.
    on_bus: bool = True
    #: The `chosen` properties this node can fill, such as `zephyr,console`.
    #: They are named as Zephyr names them in either dialect: in Linux's,
    #: the node that can be `zephyr,console` is the one `stdout-path` is.
    chosen: tuple[str, ...] = ()
    #: The names in `aliases` this node can take, such as `watchdog0`.
    #: 🎓 An alias is a name firmware agrees on beforehand for "the board's
    #: watchdog", so that one program runs on boards that label theirs
    #: differently.
    aliases: tuple[str, ...] = ()
    #: Which of the component's output lines are this node's interrupts, by
    #: port. None means all of them, which is right for a component that is
    #: one device.
    interrupts: tuple[str, ...] | None = None
    #: Whether the node gives its interrupt the short way, as
    #: `interrupt-parent` and `interrupts`, where it would otherwise have
    #: `interrupts-extended`. The two say the same of a device whose
    #: interrupts go to one controller. ⚠️ Zephyr's Kconfig can see the
    #: short one only, and some drivers' asks it whether their device can
    #: interrupt at all (docs/upstream.md).
    short_interrupts: bool = False
    #: The port the device's interrupt messages leave by, if it interrupts
    #: with messages on behalf of other devices. The node then names what
    #: takes them, as `msi-parent`.
    messages: str | None = None
    #: The port the device's own accesses leave by, its DMA and its
    #: messages, if they may go through an IOMMU on their way. If one is
    #: connected there, the node says so as its component's
    #: `iommu_properties` have it.
    accesses: str | None = None
    #: What the node's label has after the component's, for a component
    #: with more than one node: `_s` makes `imsic` `imsic_s`.
    suffix: str = ""
    #: Nodes inside this one: a child a driver binds to, as Zephyr's virtio
    #: drivers do, or a device on a bus the node controls, as a flash chip
    #: on its SPI controller. A child has no memory-mapped `reg` ranges and
    #: no interrupts of its own: those are the node's.
    children: tuple[DeviceNode, ...] = ()


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


def not_a_parameter(default: Any, *, kw_only: bool = True) -> Any:
    """A field the simulator is not configured with, and its default.

    For what a component is handed that is not a number, such as a script.
    It is given by keyword, as a parameter is, unless `kw_only` is false.
    """
    return dataclasses.field(
        default=default, kw_only=kw_only, metadata={"parameter": False}
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
        self,
        *,
        image: str,
        xlen: int,
        entry: int,
        path: str,
        what_is_at: Callable[[int], Component | None],
    ) -> None:
        """Raise if a program image loaded through this component cannot run.

        `image` is the file, built for a word size of `xlen` bits and
        starting at `entry`. `path` is where this component is placed, and
        `what_is_at(address)` is the component it finds at an address, or
        None. Most components run no program and have no objection.
        """
        return

    def why_a_poke_was_refused(self, path: str) -> str | None:
        """What to tell someone whose `poke` this component turned away.

        `path` is where this component is placed. None for a component
        that takes any write that fits inside it, which is most: its
        refusal is then that the write did not fit.
        """
        return None

    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
        """The devicetree node for this component, where a bus master finds it.

        `reached` has each of the component's ports that the bus master can
        reach, by name: the address it finds the port at, and how many
        bytes of it can be reached there. `dialect` is whose bindings the
        node is in. None is returned for a component that firmware has no
        driver for and need not know about.
        """
        return None

    def device_nodes(
        self, reached: Mapping[str, Reached], *, dialect: Dialect, label: str
    ) -> tuple[DeviceNode, ...]:
        """Each devicetree node of this component, where a bus master finds it.

        Most components are one node, `device_node`'s, and this is that or
        nothing. A component that is more than one node in a dialect says
        so here. `label` is the component's own label, for a node that
        names another of the component's.
        """
        node = self.device_node(reached, dialect=dialect)
        return () if node is None else (node,)

    def cpu_node(
        self, label: str, connected: Collection[str]
    ) -> tuple[str, ...] | None:
        """This component's `cpu` node in a devicetree, labelled `label`.

        The node's lines, from `label: cpu@0 {` to its closing `};`. None
        for anything that is not a CPU. `connected` is which of the
        component's ports have something connected to them, since what a
        CPU is can depend on what it is given.
        """
        return None

    def interrupt_number(self, port: str) -> int | None:
        """Which of this component's interrupts a line arriving at `port` is.

        The number is what firmware knows the line by. None if `port` is
        not an interrupt input, or is one with no number.
        """
        return None

    def interrupt_input(
        self, port: str, label: str, *, dialect: Dialect
    ) -> str | None:
        """How a devicetree refers to an interrupt arriving at `port`.

        A device whose interrupt line is connected to this port gets
        `interrupts-extended = <...>` with what this returns inside, such
        as `&plic 5 1`. `label` is this component's own label, and
        `dialect` whose bindings the reference is in. None if `port` is not
        an interrupt input.
        """
        return None

    def timebase_frequency(self, port: str) -> int | None:
        """How many times a second the count a CPU reads at `port` goes up.

        A CPU whose `time` register is connected to `port` counts time in
        those ticks, and its devicetree says so. None if `port` is no such
        count, which is so of most.
        """
        return None

    def takes_messages(self, port: str, *, dialect: Dialect) -> bool:
        """Whether `port` is where firmware's hart is sent its interrupts.

        True of the page of a message controller that the firmware a
        devicetree in `dialect` is for is sent its interrupts at. A device
        that sends interrupt messages and can reach that page gets
        `msi-parent = <&label>` in its devicetree node, with the label of
        the node of that page.
        """
        return False

    def translates(self, port: str) -> bool:
        """Whether accesses arriving at `port` are a device's, to translate.

        True of an IOMMU's way in. A device whose node has `accesses`, and
        whose accesses arrive here, names this component's node in its own,
        as `iommu_properties` says.
        """
        return False

    def iommu_properties(
        self, iommu: str, *, dialect: Dialect
    ) -> tuple[str, ...]:
        """How this device's node says its accesses go through an IOMMU.

        `iommu` is the label of the IOMMU's node, and `dialect` whose
        bindings the properties are in. Asked of a component whose node has
        `accesses`, when an IOMMU is connected there.
        """
        return ()

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


#: What a RISC-V hart here has besides: where its `time` register is read
#: from (a machine timer's `time`), the supervisor external interrupt, and
#: where its registers that are really an IMSIC's are reached.
_HART_PORTS = (
    *_CPU_PORTS,
    initiator("time", required=False),
    wire_in("supervisor_irq"),
    initiator("csr", required=False),
)


#: The cores a `DbtRiseCpu` can be: what `isa` and `modes` may be together,
#: and at which `xlen`.
_CORES: Mapping[tuple[str, str], tuple[int, ...]] = {
    ("imac", "m"): (32, 64),
    ("gc", "msu"): (64,),
}


class RiscvCpu(Component):
    """What socpuppet's RISC-V CPUs have alike, `DbtRiseCpu` and `QboxCpu`.

    The same ports, the same node in a devicetree, the same interrupt
    numbers and the same checks on an image. `xlen` is the width of its
    registers in bits (XLEN is the RISC-V specification's name for it),
    and `reset_vector` is the address of the first instruction. `isa` and
    `modes` are which instruction sets and privilege modes its core has,
    by RISC-V's letters for them.

    With a `gdb_port`, the CPU listens for a debugger on that TCP port, and
    waits for one to attach before it executes anything. Each CPU of a
    simulation can have one, on a port of its own. ⚠️ A CPU stopped in its
    debugger stops the whole simulation, the other CPUs with it.
    """

    port_specs = _HART_PORTS
    is_bus_master = True

    xlen: int
    reset_vector: int
    gdb_port: int = 0
    # Each kind of CPU says which it has.
    isa: str = dataclasses.field(metadata={"parameter": False})
    modes: str = dataclasses.field(metadata={"parameter": False})

    @override
    def cpu_node(
        self, label: str, connected: Collection[str]
    ) -> tuple[str, ...]:
        # Every RISC-V CPU has an interrupt controller inside it: the
        # handful of interrupt inputs the core itself has. Devices refer to
        # it, not to the CPU, which is why it has a label of its own.
        #
        # A devicetree lists the extensions one by one, and G is short for
        # IMAFD with the two Z extensions, which every core here has.
        # Smcsrind is one more, which a CPU has when it has an IMSIC to
        # reach: the window onto registers another block keeps (`miselect`
        # and `mireg`). ⚠️ The extension's name promises more than the CPU
        # has: five more such windows. It is here because it is what
        # Zephyr's IMSIC driver looks for. Ssaia is the same for a CPU
        # with supervisor mode: that mode's window, the register it claims
        # through (`siselect`, `sireg` and `stopei`) and `stopi`, which
        # says which of its interrupts comes first. It is what Linux's
        # IMSIC driver looks for. ⚠️ Its name promises more too: the
        # priorities software may give interrupts. Smaia, the same for
        # machine mode, is left out: OpenSBI, the one program that wants it,
        # finds it by reading `mtopi` and not from the devicetree.
        reaches_an_imsic = "csr" in connected
        # A CPU with supervisor mode translates addresses, and this one's
        # MMU walks Sv39 page tables and no other kind.
        pages = ('\tmmu-type = "riscv,sv39";',) if "s" in self.modes else ()
        extensions = ", ".join(
            f'"{each}"'
            for each in (
                *self.isa.replace("g", "imafd"),
                "zicsr",
                "zifencei",
                *(("smcsrind",) if reaches_an_imsic else ()),
                *(("ssaia",) if reaches_an_imsic and "s" in self.modes else ()),
            )
        )
        return (
            f"{label}: cpu@0 {{",
            '\tdevice_type = "cpu";',
            '\tcompatible = "riscv";',
            "\treg = <0>;",
            f'\triscv,isa-base = "rv{self.xlen}i";',
            f"\triscv,isa-extensions = {extensions};",
            *pages,
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
        # machine external interrupt and 9 the supervisor's.
        return {"timer_irq": 7, "irq": 11, "supervisor_irq": 9}.get(port)

    @override
    def interrupt_input(
        self, port: str, label: str, *, dialect: Dialect
    ) -> str | None:
        number = self.interrupt_number(port)
        return None if number is None else f"&{label}_intc {number}"

    @override
    def refuse_image(
        self,
        *,
        image: str,
        xlen: int,
        entry: int,
        path: str,
        what_is_at: Callable[[int], Component | None],
    ) -> None:
        if xlen != self.xlen:
            raise ValueError(
                f"{image} is a {xlen}-bit image, and {path} is a "
                f"{self.xlen}-bit CPU. Build the firmware for a "
                f"{self.xlen}-bit core, or describe the CPU with xlen={xlen}."
            )
        if entry == self.reset_vector:
            return
        if isinstance(what_is_at(self.reset_vector), Rom):
            raise ValueError(
                f"{image} starts at {entry:#x}, and {path} starts executing "
                f"in a boot ROM, at {self.reset_vector:#x}. What `load_elf` "
                "gives this CPU is the ROM's own program (firmware/rom). An "
                "image for the ROM to boot goes in the flash, where the "
                "CPU's system controller says to look: "
                "`platform.poke(<its boot_address>, "
                f'socpuppet.boot_image.wrap("{image}"), '
                "via=<the CPU's socket>)`. Or have the CPU start in RAM, "
                "where `load_elf` puts an image, as a socpuppet board "
                "described with no `boot` does."
            )
        raise ValueError(
            f"{image} starts at {entry:#x}, and {path} starts executing "
            f"at its reset vector, {self.reset_vector:#x}. Link the "
            "firmware to start there, or describe the CPU with "
            f"reset_vector={entry:#x}."
        )


class DbtRiseCpu(RiscvCpu):
    """A RISC-V CPU that runs real firmware.

    The model is DBT-RISE-RISCV (Minres), an instruction-set simulator: it
    executes the firmware's instructions one after another, the way the
    processor would. `xlen` is the width of its registers in bits, 32 or
    64 (XLEN is the RISC-V specification's name for it), and `reset_vector`
    is the address of the first instruction.

    Its GDB server is DBT-RISE's own, and listens from the moment the
    platform is built.

    As it comes it is an RV32IMAC or RV64IMAC core in machine mode only: no
    floating point, and no supervisor or user mode. Build firmware for it
    with `-march=rv32imac_zicsr_zifencei` or `-march=rv64imac_zicsr_zifencei`.

    `isa` is which instruction sets it has, by RISC-V's letters for them:
    the part of `RV64IMAC` after the number. `modes` is which privilege
    modes. `isa="gc", modes="msu"` is RV64GC, with single and double
    precision floating point, and with supervisor and user mode below
    machine mode. That pair, at 64 bits only, and the default pair,
    `isa="imac", modes="m"`, at either width, are the cores there are. Any
    other combination is refused. Firmware built for RV64IMAC runs on the
    RV64GC core unchanged. ⚠️ Unless it uses physical memory protection
    (PMP), which the default core has and the RV64GC one has not.
    """

    implementation = "dbt_rise_cpu"

    isa: Literal["imac", "gc"] = not_a_parameter(default="imac")
    modes: Literal["m", "msu"] = not_a_parameter(default="m")

    def __post_init__(self) -> None:
        if self.xlen not in _CORES.get((self.isa, self.modes), ()):
            raise ValueError(
                f'There is no CPU with xlen={self.xlen}, isa="{self.isa}", '
                f'modes="{self.modes}". The ones there are: '
                + ", and ".join(
                    f'isa="{isa}", modes="{modes}" with xlen='
                    + " or ".join(str(xlen) for xlen in xlens)
                    for (isa, modes), xlens in _CORES.items()
                )
                + "."
            )

    @property
    @override
    def parameters(self) -> dict[str, int]:
        # The simulator takes numbers, so the two strings go as two flags.
        return {
            **super().parameters,
            "floating_point": int(self.isa == "gc"),
            "supervisor_mode": int(self.modes == "msu"),
        }


class QboxCpu(RiscvCpu):
    """A RISC-V CPU that is QEMU's: QBox, Qualcomm's QEMU inside SystemC.

    QEMU translates the firmware's instructions into the host's as it
    meets them, where `DbtRiseCpu` interprets them, so it is many times
    faster, and it is a second hart written by other people: firmware that
    works on one and not the other says which to look at. Only a build of
    socpuppet with QBox has it (tools/build_qbox.py), because QEMU is
    GPL-2.0 and is never in the wheel.

    It is RV64GC with supervisor and user mode, the core `DbtRiseCpu` has
    as `isa="gc", modes="msu"`, and has the same ports. It counts
    128 ns for each instruction, where `DbtRiseCpu` counts 100.
    docs/models/qbox-cpu.md says what else it does differently.

    Its GDB server is QEMU's own, and ⚠️ its port opens when the run starts
    and the CPU is held, not as the platform is built: start the run, then
    attach.
    """

    implementation = "qbox_cpu"

    isa: Literal["gc"] = not_a_parameter(default="gc")
    modes: Literal["msu"] = not_a_parameter(default="msu")

    def __post_init__(self) -> None:
        if self.xlen != 64:
            raise ValueError(
                f"A QboxCpu is a 64-bit CPU, and xlen={self.xlen} was asked "
                "for. A CPU of another width is a DbtRiseCpu."
            )
        if (self.isa, self.modes) != ("gc", "msu"):
            raise ValueError(
                "A QboxCpu is RV64GC with supervisor and user mode: "
                'isa="gc", modes="msu", and '
                f'isa="{self.isa}", modes="{self.modes}" was asked for.'
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
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
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
    #: What the controller's register map says it takes.
    mapped_size = flash_controller.SIZE

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
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

    @override
    def place(self, platform: Platform, path: str) -> PlacedNand:
        return PlacedNand(platform, path, self)


class Imsic(Component):
    """A RISC-V IMSIC: the interrupt controller a CPU is sent messages at.

    🎓 An IMSIC (incoming message-signalled interrupt controller) is half
    of RISC-V's Advanced Interrupt Architecture. A device interrupts by
    writing a number, an interrupt identity, to an address, and no wire
    runs from the device to the CPU. A PCIe device's interrupt is such a
    message already.

    It keeps a file of pending identities for machine mode and another for
    supervisor mode, each with a page of 4 KiB for its messages: map
    `machine` and `supervisor` onto the CPU's bus, where the devices that
    send can reach them. Connect `irq` to the CPU's `irq` and
    `supervisor_irq` to its `supervisor_irq`. The files' registers are not
    on the bus at all. Firmware reaches them through the CPU, and a file
    cannot interrupt until firmware has switched it on there, so connect
    the CPU's `csr` to `csr`.

    `identities` is the highest identity each file has: 63, or 127, and so
    on up to 2047. The first is 1.
    """

    implementation = "imsic"
    port_specs = (
        target("machine"),
        target("supervisor", required=False),
        target("csr"),
        wire_out("irq"),
        wire_out("supervisor_irq", required=False),
    )
    #: Each file's page.
    mapped_size = 0x1000

    identities: int = 63

    def __post_init__(self) -> None:
        # A file's registers hold 64 identities each and identity 0 is
        # none, so a file ends one short of a whole register.
        if self.identities % 64 != 63 or self.identities > 2047:
            raise ValueError(
                f"An IMSIC's highest identity is 63, 127 and so on up to "
                f"2047, one short of a multiple of 64, and "
                f"{self.identities} was given."
            )

    @override
    def device_nodes(
        self, reached: Mapping[str, Reached], *, dialect: Dialect, label: str
    ) -> tuple[DeviceNode, ...]:
        if dialect == "zephyr":
            # Zephyr's binding has one node, for the page of the mode Zephyr
            # runs in, machine mode, and that mode's line.
            if "machine" not in reached:
                return ()
            return (
                DeviceNode(
                    "interrupt-controller",
                    ((reached["machine"].address, self.mapped_size),),
                    (
                        'compatible = "riscv,imsic";',
                        "#address-cells = <0>;",
                        # An interrupt is named by one number: its identity.
                        "#interrupt-cells = <1>;",
                        "interrupt-controller;",
                        "msi-controller;",
                        f"riscv,num-ids = <{self.identities}>;",
                        # The one hart a socpuppet CPU is.
                        "riscv,hart-id = <0>;",
                    ),
                    interrupts=("irq",),
                ),
            )
        # 🎓 Linux's binding has a node for each mode's page, and says which
        # mode's by which of the CPU's interrupts it names, 11 for machine
        # mode's line and 9 for the supervisor's: there is no other word for
        # it. A hart is found the same way, so there is no hart's number.
        # OpenSBI keeps machine mode's for itself and marks its node
        # disabled before it hands the tree on.
        return tuple(
            DeviceNode(
                "interrupt-controller",
                ((reached[page].address, self.mapped_size),),
                (
                    'compatible = "riscv,imsics";',
                    "#address-cells = <0>;",
                    # A message is not named by any number on a wire.
                    "#interrupt-cells = <0>;",
                    "interrupt-controller;",
                    "msi-controller;",
                    "#msi-cells = <0>;",
                    f"riscv,num-ids = <{self.identities}>;",
                ),
                interrupts=(line,),
                suffix=suffix,
            )
            for page, line, suffix in (
                ("machine", "irq", "_m"),
                ("supervisor", "supervisor_irq", "_s"),
            )
            if page in reached
        )

    @override
    def takes_messages(self, port: str, *, dialect: Dialect) -> bool:
        # Machine mode's page for Zephyr, which runs in machine mode, and
        # the supervisor's for Linux, which runs in supervisor mode.
        return port == ("machine" if dialect == "zephyr" else "supervisor")


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


class Memory(Component):
    """A flat RAM of `size` bytes."""

    implementation = "memory"
    port_specs = (target("socket"),)

    size: int

    def __post_init__(self) -> None:
        self.mapped_size = self.size

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
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


class Rom(Component):
    """A read-only memory of `size` bytes: what a CPU boots from.

    A CPU starts at a fixed address, its reset vector, and on a real chip
    that address is in a ROM, written when the chip is made, whose program
    finds the firmware and starts it. Map `socket` at the reset vector and
    load the ROM's own program with `platform.load_elf`, before the first
    run. A write from the bus always fails. ⚠️ `poke` and `load_elf` work
    only until the bus master's first access. After it they are refused,
    as a debugger cannot patch a ROM on a board.

    It has no devicetree node. Firmware is not told of the ROM that
    started it.
    """

    implementation = "rom"
    port_specs = (target("socket"),)

    size: int

    def __post_init__(self) -> None:
        self.mapped_size = self.size

    @override
    def why_a_poke_was_refused(self, path: str) -> str:
        return (
            f'"{path}" is a ROM, and its bus master has already come to '
            "it. A ROM is loaded before the first run and not after: a "
            "debugger cannot patch one on a board either."
        )


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
    #: The controller's clock: 50 MHz.
    CLOCK_HZ = 50_000_000
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


class VirtioRng(Component):
    """🎭 A virtio entropy device: random bytes for a kernel's pool.

    🎓 **Virtio** is the family of devices a virtual machine offers its
    guest when it does not pretend to be real hardware, each a small
    register block (`virtio-mmio`) and rings of descriptors in the guest's
    memory, with drivers in every Linux. No real SoC has one; this is a
    stand-in, holding a place so that firmware can rehearse. The entropy
    device is the smallest of the family: the driver hands it empty
    buffers and it fills them with random bytes.

    `seed` is what the bytes come from, so that a run can be repeated: the
    same seed gives the same bytes. `cpu` is the register block, `dma` is
    how the device reaches the driver's memory, and `irq` is its interrupt
    line, high while a used buffer waits to be acknowledged.
    """

    implementation = "virtio_rng"
    port_specs = (
        target("cpu"),
        initiator("dma"),
        # A driver may poll the used ring and leave the line alone.
        wire_out("irq", required=False),
    )
    #: The transport's registers and the device's configuration after them.
    mapped_size = virtio_mmio.SIZE

    seed: int = 1

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return virtio_node(
            reached["cpu"].address,
            dialect,
            child=VirtioChild("entropy", "virtio,device4"),
            chosen=("zephyr,entropy",),
        )


class VirtioBlk(Component):
    """🎭 A virtio block device: a disk of 512-byte sectors.

    The driver reads and writes it by request: a header with the request's
    kind and first sector, the data, and a status byte the device writes
    last. It is the disk QEMU's `virt` machine gives a guest, and a stock
    Linux kernel mounts its root on one with no module and no initramfs.
    What it leaves out: more than one queue, discard, write-zeroes and the
    optional sizes and geometry. The disk is RAM, so a flush has nothing to
    do.

    `blocks` is how many sectors the disk has. Python puts an image on it
    with the placed disk's `load` and reads it back with `contents`. `cpu`
    is the register block, `dma` is how the device reaches the driver's
    memory, and `irq` is its interrupt line, high while a used buffer
    waits to be acknowledged.
    """

    implementation = "virtio_blk"
    port_specs = (
        target("cpu"),
        initiator("dma"),
        # A driver may poll the used ring and leave the line alone, as
        # EDK2's does.
        wire_out("irq", required=False),
    )
    #: The transport's registers and the device's configuration after them.
    mapped_size = virtio_mmio.SIZE

    blocks: int

    @override
    def place(self, platform: Platform, path: str) -> PlacedBlock:
        return PlacedBlock(platform, path, self)

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        # Zephyr has no driver for a virtio disk, so nothing to bind.
        return virtio_node(reached["cpu"].address, dialect)


class VirtioConsole(Component):
    """🎭 A virtio console: a serial port with no baud rate.

    The driver hands it bytes to put out, and buffers for what comes in.
    What the firmware puts out is kept, and the placed console's `output`
    reads it; what it is to receive is typed with the placed console's
    `write`, as at the UART (`Ns16550`). One port, and none of the
    device's features (no size, no multiport, no emergency write).

    `cpu` is the register block, `dma` is how the device reaches the
    driver's memory, and `irq` is its interrupt line, high while a used
    buffer waits to be acknowledged.
    """

    implementation = "virtio_console"
    port_specs = (
        target("cpu"),
        initiator("dma"),
        # A driver may poll the used ring and leave the line alone.
        wire_out("irq", required=False),
    )
    #: The transport's registers and the device's configuration after them.
    mapped_size = virtio_mmio.SIZE

    @override
    def place(self, platform: Platform, path: str) -> PlacedConsole:
        return PlacedConsole(platform, path, self)

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        # Not chosen as the console: a shield that builds firmware to
        # speak through it says so, and the 16550 stays the console
        # otherwise.
        return virtio_node(
            reached["cpu"].address,
            dialect,
            child=VirtioChild("console", "virtio,console"),
        )


class Virtio9p(Component):
    """🎭 A virtio 9P transport: a directory of this machine, shared.

    The driver mounts the share by its `tag` and talks to it in 9P2000.L,
    the dialect of Plan 9's file protocol that Linux's 9p client speaks;
    Python serves it out of `directory` (`socpuppet.ninep.Directory`), as
    QEMU serves its `virtio-9p-device`. It is the shared directory Linux
    mounts with `mount -t 9p -o trans=virtio`, where `VirtioFs` is the one
    Zephyr mounts. With no `directory` nothing serves the share, and every
    message comes back empty.

    ⚠️ Firmware may change anything under `directory`. `cpu` is the
    register block, `dma` is how the device reaches the driver's memory,
    and `irq` is its interrupt line, high while a used buffer waits to be
    acknowledged.
    """

    implementation = "virtio_9p"
    port_specs = (
        target("cpu"),
        initiator("dma"),
        wire_out("irq", required=False),
    )
    #: The transport's registers and the device's configuration after them.
    mapped_size = virtio_mmio.SIZE
    #: How long a tag may be, in bytes: what the configuration holds after
    #: the tag's two-byte length.
    TAG_BYTES = virtio_mmio.SIZE - virtio_mmio.CONFIG - 2

    tag: str = not_a_parameter("socpuppet")
    directory: str | os.PathLike[str] | None = not_a_parameter(None)

    def __post_init__(self) -> None:
        if len(self.tag.encode()) > self.TAG_BYTES:
            raise ValueError(
                f"A virtio 9P transport's tag is at most {self.TAG_BYTES} "
                f"bytes, and {self.tag!r} is {len(self.tag.encode())}."
            )

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        if self.directory is not None:
            native.virtio_9p_serve(
                path, self.tag, ninep.Directory(self.directory)
            )

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        # Zephyr has no 9P client, and Linux's finds the share by its tag.
        return virtio_node(reached["cpu"].address, dialect)


class VirtioFs(Component):
    """🎭 A virtio file system device: a directory of this machine, shared.

    The driver mounts the share by its `tag` and talks to it in FUSE,
    Linux's protocol for a file system served by a program; Python serves
    it out of `directory` (`socpuppet.fuse.Directory`), as QEMU's
    `virtiofsd` serves a `vhost-user-fs-device`. One request queue, no
    notification queue and no DAX window. With no `directory` nothing
    serves the share, and every request comes back empty.

    ⚠️ Firmware may change anything under `directory`. `cpu` is the
    register block, `dma` is how the device reaches the driver's memory,
    and `irq` is its interrupt line, high while a used buffer waits to be
    acknowledged.
    """

    implementation = "virtio_fs"
    port_specs = (
        target("cpu"),
        initiator("dma"),
        # A driver may poll the used rings and leave the line alone, as
        # EDK2's does.
        wire_out("irq", required=False),
    )
    #: The transport's registers and the device's configuration after them.
    mapped_size = virtio_mmio.SIZE
    #: How long a tag may be, in bytes: the configuration's field.
    TAG_BYTES = 36

    tag: str = not_a_parameter("socpuppet")
    directory: str | os.PathLike[str] | None = not_a_parameter(None)

    def __post_init__(self) -> None:
        if len(self.tag.encode()) > self.TAG_BYTES:
            raise ValueError(
                f"A virtio file system's tag is at most {self.TAG_BYTES} "
                f"bytes, and {self.tag!r} is {len(self.tag.encode())}."
            )

    @override
    def configure(self, native: _core.Platform, path: str) -> None:
        if self.directory is not None:
            native.virtio_fs_serve(
                path, self.tag, fuse.Directory(self.directory)
            )

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        # Zephyr's client mounts the transport's device itself, which a
        # program finds by the alias; Linux's finds the share by its tag.
        return virtio_node(
            reached["cpu"].address, dialect, aliases=("virtiofs0",)
        )


class VirtioNet(Component):
    """🎭 A virtio network device: an Ethernet port with Python on the wire.

    The driver hands it frames to send, and empty buffers for the frames
    that come in, each with a 12-byte header in front for offloads this
    device offers none of. It is QEMU's `virtio-net-device`, with one pair
    of queues and its MAC address in its configuration, and none of the
    checksum or segmentation offloads, merged buffers, control queue or
    link status a driver can do without.

    `mac` is its address, as a 48-bit number with the first byte highest:
    the default, `0x0200_5E00_5301`, is `02:00:5e:00:53:01`, locally
    administered so that it is no manufacturer's. Python reads the frames
    the firmware sent with the placed device's `received`, and sends it
    frames with `send`. `cpu` is the register block, `dma` is how the
    device reaches the driver's memory, and `irq` is its interrupt line,
    high while a used buffer waits to be acknowledged.
    """

    implementation = "virtio_net"
    port_specs = (
        target("cpu"),
        initiator("dma"),
        # A driver may poll the used rings and leave the line alone, as
        # EDK2's does.
        wire_out("irq", required=False),
    )
    #: The transport's registers and the device's configuration after them.
    mapped_size = virtio_mmio.SIZE

    mac: int = 0x0200_5E00_5301

    def __post_init__(self) -> None:
        if not 0 <= self.mac < 1 << 48:
            raise ValueError(
                f"A MAC address is 48 bits, six bytes, and {self.mac:#x} "
                "does not fit in them."
            )

    @override
    def place(self, platform: Platform, path: str) -> PlacedNet:
        return PlacedNet(platform, path, self)

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        # Zephyr's driver takes the address from its node, and Linux's and
        # EDK2's from the device.
        address = " ".join(f"{byte:02x}" for byte in self.mac.to_bytes(6))
        return virtio_node(
            reached["cpu"].address,
            dialect,
            child=VirtioChild(
                "net",
                "virtio,net",
                (f"local-mac-address = [{address}];",),
            ),
        )


class VirtioChild(NamedTuple):
    """What Zephyr's driver for a kind of virtio device binds to.

    It is a child of the transport's node, in Zephyr's dialect only:
    `virtio-<kind>`, with `binding` as its `compatible` and any
    `properties` the driver reads from it.
    """

    kind: str
    binding: str
    properties: tuple[str, ...] = ()


def virtio_node(
    address: int,
    dialect: Dialect,
    *,
    child: VirtioChild | None = None,
    chosen: tuple[str, ...] = (),
    aliases: tuple[str, ...] = (),
) -> DeviceNode:
    """The node of a virtio device behind the virtio-mmio transport.

    In Linux's dialect it is the transport's node alone, and the device
    says what it is in a register (`virtio,mmio`: `compatible`, `reg` and
    `interrupts`). Zephyr's drivers bind to a child of that node, and only
    in that dialect: `child`, labelled as the transport's device. `chosen`
    is what the child can be chosen for. With no `child`, for a kind
    Zephyr has no driver for, the node is the transport's alone in both
    dialects. `aliases` are the transport node's own.
    """
    children = (
        (
            DeviceNode(
                f"virtio-{child.kind}",
                (),
                (f'compatible = "{child.binding}";', *child.properties),
                chosen=chosen,
                # The transport's interrupt is the node's, not the child's.
                interrupts=(),
                suffix="_device",
            ),
        )
        if dialect == "zephyr" and child is not None
        else ()
    )
    return DeviceNode(
        # QEMU's and Zephyr's spelling.
        "virtio_mmio",
        ((address, virtio_mmio.SIZE),),
        ('compatible = "virtio,mmio";',),
        # Zephyr's transport driver is one that asks.
        short_interrupts=True,
        aliases=aliases,
        children=children,
    )


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
    #: The CPU's register block, which is as big as its register map says.
    CPU_SIZE: ClassVar[int] = nvme_frontend.SIZE

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
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
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
    #: blocks it points at: as much as its register map says.
    REGISTERS_SIZE: ClassVar[int] = ucie_link.SIZE
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
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
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


class PcieFunctionFront(Component):
    """What stands in front of a PCIe function, as the host sees it.

    `PcieEndpoint` and `PciemHost` both put a function, such as
    `BehavioralNvme`, before a host, and say the same of it.
    `vendor_id` and `device_id` say who made the device and which device it
    is, and `class_code` what kind of device it is, as three bytes: class,
    subclass and programming interface (0x010802 for an NVMe drive).
    `function_size` is how many bytes the function's register block takes,
    and `vectors` how many interrupt lines it has.
    """

    vendor_id: int
    device_id: int
    class_code: int
    function_size: int
    vectors: int

    def __post_init__(self) -> None:
        if not 1 <= self.vectors <= 2048:
            raise ValueError(
                f"A PCIe function has 1 to 2048 interrupt vectors, which is "
                f"what an MSI-X table can hold, and {self.vectors} were "
                "asked for."
            )


class PcieEndpoint(PcieFunctionFront):
    """What stands between a PCIe link and a function that knows no PCIe.

    The function, such as `BehavioralNvme`, has a register block, a DMA
    port and interrupt lines. The endpoint puts PCIe around them: it says
    what the device is, lets the host place the register block in its
    address map, and passes the function's DMA up the link. Its parameters
    are `PcieFunctionFront`'s.
    """

    implementation = "pcie_endpoint"

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


class PciemHost(PcieFunctionFront):
    """🐧 This machine's own Linux, as the host of a PCIe function.

    It stands where a `PcieEndpoint`, its link and a root complex would,
    and hands the function to this machine through pciem, a Linux kernel
    module that lets a program be a PCIe device: the host's driver finds
    the function on its own bus and uses it as it would a card in a slot.
    The host's register writes reach the function out of `bar0`, the
    function's DMA comes in on `dma` and goes on to the host's memory, and
    a rising `irq` line sends the host that vector.

    Its parameters are `PcieFunctionFront`'s, as a `PcieEndpoint`'s are.
    Only a build of socpuppet with pciem has it (tools/build_pciem.py),
    because pciem is GPL-2.0-only and is never in the wheel, and it runs
    only on a machine whose Linux has pciem loaded (docs/setup.md).
    """

    implementation = "pciem_host"

    @override
    def place(self, platform: Platform, path: str) -> PlacedPciemHost:
        return PlacedPciemHost(platform, path, self)

    @property
    def port_specs(self) -> tuple[PortSpec, ...]:
        """The function's three kinds of port, one line per vector."""
        return (
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
    #: The requester ID of the one device the link has room for: bus 0,
    #: device 0, function 0. It is the device's ID at an IOMMU too.
    REQUESTER_ID = 0
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
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode | None:
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
                # Zephyr's own ECAM driver delivers messages through an
                # interrupt controller of ARM's only, so it has a driver of
                # ours. Linux's generic one is all this root complex needs.
                'compatible = "socpuppet,pcie";'
                if dialect == "zephyr"
                else 'compatible = "pci-host-ecam-generic";',
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
            # A PCIe device's interrupt is a message, which comes out of
            # `dma` with the device's other writes.
            messages="dma",
            accesses="dma",
        )

    @override
    def iommu_properties(
        self, iommu: str, *, dialect: Dialect
    ) -> tuple[str, ...]:
        # A device behind the root complex is known to the IOMMU by its
        # requester ID, its bus, device and function numbers. Linux maps a
        # range of requester IDs to the IOMMU's device IDs: all 65536 of
        # them, to the same numbers. socpuppet's binding for Zephyr names
        # each ID the IOMMU will see in a list, and there is one device.
        if dialect == "linux":
            return (f"iommu-map = <0x0 &{iommu} 0x0 0x10000>;",)
        return (f"iommus = <&{iommu} {self.REQUESTER_ID:#x}>;",)


class Iommu(Component):
    """A RISC-V IOMMU: it confines each device to the memory it was given.

    🎓 An IOMMU (input-output memory management unit) is to a device what
    the MMU is to a program. Every address a device uses goes through page
    tables the operating system owns, and an access that is not mapped is
    refused and reported. This one follows the RISC-V IOMMU specification:
    a device context says which page tables a device's addresses go
    through, found in a device directory by the device's ID, and two rings
    in memory carry commands in and fault records out.

    Put it between a device and memory: what the device sends comes in at
    `target`, and what was translated goes out at `initiator`, with the
    IOMMU's own reads of its tables and writes of its records. A device's
    ID is its PCIe requester ID, which a PCIe endpoint marks its accesses
    with. Firmware reaches its registers at `socket`. `irq` is its
    interrupt, a line for an interrupt controller's source.

    It has what drivers use: a directory of one to three levels, one stage
    of translation through Sv39 page tables, the two queues and a wired
    interrupt. The model is socpuppet's own, written for VPV-Peripherals.
    """

    implementation = "iommu"
    port_specs = (
        target("socket"),
        target("target"),
        initiator("initiator"),
        wire_out("irq", required=False),
    )
    #: Its registers, a page.
    mapped_size = 0x1000

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return DeviceNode(
            "iommu",
            ((reached["socket"].address, self.mapped_size),),
            (
                'compatible = "riscv,iommu";',
                # A device is named to it by one number, its device ID.
                "#iommu-cells = <1>;",
            ),
            # Zephyr's Kconfig sees the short form only.
            short_interrupts=True,
        )

    @override
    def translates(self, port: str) -> bool:
        return port == "target"

    @override
    def routes(self, port: str) -> Iterable[tuple[str, int, int | None]]:
        # What comes in is translated, and goes out at an address only the
        # device's page tables say. A walk of the address map, which is how
        # the devicetree finds where a device's interrupt messages go,
        # takes that address to be the same: ⚠️ firmware that puts a
        # device's messages through page tables has to map the page they
        # go to at its own address.
        return (("initiator", 0, None),) if port == "target" else ()


class Aplic(Component):
    """A RISC-V APLIC: it turns devices' interrupt lines into messages.

    🎓 The APLIC (advanced platform-level interrupt controller) is the
    other half of RISC-V's Advanced Interrupt Architecture, beside the
    `Imsic`. A device that only has a wire connects it here, to one of
    `source1` to `source31`. When the line asks, the APLIC writes an
    interrupt identity to the page of the CPU's IMSIC, as a device that
    interrupts with messages would have done itself. So it can sit with
    its devices, on another die than the CPU, with nothing but a bus
    between them.

    Connect `msi` to a bus that the IMSIC's pages are on, or to
    something that leads to them. Firmware says which page and which
    identity each source sends. This APLIC only delivers by message: it
    has no line to a CPU. The model is borrowed from VPV-Peripherals, with
    delivery by message added.

    `messages_to` is where its messages go until firmware says otherwise:
    the address of an IMSIC's page. Zero, the default, is nowhere, for
    firmware that says, as Zephyr's driver does when it reads zero there.
    OpenSBI and Linux say nothing for an APLIC that serves supervisor mode
    alone, and leave it to whoever built the platform.
    """

    implementation = "aplic"
    #: The APLIC numbers its sources from 1. 0 means "no interrupt".
    SOURCES = 31
    port_specs = (
        target("socket"),
        initiator("msi"),
        *(wire_in(f"source{number}") for number in range(1, SOURCES + 1)),
    )
    #: The APLIC's registers, as far as the lines to harts it does not have.
    mapped_size = 0x8000

    messages_to: int = 0

    def __post_init__(self) -> None:
        # The registers that say where messages go hold a page's number,
        # and an IMSIC's page is 4 KiB.
        if self.messages_to % 0x1000 != 0:
            raise ValueError(
                f"An APLIC sends its messages to the start of an IMSIC's "
                f"page, which is a multiple of 4 KiB, and "
                f"{self.messages_to:#x} is not one."
            )

    @override
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
        return DeviceNode(
            "interrupt-controller",
            ((reached["socket"].address, self.mapped_size),),
            (
                'compatible = "riscv,aplic";',
                "#address-cells = <0>;",
                # An interrupt is named by its source and how its line
                # asks, and in Zephyr's binding by a priority between them.
                "#interrupt-cells = <3>;"
                if dialect == "zephyr"
                else "#interrupt-cells = <2>;",
                "interrupt-controller;",
                f"riscv,num-sources = <{self.SOURCES}>;",
            ),
            messages="msi",
        )

    @override
    def interrupt_number(self, port: str) -> int | None:
        if not port.startswith("source"):
            return None
        return int(port.removeprefix("source"))

    @override
    def interrupt_input(
        self, port: str, label: str, *, dialect: Dialect
    ) -> str | None:
        number = self.interrupt_number(port)
        if number is None:
            return None
        # The source's number, then for Zephyr a priority, which only counts
        # when an APLIC interrupts over a line, and 4, the devicetree's
        # number for a line that asks while it is high, as every line in
        # socpuppet does.
        priority = " 1" if dialect == "zephyr" else ""
        return f"&{label} {number}{priority} 4"


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
    def device_node(
        self, reached: Mapping[str, Reached], *, dialect: Dialect
    ) -> DeviceNode:
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
    def interrupt_input(
        self, port: str, label: str, *, dialect: Dialect
    ) -> str | None:
        number = self.interrupt_number(port)
        # The source's number, and the priority the firmware gives it unless
        # it chooses another: 1, the lowest that can interrupt. ⚠️ That is
        # Zephyr's binding in both dialects. Linux's has the source alone,
        # and nothing that reads Linux's has a PLIC here yet.
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

    script: Script | None = not_a_parameter(None, kw_only=False)

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
