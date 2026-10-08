"""🎭 A host's NVMe driver, small enough to read in one sitting.

It stands in for the driver that firmware on the host will have (Zephyr's,
later on). It does what a driver does, in the order a driver does it: put
the admin queues in the host's memory, enable the controller, and send
commands by writing them into a queue and ringing a doorbell.

It is written for a script, so every step that touches the bus is a
generator, and a script hands over to it with `yield from`:

    def script():
        nvme = sp.NvmeHost(registers=0x1000_0000, memory=0x8000_0000)
        yield from nvme.enable()
        yield from nvme.write_blocks(first=0, data=bytes(512))
        block = yield from nvme.read_blocks(first=0, count=1)

Everything here follows the NVMe base specification, which is public.
"""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass

from socpuppet.errors import NvmeError
from socpuppet.ops import (
    Steps,
    read,
    read32,
    read64,
    wait,
    wait_irq,
    write,
    write32,
    write64,
)
from socpuppet.time import ms

# Controller registers: their offsets, and the bits used in them.
_CAPABILITIES = 0x00
_CONFIGURATION = 0x14
_ENABLE = 1 << 0
# CC.IOSQES and CC.IOCQES: a command is 2^6 bytes and a completion 2^4.
_ENTRY_SIZES = 6 << 16 | 4 << 20
_STATUS = 0x1C
_READY = 1 << 0
# CSTS.CFS: the controller has hit an error it cannot recover from.
_FATAL = 1 << 1
_ADMIN_QUEUE_SIZES = 0x24
_ADMIN_SUBMISSION_QUEUE = 0x28
_ADMIN_COMPLETION_QUEUE = 0x30
_DOORBELLS = 0x1000

# Admin opcodes.
_CREATE_IO_SUBMISSION_QUEUE = 0x01
_CREATE_IO_COMPLETION_QUEUE = 0x05
_IDENTIFY = 0x06
_SET_FEATURES = 0x09
# The feature Set Features sets here: how many I/O queues the host wants.
_NUMBER_OF_QUEUES = 0x07
# Bits of dword 11 in the two commands that create a queue: the ring is
# one piece of memory, and (for a completion queue) it interrupts.
_CONTIGUOUS = 1 << 0
_INTERRUPTS_ENABLED = 1 << 1
# What Identify is asked to describe (its CNS value): a namespace.
_DESCRIBE_NAMESPACE = 0

# I/O opcodes.
_WRITE = 0x01
_READ = 0x02

# What a status in a completion means, by (status code type, status code).
# Type 0 is the list every command shares, and type 1 is a command's own.
_STATUS_NAMES = {
    (0, 0x01): "Invalid Command Opcode",
    (0, 0x02): "Invalid Field in Command",
    (0, 0x0B): "Invalid Namespace or Format",
    (0, 0x80): "LBA Out of Range",
    (1, 0x00): "Completion Queue Invalid",
    (1, 0x01): "Invalid Queue Identifier",
    (1, 0x08): "Invalid Interrupt Vector",
}

_PAGE = 4096
_COMMAND_SIZE = 64
_COMPLETION_SIZE = 16
# How many entries fit in the page a queue's ring is given: 64 commands.
# (256 completions would fit, but the two queues of a pair are the same
# length here.)
_MOST_QUEUE_ENTRIES = _PAGE // _COMMAND_SIZE
# The drive's one namespace. Namespaces are numbered from 1.
_NAMESPACE = 1
# How many pages of data one command can point at: the first directly, and
# the rest through a list that is itself one page of 8-byte entries.
_MOST_PAGES = 1 + _PAGE // 8
# The pages at the start of the driver's memory that hold its queues: two
# rings for each of its two queue pairs.
_QUEUE_PAGES = 4
# The identifier of a queue pair's first command. Not zero, so that a
# completion slot nobody filled in is not taken for the first command's.
_FIRST_COMMAND_ID = 0x100


def _wait_for_the_wire() -> Steps[None]:
    """Waits for the master's interrupt line.

    Unlike with an MSI receiver there is nothing to read afterwards: the
    line falls when the driver acknowledges the completion.
    """
    yield wait_irq()


@dataclass(frozen=True)
class NvmeNamespace:
    """What a namespace says about itself: its size, in blocks of what size."""

    blocks: int
    block_size: int


class _QueuePair:
    """A submission queue and the completion queue its completions go to."""

    def __init__(
        self, identifier: int, submissions: int, completions: int, entries: int
    ) -> None:
        self.identifier = identifier
        self.entries = entries
        # Where the two rings are in the host's memory.
        self.submissions = submissions
        self.completions = completions
        self.next_command_id = _FIRST_COMMAND_ID
        self.start_over()

    def start_over(self) -> None:
        """Empty both rings, as a controller reset does on its side."""
        # Where the host puts its next command, and looks for the next
        # completion.
        self.tail = 0
        self.head = 0
        # The phase bit a new completion carries. It starts at 1 and
        # inverts each time the completion queue wraps around.
        self.phase = 1


class NvmeHost:
    """🎭 Stand-in for the host's NVMe driver.

    `registers` is where the controller's register block is in the host's
    address map. `memory` is the start of an area of the host's memory that
    the driver may use: four pages for its queues, then as many pages as
    its largest transfer needs, and one more for a list of them. It has to
    start on a page boundary (a multiple of 4096). `memory_size` is how
    many bytes the area has. Given one, the driver says so when a transfer
    needs more, where it would otherwise write past the end of whatever
    you meant it to have. `queue_entries` is how long the driver makes its
    queues, which has to be no longer than the controller takes. Like a
    real driver, it asks the controller that, and how far apart its
    doorbells are.

    `interrupt` is how the driver waits for the controller's interrupt:
    steps that return once it has come. Left out, the driver waits with
    `sp.wait_irq()`, which is right when the controller's first interrupt
    line is wired to the master that runs the script. Behind PCIe the
    interrupt arrives as a message, and `MsiHost.wait` is the thing to
    pass.
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
        if not 2 <= queue_entries <= _MOST_QUEUE_ENTRIES:
            raise ValueError(
                f"This driver's queues have 2 to {_MOST_QUEUE_ENTRIES} "
                f"entries (a queue is one page of memory), and "
                f"{queue_entries} were asked for."
            )
        if memory % _PAGE:
            raise ValueError(
                f"The driver's memory has to start on a page boundary (a "
                f"multiple of {_PAGE}), because its queues and its data are "
                f"whole pages, and {memory:#x} does not."
            )
        if memory_size is not None and memory_size < _QUEUE_PAGES * _PAGE:
            raise ValueError(
                f"The driver's queues take {_QUEUE_PAGES} pages of its "
                f"memory ({_QUEUE_PAGES * _PAGE} bytes) before any data, "
                f"and it was given {memory_size} bytes."
            )
        self._queue_entries = queue_entries
        self._registers = registers
        self._interrupt = interrupt or _wait_for_the_wire
        self._free_memory = memory + _QUEUE_PAGES * _PAGE
        # Where the driver's memory ends, if it was told.
        self._memory_end = None if memory_size is None else memory + memory_size
        # Pages that held a command's data and can hold the next one's.
        self._spare_pages: list[int] = []
        # Queue pair 0's two rings are the first two pages of the driver's
        # memory, and queue pair 1's the next two.
        self._admin = _QueuePair(0, memory, memory + _PAGE, queue_entries)
        self._io = _QueuePair(
            1, memory + 2 * _PAGE, memory + 3 * _PAGE, queue_entries
        )
        # What the controller says about itself, read when it is enabled:
        # how far apart its doorbells are, and how long it may take to
        # become ready. Until then, what the specification starts from.
        self._doorbell_stride = 4
        self._ready_timeout = 0
        # What the namespace said about itself, once it has been asked.
        self._namespace: NvmeNamespace | None = None

    def enable(self) -> Steps[None]:
        """Reset the controller, set up the queues, and enable it."""
        # A driver cannot know what state it finds a controller in, so it
        # starts with a reset: clear CC.EN, and wait for CSTS.RDY to clear.
        # The reset does away with every queue the controller had, so the
        # host starts its own over too.
        yield from self._ask_what_the_controller_takes()
        yield write32(self._registers + _CONFIGURATION, 0)
        yield from self._wait_until_ready_is(False)
        self._admin.start_over()
        self._io.start_over()
        entries = self._queue_entries - 1  # sizes are counted from zero
        yield write32(
            self._registers + _ADMIN_QUEUE_SIZES, entries << 16 | entries
        )
        yield from write64(
            self._registers + _ADMIN_SUBMISSION_QUEUE, self._admin.submissions
        )
        yield from write64(
            self._registers + _ADMIN_COMPLETION_QUEUE, self._admin.completions
        )
        yield write32(self._registers + _CONFIGURATION, _ENTRY_SIZES | _ENABLE)
        yield from self._wait_until_ready_is(True)
        yield from self._create_io_queues()

    def identify_namespace(self) -> Steps[NvmeNamespace]:
        """Ask the drive how big it is, with an Identify command."""
        (page,) = self._take_pages(1)
        yield from self._complete(
            self._admin,
            "Identify",
            opcode=_IDENTIFY,
            namespace=_NAMESPACE,
            data=page,
            dword10=_DESCRIBE_NAMESPACE,
        )
        description = yield read(page, _PAGE)
        self._spare_pages.append(page)
        # NSZE, the size in blocks, is 64 bits at byte 0. The block formats
        # the namespace could have are 32 bits each from byte 128, and
        # byte 26 (FLBAS, low four bits) says which one it has. A format
        # gives the block size as a power of two in its bits 23 to 16.
        (blocks,) = struct.unpack_from("<Q", description, 0)
        (block_format,) = struct.unpack_from(
            "<I", description, 128 + 4 * (description[26] & 0xF)
        )
        self._namespace = NvmeNamespace(
            blocks=blocks, block_size=1 << ((block_format >> 16) & 0xFF)
        )
        return self._namespace

    def read_blocks(self, *, first: int, count: int) -> Steps[bytes]:
        """Read `count` blocks, starting at block `first`."""
        block_size = yield from self._block_size()
        pages = self._pages_for(count, block_size)
        yield from self._transfer(_READ, "Read", first, count, pages)
        data = bytearray()
        for page in pages:
            data += yield read(page, _PAGE)
        self._spare_pages += pages
        return bytes(data[: count * block_size])

    def write_blocks(self, *, first: int, data: bytes) -> Steps[None]:
        """Write `data`, which is whole blocks, starting at block `first`."""
        block_size = yield from self._block_size()
        if len(data) % block_size:
            raise ValueError(
                f"A write is of whole {block_size}-byte blocks, and this "
                f"data is {len(data)} bytes long."
            )
        pages = self._pages_for(len(data) // block_size, block_size)
        for index, page in enumerate(pages):
            yield write(page, data[index * _PAGE : (index + 1) * _PAGE])
        yield from self._transfer(
            _WRITE, "Write", first, len(data) // block_size, pages
        )
        self._spare_pages += pages

    def _ask_what_the_controller_takes(self) -> Steps[None]:
        """Read the capabilities register, and go by what it says."""
        capabilities = yield from read64(self._registers + _CAPABILITIES)
        # CAP.MQES, bits 15 to 0: the longest queue, counted from zero.
        most_entries = (capabilities & 0xFFFF) + 1
        if self._queue_entries > most_entries:
            raise NvmeError(
                "This driver was told to make its queues "
                f"{self._queue_entries} entries long, and the controller "
                f"takes at most {most_entries}. Create the driver with "
                f"queue_entries={most_entries} or fewer."
            )
        # CAP.TO, bits 31 to 24: how long the controller may take to
        # become ready or idle, in units of 500 ms.
        self._ready_timeout = ((capabilities >> 24) & 0xFF) * ms(500)
        # CAP.DSTRD, bits 35 to 32: the doorbells are 4 << DSTRD bytes
        # apart.
        self._doorbell_stride = 4 << ((capabilities >> 32) & 0xF)

    def _create_io_queues(self) -> Steps[None]:
        # One pair of I/O queues is all this driver uses. It asks for it
        # (both counts are from zero: submission queues, then completion
        # queues), and then creates the completion queue before the
        # submission queue that feeds it.
        yield from self._complete(
            self._admin,
            "Set Features",
            opcode=_SET_FEATURES,
            dword10=_NUMBER_OF_QUEUES,
            dword11=0 << 16 | 0,
        )
        size_and_identifier = (
            self._queue_entries - 1
        ) << 16 | self._io.identifier
        # The completion queue interrupts on vector 0, like the admin queue:
        # the host here has one interrupt line.
        yield from self._complete(
            self._admin,
            "Create I/O Completion Queue",
            opcode=_CREATE_IO_COMPLETION_QUEUE,
            data=self._io.completions,
            dword10=size_and_identifier,
            dword11=0 << 16 | _INTERRUPTS_ENABLED | _CONTIGUOUS,
        )
        yield from self._complete(
            self._admin,
            "Create I/O Submission Queue",
            opcode=_CREATE_IO_SUBMISSION_QUEUE,
            data=self._io.submissions,
            dword10=size_and_identifier,
            dword11=self._io.identifier << 16 | _CONTIGUOUS,
        )

    def _block_size(self) -> Steps[int]:
        """The drive's block size, asking it only the first time."""
        if self._namespace is None:
            yield from self.identify_namespace()
        assert self._namespace is not None
        return self._namespace.block_size

    def _pages_for(self, count: int, block_size: int) -> list[int]:
        """Pages of the driver's memory for `count` blocks of data."""
        if count < 1:
            raise ValueError(
                f"A transfer is of at least one block, and {count} were "
                "asked for."
            )
        most_blocks = _MOST_PAGES * _PAGE // block_size
        if count > most_blocks:
            raise ValueError(
                f"This driver moves at most {most_blocks} blocks in one "
                f"command ({_MOST_PAGES} pages of memory), and {count} were "
                "asked for. Split the transfer."
            )
        return self._take_pages(-(-count * block_size // _PAGE))

    def _transfer(
        self, opcode: int, name: str, first: int, count: int, pages: list[int]
    ) -> Steps[None]:
        """Send a read or a write of `count` blocks, with its data in `pages`.

        A command says where its data is page by page, because the pages a
        host can spare are rarely next to each other. 🎓 The specification
        calls the two pointers a command has PRP entries (physical region
        pages). The first is the first page. The second is the second page
        if there are two, and otherwise the address of a page that lists
        every page after the first.
        """
        page_list = []
        if len(pages) == 1:
            more_data = 0
        elif len(pages) == 2:
            more_data = pages[1]
        else:
            page_list = self._take_pages(1)
            more_data = page_list[0]
            yield write(
                more_data, struct.pack(f"<{len(pages) - 1}Q", *pages[1:])
            )
        yield from self._complete(
            self._io,
            name,
            opcode=opcode,
            namespace=_NAMESPACE,
            data=pages[0],
            more_data=more_data,
            # The starting block in dwords 10 and 11, and the number of
            # blocks, counted from zero, in dword 12.
            dword10=first & 0xFFFF_FFFF,
            dword11=first >> 32,
            dword12=count - 1,
        )
        self._spare_pages += page_list

    def _complete(
        self,
        queue: _QueuePair,
        name: str,
        *,
        opcode: int,
        namespace: int = 0,
        data: int = 0,
        more_data: int = 0,
        dword10: int = 0,
        dword11: int = 0,
        dword12: int = 0,
    ) -> Steps[None]:
        """Send one command, wait for the controller, and see how it went."""
        # 1. Write the 64-byte command into the submission queue's next slot.
        command_id = queue.next_command_id
        queue.next_command_id = (command_id + 1) & 0xFFFF
        command = struct.pack(
            "<BBHI16xQQIII12x",
            opcode,
            0,
            command_id,
            namespace,
            data,
            more_data,
            dword10,
            dword11,
            dword12,
        )
        yield write(queue.submissions + queue.tail * _COMMAND_SIZE, command)
        # 2. Ring the doorbell: tell the controller how far the queue is
        #    filled now.
        queue.tail = (queue.tail + 1) % queue.entries
        yield write32(self._doorbell(queue, completion=False), queue.tail)
        # 3. Wait for the interrupt, and read the 16-byte completion.
        yield from self._interrupt()
        entry = yield read(
            queue.completions + queue.head * _COMPLETION_SIZE, _COMPLETION_SIZE
        )
        _, _, _, completed_id, status = struct.unpack("<IIIHH", entry)
        if (status & 1) != queue.phase or completed_id != command_id:
            raise NvmeError(
                f"An interrupt came, but the completion queue holds no "
                f"completion for the {name} command just sent. Check what "
                "reaches this master's irq input: it should be the "
                "controller's first interrupt line and nothing else, or, "
                "behind PCIe, the line of the MSI receiver that the "
                "controller's messages are sent to."
            )
        # 4. Ring the other doorbell: tell the controller how far the
        #    completions have been read. Its interrupt line falls.
        queue.head += 1
        if queue.head == queue.entries:
            queue.head = 0
            queue.phase ^= 1
        yield write32(self._doorbell(queue, completion=True), queue.head)
        # 5. See how it went. Above the phase bit, the status field holds
        #    an 8-bit code and the 3-bit type of list the code is from.
        code, code_type = (status >> 1) & 0xFF, (status >> 9) & 0x7
        if (code_type, code) != (0, 0):
            meaning = _STATUS_NAMES.get((code_type, code))
            raise NvmeError(
                f"The controller failed the {name} command"
                + (f": {meaning}" if meaning else "")
                + f" (status code type {code_type}, status code {code:#04x})."
            )

    def _doorbell(self, queue: _QueuePair, *, completion: bool) -> int:
        # Two doorbells per queue pair: the submission queue's tail, then
        # the completion queue's head. Each is 4 bytes, and the controller
        # says how far apart they are.
        return (
            self._registers
            + _DOORBELLS
            + (2 * queue.identifier + (1 if completion else 0))
            * self._doorbell_stride
        )

    def _wait_until_ready_is(self, wanted: bool) -> Steps[None]:
        limit = self._ready_timeout
        waited = 0
        while True:
            status = yield read32(self._registers + _STATUS)
            if status & _FATAL:
                raise NvmeError(
                    "The controller reports a fatal error (CSTS.CFS is "
                    "set), so there is no use in waiting for it to become "
                    f"{'ready' if wanted else 'idle'}."
                )
            if bool(status & _READY) == wanted:
                return
            if waited >= limit:
                raise NvmeError(
                    "The controller did not become "
                    f"{'ready' if wanted else 'idle'} within the "
                    f"{limit // ms(1)} ms it says that may take."
                )
            yield wait(ms(1))
            waited += ms(1)

    def _take_pages(self, count: int) -> list[int]:
        """`count` pages of the driver's memory.

        A page that an earlier command is done with is used again before a
        new one is taken.
        """
        pages = []
        for _ in range(count):
            if self._spare_pages:
                pages.append(self._spare_pages.pop())
                continue
            if self._memory_end is not None and (
                self._free_memory + _PAGE > self._memory_end
            ):
                given = (self._memory_end - self._admin.submissions) // _PAGE
                raise NvmeError(
                    f"The driver needs more memory than the {given} pages "
                    f"it was given: {_QUEUE_PAGES} of them hold its queues, "
                    "and this transfer wants more than the rest. Give it a "
                    "larger memory_size, or split the transfer."
                )
            pages.append(self._free_memory)
            self._free_memory += _PAGE
        return pages
