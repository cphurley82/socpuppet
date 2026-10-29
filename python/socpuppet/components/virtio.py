"""🎭 The virtio devices, and the devicetree node a slot of them gets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, NamedTuple, override

from socpuppet import fuse, ninep
from socpuppet.components.base import (
    Component,
    DeviceNode,
    Dialect,
    initiator,
    not_a_parameter,
    target,
    wire_out,
)
from socpuppet.placed import PlacedBlock, PlacedConsole, PlacedNet
from socpuppet.regs import virtio_mmio

if TYPE_CHECKING:
    from socpuppet import _core
    from socpuppet.address_map import Reached
    from socpuppet.platform import Platform


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
