"""The interrupt controllers, wired and by message."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, override

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    initiator,
    target,
    wire_in,
    wire_out,
)

if TYPE_CHECKING:
    from socpuppet.address_map import Reached


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
