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
device, such as `VirtioRngHost`, is a thin layer over it that knows what
goes in that device's chains.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

from socpuppet.errors import VirtioError
from socpuppet.ops import Steps, read, read32, wait_irq, write, write32
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
_DESCRIPTOR = struct.Struct("<QIHH")
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
        for queue in self._queues.values():
            queue.in_flight.clear()
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
        queue = _Queue(number, entries, self._take(3 * _PAGE, _PAGE))
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
        queue = self._queues[number]
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
        for data in readable:
            buffers.append((self._take(len(data), 1), len(data), 0, data))
        for size in writable:
            buffers.append((self._take(size, 1), size, _WRITE, None))
        if not buffers:
            raise ValueError("A chain has at least one buffer.")
        head = queue.next_descriptor
        for index, (address, size, flags, data) in enumerate(buffers):
            descriptor = (queue.next_descriptor + 1) % queue.entries
            last = index == len(buffers) - 1
            yield write(
                queue.descriptors + 16 * queue.next_descriptor,
                _DESCRIPTOR.pack(
                    address, size, flags | (0 if last else _NEXT), descriptor
                ),
            )
            if data is not None:
                yield write(address, data)
            queue.next_descriptor = descriptor
        queue.in_flight[head] = [
            (address, size) for address, size, flags, _ in buffers if flags
        ]
        slot = queue.made_available % queue.entries
        yield write(queue.available + 4 + 2 * slot, struct.pack("<H", head))
        queue.made_available += 1
        yield write(
            queue.available + 2,
            struct.pack("<H", queue.made_available & 0xFFFF),
        )
        yield self._write(regs.QUEUE_NOTIFY, number)
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
            status = yield from self._read(regs.INTERRUPT_STATUS)
            yield self._write(regs.INTERRUPT_ACK, status)
        element = yield read(
            queue.used + 4 + 8 * (queue.taken % queue.entries), 8
        )
        queue.taken += 1
        used_head, written = _USED_ELEMENT.unpack(element)
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
        index = yield read(queue.used + 2, 2)
        return struct.unpack("<H", index)[0]

    def _take(self, size: int, alignment: int) -> int:
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
        return (yield read32(self._registers + offset))

    def _write(self, offset: int, value: int):
        return write32(self._registers + offset, value)


class VirtioRngHost:
    """🧵 Stand-in for the driver of a virtio entropy device.

    Takes what `VirtioHost` takes. `start` finds the device and sets its
    one queue up; `read` asks it for bytes.
    """

    #: What the device says it is (section 5.4).
    DEVICE_ID = 4

    def __init__(self, **host: object) -> None:
        self._host = VirtioHost(**host)  # type: ignore[arg-type]

    def start(self) -> Steps[None]:
        """Finds the device, agrees on no features, and sets its queue up."""
        device_id = yield from self._host.probe()
        if device_id != self.DEVICE_ID:
            raise VirtioError(
                f"The virtio device is a kind {device_id}, not an entropy "
                f"device (kind {self.DEVICE_ID})."
            )
        yield from self._host.reset()
        yield from self._host.negotiate(0)
        yield from self._host.setup_queue(0)
        yield from self._host.driver_ok()

    def read(self, count: int) -> Steps[bytes]:
        """Asks the device for `count` random bytes."""
        written, (answer,) = yield from self._host.submit(0, [], [count])
        return answer[:written]
