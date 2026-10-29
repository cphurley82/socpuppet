"""What every component is: its ports, its parameters, its node."""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    NamedTuple,
    dataclass_transform,
)

from socpuppet.placed import Placed

if TYPE_CHECKING:
    from socpuppet import _core
    from socpuppet.address_map import Reached
    from socpuppet.ops import Operation
    from socpuppet.platform import Platform


#: Whose bindings a devicetree is written in. 🎓 A devicetree says what
#: hardware there is, and each operating system's drivers look for their
#: own names, numbers of cells and shapes of nodes: its bindings. Zephyr's
#: are what socpuppet's boards are built with, and Linux's are what OpenSBI
#: and Linux read, and EDK2 after them.
type Dialect = Literal["zephyr", "linux"]


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

    For what is for Python's side only: what a component is handed that is
    not a number, such as a script, or a number only its devicetree node
    uses, such as how many of a GPIO's pins a board brings out. It is given
    by keyword, as a parameter is, unless `kw_only` is false.
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
