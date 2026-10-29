"""The drive's parts: 🎭 the behavioral NVMe, and the SSD's own blocks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, ClassVar, override

from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    PortSpec,
    initiator,
    target,
    wire_out,
)
from socpuppet.placed import PlacedNand
from socpuppet.regs import dma_engine, flash_controller, nvme_frontend

if TYPE_CHECKING:
    from socpuppet.address_map import Reached
    from socpuppet.platform import Platform


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
