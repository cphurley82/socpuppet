"""PCIe: the root complex, an endpoint's front, pciem's host, and the IOMMU."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, override

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    PortSpec,
    cells,
    initiator,
    target,
    wire_in,
    wire_out,
)
from socpuppet.placed import PlacedPciemHost

if TYPE_CHECKING:
    from socpuppet.address_map import Reached
    from socpuppet.platform import Platform


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
