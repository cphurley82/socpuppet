"""🧵 A host's virtio driver, small enough to read in one sitting.

It stands in for the driver a kernel has for every virtio device, and it
does what that driver does, in the order it does it (virtio 1.2, section
3): find the device, agree on features, put a virtqueue in the host's
memory and tell the device where, say the driver is ready, and then hand
the device buffers by chaining descriptors, ringing the doorbell and
waiting for the interrupt.

It is written for a script, so every step that touches the bus is a
generator, and a script hands over to it with `yield from`:

    def script():
        rng = sp.VirtioRngHost(registers=0x1000_1000, memory=0x8000_0000)
        yield from rng.start()
        bytes_from_the_device = yield from rng.read(32)

`VirtioHost` is the part every kind of device shares; a class for a kind of
device, such as `VirtioRngHost`, is a thin layer over it that says what the
device is and knows what goes in its chains.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from typing import Any

from socpuppet import fuse, ninep
from socpuppet.errors import VirtioError
from socpuppet.ops import (
    Operation,
    Steps,
    read,
    read32,
    wait_irq,
    write,
    write32,
)
from socpuppet.regs import virtio_mmio as regs

#: The transport's own feature bit: the device speaks the modern layout.
VERSION_1 = 1 << 32

# A descriptor's flags (section 2.7.5): the chain goes on at `next`; the
# device writes this buffer.
_NEXT = 1
_WRITE = 2

# The rings' alignment (section 2.7): the descriptor table on 16 bytes, the
# available ring on 2, the used ring on 4. Each ring here starts on a page,
# which satisfies all three and keeps the arithmetic plain.
_PAGE = 4096
# One descriptor: the buffer's address, its length, its flags, and which
# descriptor comes next.
_DESCRIPTOR = struct.Struct("<QIHH")
# Both rings begin with 16-bit flags, then the 16-bit index, then the
# entries: a 16-bit head each in the available ring, and in the used ring
# an element of the chain's head and how many bytes the device wrote.
_RING_INDEX = 2
_RING_ENTRIES = 4
_AVAILABLE_ENTRY = struct.Struct("<H")
_USED_ELEMENT = struct.Struct("<II")


def _wait_for_the_wire() -> Steps[None]:
    """Waits for the master's interrupt line."""
    yield wait_irq()


class _Queue:
    """One virtqueue, as the driver keeps track of it."""

    def __init__(self, number: int, entries: int, rings: int) -> None:
        self.number = number
        self.entries = entries
        # Where the three rings are in the host's memory.
        self.descriptors = rings
        self.available = rings + _PAGE
        self.used = rings + 2 * _PAGE
        # The next descriptor to hand out, the next available slot to fill,
        # and how many used elements the driver has taken.
        self.next_descriptor = 0
        self.made_available = 0
        self.taken = 0
        # The writable buffers of each chain in flight, by its head.
        self.in_flight: dict[int, list[tuple[int, int]]] = {}


class VirtioHost:
    """🧵 Stand-in for a kernel's virtio driver, for any kind of device.

    `registers` is where the device's register block is in the host's
    address map. `memory` is the start of an area of the host's memory the
    driver may use: three pages for each queue's rings, then the buffers
    it hands the device. It has to start on a page boundary. `memory_size`
    is how many bytes the area has; given one, the driver says so when a
    buffer would not fit. `queue_entries` is how long the driver makes each
    queue, at most what the device allows.

    `interrupt` is how the driver waits for the device's interrupt: steps
    that return once it has come. Left out, the driver waits with
    `sp.wait_irq()`, which is right when the device's line is wired to the
    master that runs the script.
    """

    def __init__(
        self,
        *,
        registers: int,
        memory: int,
        memory_size: int | None = None,
        queue_entries: int = 16,
        interrupt: Callable[[], Steps[object]] | None = None,
    ) -> None:
        if memory % _PAGE:
            raise ValueError(
                f"The driver's memory has to start on a page boundary (a "
                f"multiple of {_PAGE}), because each ring is a page, and "
                f"{memory:#x} does not."
            )
        if queue_entries < 1 or queue_entries & (queue_entries - 1):
            raise ValueError(
                f"A virtqueue has a power of two entries, and {queue_entries} "
                "were asked for."
            )
        self._registers = registers
        self._queue_entries = queue_entries
        self._interrupt = interrupt or _wait_for_the_wire
        self._free_memory = memory
        self._memory_end = None if memory_size is None else memory + memory_size
        self._queues: dict[int, _Queue] = {}

    #: What a kind of device says it is (section 5), how many queues it
    #: has, and what to call it in a refusal: a class for a kind sets them.
    DEVICE_ID: int
    QUEUES: int
    KIND: str

    def start(self) -> Steps[None]:
        """Finds the device, agrees on no features, and sets its queues up."""
        device_id = yield from self.probe()
        if device_id != self.DEVICE_ID:
            raise VirtioError(
                f"The virtio device is a kind {device_id}, not {self.KIND} "
                f"(kind {self.DEVICE_ID})."
            )
        yield from self.reset()
        yield from self.negotiate(0)
        for number in range(self.QUEUES):
            yield from self.setup_queue(number)
        yield from self.driver_ok()

    def probe(self) -> Steps[int]:
        """Finds the device: checks it is a virtio device, and says which kind.

        Returns the device id (section 5: 1 a network card, 2 a block
        device, 3 a console, 4 an entropy source, and so on).
        """
        magic = yield from self._read(regs.MAGIC_VALUE)
        if magic != regs.MAGIC_VALUE_AT_RESET:
            raise VirtioError(
                f"There is no virtio device at {self._registers:#x}: its "
                f"magic value reads as {magic:#010x}, not "
                f"{regs.MAGIC_VALUE_AT_RESET:#010x} (the bytes of `virt`)."
            )
        version = yield from self._read(regs.VERSION)
        if version != regs.VERSION_AT_RESET:
            raise VirtioError(
                f"The virtio device at {self._registers:#x} speaks version "
                f"{version} of the register layout, and this driver speaks "
                f"version {regs.VERSION_AT_RESET} only."
            )
        return (yield from self._read(regs.DEVICE_ID))

    def reset(self) -> Steps[None]:
        """Resets the device: writing zero to its status (section 3.1.1)."""
        yield self._write(regs.STATUS, 0)
        self._queues.clear()

    def negotiate(self, wanted: int) -> Steps[int]:
        """Agrees on features: `wanted`, as far as the device offers them.

        Returns what was accepted, which always has the modern layout in
        it. Raises `VirtioError` if the device does not keep FEATURES_OK,
        which is how a device says it cannot live with the driver's choice.
        """
        yield self._write(
            regs.STATUS, regs.STATUS_ACKNOWLEDGE | regs.STATUS_DRIVER
        )
        offered = 0
        for half in (0, 1):
            yield self._write(regs.DEVICE_FEATURES_SEL, half)
            offered |= (yield from self._read(regs.DEVICE_FEATURES)) << (
                32 * half
            )
        accepted = (wanted & offered) | VERSION_1
        for half in (0, 1):
            yield self._write(regs.DRIVER_FEATURES_SEL, half)
            yield self._write(
                regs.DRIVER_FEATURES, (accepted >> (32 * half)) & 0xFFFF_FFFF
            )
        with_features = (
            regs.STATUS_ACKNOWLEDGE
            | regs.STATUS_DRIVER
            | regs.STATUS_FEATURES_OK
        )
        yield self._write(regs.STATUS, with_features)
        status = yield from self._read(regs.STATUS)
        if not status & regs.STATUS_FEATURES_OK:
            raise VirtioError(
                f"The virtio device at {self._registers:#x} did not keep "
                f"FEATURES_OK: it offered {offered:#x} and will not take "
                f"{accepted:#x}."
            )
        return accepted

    def setup_queue(self, number: int) -> Steps[None]:
        """Puts virtqueue `number` in the host's memory and tells the device.

        The queue gets this driver's `queue_entries`, or fewer if the
        device allows fewer. Raises `VirtioError` for a queue the device
        has not got.
        """
        yield self._write(regs.QUEUE_SEL, number)
        most = yield from self._read(regs.QUEUE_NUM_MAX)
        if most == 0:
            raise VirtioError(
                f"The virtio device at {self._registers:#x} has no queue "
                f"{number}."
            )
        entries = min(self._queue_entries, most)
        queue = _Queue(number, entries, self._allocate(3 * _PAGE, _PAGE))
        yield self._write(regs.QUEUE_NUM, entries)
        yield self._write(regs.QUEUE_DESC_LOW, queue.descriptors & 0xFFFF_FFFF)
        yield self._write(regs.QUEUE_DESC_HIGH, queue.descriptors >> 32)
        yield self._write(regs.QUEUE_DRIVER_LOW, queue.available & 0xFFFF_FFFF)
        yield self._write(regs.QUEUE_DRIVER_HIGH, queue.available >> 32)
        yield self._write(regs.QUEUE_DEVICE_LOW, queue.used & 0xFFFF_FFFF)
        yield self._write(regs.QUEUE_DEVICE_HIGH, queue.used >> 32)
        yield self._write(regs.QUEUE_READY, regs.QUEUE_READY_READY)
        self._queues[number] = queue

    def driver_ok(self) -> Steps[None]:
        """Tells the device the driver is ready and it may use its queues."""
        status = yield from self._read(regs.STATUS)
        yield self._write(regs.STATUS, status | regs.STATUS_DRIVER_OK)

    def submit(
        self, number: int, readable: list[bytes], writable: list[int]
    ) -> Steps[tuple[int, list[bytes]]]:
        """Hands the device one chain on queue `number` and waits for it back.

        `readable` are the buffers the device reads, with their contents,
        and `writable` the sizes of the buffers it writes, which come after
        them in the chain. Returns how many bytes the device wrote and the
        writable buffers, read back whole.
        """
        head = yield from self.post(number, readable, writable)
        written = yield from self.take(number, head)
        queue = self._queue(number)
        answers = []
        for address, size in queue.in_flight.pop(head):
            answers.append((yield read(address, size)))
        return written, answers

    def post(
        self, number: int, readable: list[bytes], writable: list[int]
    ) -> Steps[int]:
        """Hands the device one chain on queue `number` and rings the doorbell.

        Returns the chain's head, for `take`.
        """
        queue = self._queue(number)
        buffers: list[tuple[int, int, int, bytes | None]] = []
        for contents in readable:
            address = self._allocate(len(contents), 1)
            buffers.append((address, len(contents), 0, contents))
        for size in writable:
            buffers.append((self._allocate(size, 1), size, _WRITE, None))
        if not buffers:
            raise ValueError("A chain has at least one buffer.")
        head = queue.next_descriptor
        for index, (address, size, flags, data) in enumerate(buffers):
            descriptor = (queue.next_descriptor + 1) % queue.entries
            last = index == len(buffers) - 1
            yield write(
                queue.descriptors + _DESCRIPTOR.size * queue.next_descriptor,
                _DESCRIPTOR.pack(
                    address, size, flags | (0 if last else _NEXT), descriptor
                ),
            )
            if data is not None:
                yield write(address, data)
            queue.next_descriptor = descriptor
        queue.in_flight[head] = [
            (address, size)
            for address, size, flags, _ in buffers
            if flags & _WRITE
        ]
        slot = queue.made_available % queue.entries
        yield write(
            queue.available + _RING_ENTRIES + _AVAILABLE_ENTRY.size * slot,
            _AVAILABLE_ENTRY.pack(head),
        )
        queue.made_available += 1
        index = queue.made_available & 0xFFFF
        yield write(queue.available + _RING_INDEX, _AVAILABLE_ENTRY.pack(index))
        yield self._write(regs.QUEUE_NOTIFY, queue.number)
        return head

    def take(self, number: int, head: int) -> Steps[int]:
        """Waits until the device has given the chain `head` back.

        Returns how many bytes the device wrote to it.
        """
        queue = self._queue(number)
        while True:
            used_index = yield from self._used_index(queue)
            if used_index != queue.taken & 0xFFFF:
                break
            yield from self._interrupt()
            # Whatever the device raised is acknowledged, a configuration
            # change with the used buffer: no device here changes its
            # configuration, so there is nothing to do about one.
            status = yield from self._read(regs.INTERRUPT_STATUS)
            yield self._write(regs.INTERRUPT_ACK, status)
        slot = queue.taken % queue.entries
        element = yield read(
            queue.used + _RING_ENTRIES + _USED_ELEMENT.size * slot,
            _USED_ELEMENT.size,
        )
        queue.taken += 1
        used_head, written = (
            int(field) for field in _USED_ELEMENT.unpack(element)
        )
        if used_head != head:
            raise VirtioError(
                f"The virtio device at {self._registers:#x} gave back chain "
                f"{used_head} on queue {number} where the driver was waiting "
                f"for chain {head}: this driver takes chains back in the "
                "order it handed them over."
            )
        return written

    def _queue(self, number: int) -> _Queue:
        if number not in self._queues:
            raise VirtioError(
                f"Queue {number} has not been set up: call setup_queue first."
            )
        return self._queues[number]

    def _used_index(self, queue: _Queue) -> Steps[int]:
        index = yield read(queue.used + _RING_INDEX, _AVAILABLE_ENTRY.size)
        return int(_AVAILABLE_ENTRY.unpack(index)[0])

    def _allocate(self, size: int, alignment: int) -> int:
        """Takes `size` bytes of the driver's memory, aligned."""
        start = (self._free_memory + alignment - 1) // alignment * alignment
        if self._memory_end is not None and start + size > self._memory_end:
            raise VirtioError(
                f"The driver's memory is used up: {size} more bytes were "
                f"wanted and it ends at {self._memory_end:#x}."
            )
        self._free_memory = start + size
        return start

    def _read(self, offset: int) -> Steps[int]:
        value = yield read32(self._registers + offset)
        return int(value)

    def _write(self, offset: int, value: int) -> Operation:
        return write32(self._registers + offset, value)


class VirtioRngHost(VirtioHost):
    """🧵 Stand-in for the driver of a virtio entropy device.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    one queue up; `read` asks it for bytes.
    """

    DEVICE_ID = 4  # Section 5.4.
    QUEUES = 1
    KIND = "an entropy device"

    def read(self, count: int) -> Steps[bytes]:
        """Asks the device for `count` random bytes."""
        written, (answer,) = yield from self.submit(0, [], [count])
        return answer[:written]


class VirtioConsoleHost(VirtioHost):
    """🧵 Stand-in for the driver of a virtio console.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    two queues up; `send` puts bytes out, and `receive` waits for bytes to
    come in.
    """

    DEVICE_ID = 3  # Section 5.3.
    QUEUES = 2
    KIND = "a console"
    #: Its two queues: what comes in, and what goes out.
    RECEIVE_QUEUE = 0
    TRANSMIT_QUEUE = 1

    def send(self, data: bytes) -> Steps[None]:
        """Puts `data` out, and waits until the device has taken it."""
        yield from self.submit(self.TRANSMIT_QUEUE, [data], [])

    def receive(self, at_most: int) -> Steps[bytes]:
        """Waits for bytes to come in: up to `at_most` of them."""
        written, (answer,) = yield from self.submit(
            self.RECEIVE_QUEUE, [], [at_most]
        )
        return answer[:written]


# The request types and statuses of a virtio disk, section 5.2.6.
_BLK_IN = 0
_BLK_OUT = 1
#: Each failing status, and what it most likely means here.
_BLK_STATUSES = {
    1: (
        "IOERR",
        "the request runs past the end of the disk, or is not whole sectors",
    ),
    2: ("UNSUPP", "the disk does not do that kind of request"),
}
#: The header that starts every request: its type, a reserved word, and
#: the sector it starts at.
_BLK_HEADER = struct.Struct("<IIQ")


class VirtioBlkHost(VirtioHost):
    """🧵 Stand-in for the driver of a virtio disk.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    one queue up; `read_sectors` and `write_sectors` move whole 512-byte
    sectors. A request the device fails raises `VirtioError` with the
    status it gave.
    """

    DEVICE_ID = 2  # Section 5.2.
    QUEUES = 1
    KIND = "a block device"
    #: What a sector holds.
    SECTOR = 512

    def read_sectors(self, *, first: int, count: int) -> Steps[bytes]:
        """Reads `count` sectors from sector `first` on."""
        _, (data, status) = yield from self.submit(
            0, [_blk_header(_BLK_IN, first)], [count * self.SECTOR, 1]
        )
        _refuse_unless_ok(status, f"reading sector {first}")
        return data

    def write_sectors(self, *, first: int, data: bytes) -> Steps[None]:
        """Writes `data`, whole sectors of it, from sector `first` on."""
        _, (status,) = yield from self.submit(
            0, [_blk_header(_BLK_OUT, first), data], [1]
        )
        _refuse_unless_ok(status, f"writing sector {first}")


def _blk_header(kind: int, sector: int) -> bytes:
    return _BLK_HEADER.pack(kind, 0, sector)


def _refuse_unless_ok(status: bytes, doing: str) -> None:
    if status[0] != 0:
        name, why = _BLK_STATUSES.get(
            status[0],
            (f"status {status[0]}", "which the specification has no name for"),
        )
        raise VirtioError(f"The disk answered {name} on {doing}: {why}.")


class VirtioNetHost(VirtioHost):
    """🧵 Stand-in for the driver of a virtio network device.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    two queues up; `send_frame` sends an Ethernet frame, and
    `receive_frame` waits for one to come in.
    """

    DEVICE_ID = 1  # Section 5.1.
    QUEUES = 2
    KIND = "a network device"
    #: Its two queues: what comes in, and what goes out.
    RECEIVE_QUEUE = 0
    TRANSMIT_QUEUE = 1
    #: The header in front of every frame, both ways (section 5.1.6).
    HEADER = 12
    #: The most a frame that comes in may be: an Ethernet frame of the
    #: largest payload, 1500 bytes, with its 14-byte header.
    FRAME_ROOM = 1514

    def send_frame(self, frame: bytes) -> Steps[None]:
        """Sends `frame`, and waits until the device has taken it."""
        yield from self.submit(
            self.TRANSMIT_QUEUE, [bytes(self.HEADER) + frame], []
        )

    def receive_frame(self) -> Steps[bytes]:
        """Holds out a buffer and waits for a frame to come into it."""
        written, (answer,) = yield from self.submit(
            self.RECEIVE_QUEUE, [], [self.HEADER + self.FRAME_ROOM]
        )
        return answer[self.HEADER : written]


class Virtio9pHost(VirtioHost):
    """🧵 Stand-in for the driver of a virtio 9P transport.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    one queue up; `attach`, `open` and `read` are the 9P2000.L messages
    that read a file at the top of the share. An answer that is an
    `Rlerror` raises `VirtioError` with the error's name.
    """

    DEVICE_ID = 9
    QUEUES = 1
    KIND = "a 9P transport"
    #: The fid of the share's root, once attached.
    ROOT = 0
    #: How big a message may be, as this driver tells the server.
    MESSAGE_SIZE = 8192

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._next_fid = self.ROOT + 1

    def attach(self) -> Steps[None]:
        """Agrees on 9P2000.L, and attaches to the share's root."""
        yield from self._ask(
            ninep.TVERSION,
            struct.pack("<I", self.MESSAGE_SIZE) + _string(ninep.VERSION),
        )
        yield from self._ask(
            ninep.TATTACH,
            struct.pack("<II", self.ROOT, ninep.NO_FID)
            + _string(b"nobody")
            + _string(b"")
            + struct.pack("<I", 0),
        )

    def open(self, name: str) -> Steps[int]:
        """Walks to `name`, at the top of the share, and opens it to read.

        Gives the fid it is open on.
        """
        fid = self._next_fid
        self._next_fid += 1
        yield from self._ask(
            ninep.TWALK,
            struct.pack("<IIH", self.ROOT, fid, 1) + _string(name.encode()),
            about=name,
        )
        yield from self._ask(ninep.TLOPEN, struct.pack("<II", fid, 0))
        return fid

    def read(self, fid: int, *, size: int) -> Steps[bytes]:
        """Up to `size` bytes of the file open on `fid`, from its start."""
        answer = yield from self._ask(
            ninep.TREAD, struct.pack("<IQI", fid, 0, size)
        )
        (count,) = struct.unpack_from("<I", answer)
        return answer[4 : 4 + count]

    def _ask(self, kind: int, body: bytes, *, about: str = "") -> Steps[bytes]:
        """Sends one T-message and gives the body of its R-message."""
        message = ninep.HEADER.pack(ninep.HEADER.size + len(body), kind, 0)
        written, (answer,) = yield from self.submit(
            0, [message + body], [self.MESSAGE_SIZE]
        )
        _, answered, _ = ninep.HEADER.unpack_from(answer)
        body = answer[ninep.HEADER.size : written]
        if answered == ninep.RLERROR:
            (number,) = struct.unpack_from("<I", body)
            what = f" of {about!r}" if about else ""
            raise VirtioError(
                f"The share answered 9P message {kind}{what} with "
                f"{fuse.linux_error_name(number)}."
            )
        return body


def _string(text: bytes) -> bytes:
    """A 9P string: its length in two bytes, then its bytes."""
    return struct.pack("<H", len(text)) + text


class VirtioFsHost(VirtioHost):
    """🧵 Stand-in for the driver of a virtio file system device.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    two queues up; `init`, `lookup`, `open` and `read` are the FUSE
    requests that read a file, which go on the request queue. An answer
    with an error raises `VirtioError` with the error's name.
    """

    DEVICE_ID = 26  # Section 5.11.
    QUEUES = 2
    KIND = "a file system device"
    #: Where FUSE requests go: everything but FORGET.
    REQUEST_QUEUE = 1

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Each request carries a number of its own, which its answer gives
        # back.
        self._unique = 0

    def init(self) -> Steps[None]:
        """Says hello, in FUSE 7.31."""
        yield from self._ask(
            fuse.INIT,
            fuse.ROOT,
            struct.pack("<IIII", fuse.MAJOR, fuse.MINOR, 0, 0),
            64,
        )

    def lookup(self, name: str) -> Steps[int]:
        """The node of `name`, at the top of the share."""
        entry = yield from self._ask(
            fuse.LOOKUP, fuse.ROOT, name.encode() + b"\0", 128, about=name
        )
        node: int = struct.unpack_from("<Q", entry)[0]
        return node

    def open(self, node: int) -> Steps[int]:
        """Opens the file `node` to read, and gives its handle."""
        opened = yield from self._ask(
            fuse.OPEN, node, struct.pack("<II", fuse.O_RDONLY, 0), 16
        )
        handle: int = struct.unpack_from("<Q", opened)[0]
        return handle

    def read(self, node: int, handle: int, *, size: int) -> Steps[bytes]:
        """Up to `size` bytes of the open file, from its start."""
        return (
            yield from self._ask(
                fuse.READ,
                node,
                struct.pack("<QQIIQII", handle, 0, size, 0, 0, 0, 0),
                size,
            )
        )

    def _ask(
        self, opcode: int, node: int, body: bytes, room: int, *, about: str = ""
    ) -> Steps[bytes]:
        """Sends one request and gives the body of its answer."""
        self._unique += 1
        header = fuse.IN_HEADER.pack(
            fuse.IN_HEADER.size + len(body),
            opcode,
            self._unique,
            node,
            0, 0, 0, 0, 0,
        )  # fmt: skip
        written, (answer,) = yield from self.submit(
            self.REQUEST_QUEUE, [header + body], [fuse.OUT_HEADER.size + room]
        )
        length, error, _ = fuse.OUT_HEADER.unpack_from(answer)
        if error:
            name = fuse.linux_error_name(-error)
            what = f" of {about!r}" if about else ""
            raise VirtioError(
                f"The share answered FUSE request {opcode}{what} with {name}."
            )
        return answer[fuse.OUT_HEADER.size : min(length, written)]
