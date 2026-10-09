"""🎭 A stand-in for an SSD's firmware: the SSD's CPU, played by a script.

The SSD's hardware keeps the queues and moves the data, and its firmware
makes the decisions (see docs/models/nvme-frontend.md). `SsdFirmware` is
those decisions as a Python script, for a `ScriptedBusMaster` in the place
of the SSD's CPU:

    firmware = sp.SsdFirmware(frontend=0x1001_0000, dma=0x1002_0000,
                              flash=0x1003_0000, buffer=0x4000_0000)
    cpu = ssd.add("cpu", sp.ScriptedBusMaster(firmware.script))

It is what real firmware does, a step at a time and in the same order, so
it is also the place to read how an NVMe drive answers its host:

1. Wait for the frontend to say something has happened.
2. If the host has reset or enabled the controller, see to that.
3. If a command is waiting, read it, do what it says, and have the
   frontend post how it went.

🎓 The part that turns the drive's blocks into pages of NAND flash is the
flash translation layer (FTL). This one is as small as an FTL can be: a
table that says, for each page of the drive, which NAND page holds it.
"""

from __future__ import annotations

import struct
from typing import NamedTuple

from socpuppet.ops import Steps, read, read32, wait_irq, write, write32

# ---- The NVMe frontend's registers for its CPU.
_CONTROL = 0x00
_STATUS = 0x04
_INTERRUPT_ENABLE = 0x08
_LIMITS = 0x0C
_COMMAND_QUEUE = 0x10
_COMPLETION_RESULT = 0x14
_COMPLETION_STATUS = 0x18
_COMPLETION_POST = 0x1C
_QUEUE_ID = 0x20
_QUEUE_BASE_LOW = 0x24
_QUEUE_BASE_HIGH = 0x28
_QUEUE_LAST = 0x2C
_QUEUE_LINK = 0x30
_QUEUE_CREATE = 0x34
_COMMAND = 0x40

#: The frontend's status bits: the host has enabled the controller, the
#: host has reset it, and a command is waiting.
_ENABLED = 1 << 0
_DISABLED = 1 << 1
_COMMAND_WAITING = 1 << 2
#: The one bit of its control register: the firmware is ready.
_READY = 1 << 0
#: What its queue-create register is told.
_A_COMPLETION_QUEUE = 1
_A_SUBMISSION_QUEUE = 2

# ---- What the DMA engine and the flash controller have in common.
_DEVICE_COMMAND = 0x00
_DEVICE_STATUS = 0x04
_ERROR = 1 << 1
_BUSY = 1 << 2

# ---- The DMA engine's registers, and its two commands.
_HOST_ADDRESS_LOW = 0x0C
_HOST_ADDRESS_HIGH = 0x10
_DMA_LOCAL_ADDRESS = 0x14
_LENGTH = 0x18
_FROM_HOST = 1
_TO_HOST = 2

# ---- The flash controller's registers, and the commands used here.
_BLOCK = 0x0C
_PAGE = 0x10
_FLASH_LOCAL_ADDRESS = 0x14
_PAGE_SIZE = 0x20
_PAGES_PER_BLOCK = 0x24
_BLOCKS = 0x28
_READ_PAGE = 1
_PROGRAM_PAGE = 2
_IDENTIFY_THE_CHIP = 4

# ---- NVMe, as its specification gives it.
_COMMAND_SIZE = 64
#: The drive's block, and the page of the host's memory that a command's
#: data pointers count in.
_BLOCK_SIZE = 512
_HOST_PAGE = 4096
#: There is one namespace, and namespaces are numbered from 1.
_THE_NAMESPACE = 1

#: Admin commands.
_CREATE_IO_SUBMISSION_QUEUE = 0x01
_CREATE_IO_COMPLETION_QUEUE = 0x05
_IDENTIFY = 0x06
_SET_FEATURES = 0x09
#: I/O commands.
_FLUSH = 0x00
_WRITE = 0x01
_READ = 0x02
#: What Identify can be asked for, and the one feature there is to set.
_THE_NAMESPACE_ITSELF = 0x00
_THE_CONTROLLER = 0x01
_THE_ACTIVE_NAMESPACES = 0x02
_NUMBER_OF_QUEUES = 0x07

#: How many times the firmware asks a device whether it is done before it
#: gives up. Nothing takes simulated time yet, so a device is done by the
#: first or second time of asking.
_PATIENCE = 100


class _Outcome(NamedTuple):
    """How a command went: what its completion will say."""

    #: The status code, zero for success.
    status: int = 0
    #: Which list the code is from: the one every command shares (0), or
    #: the command's own (1).
    status_type: int = 0
    #: The command's answer, for the few that have one of 32 bits.
    result: int = 0


_SUCCESS = _Outcome()
#: Statuses every command shares.
_INVALID_OPCODE = _Outcome(0x01)
_INVALID_FIELD = _Outcome(0x02)
_DATA_TRANSFER_ERROR = _Outcome(0x04)
_INVALID_NAMESPACE = _Outcome(0x0B)
_LBA_OUT_OF_RANGE = _Outcome(0x80)
#: Statuses of the two commands that create a queue.
_COMPLETION_QUEUE_INVALID = _Outcome(0x00, 1)
_INVALID_QUEUE_IDENTIFIER = _Outcome(0x01, 1)
_INVALID_QUEUE_SIZE = _Outcome(0x02, 1)
_INVALID_INTERRUPT_VECTOR = _Outcome(0x08, 1)


class _Command(NamedTuple):
    """A command, as the fields of it the firmware reads."""

    opcode: int
    namespace: int
    #: Where the command's data is in the host's memory: its first page,
    #: and either its second or a list of the rest.
    data: int
    more_data: int
    #: The command's own parameters, which each command lays out its way.
    dword10: int
    dword11: int
    dword12: int

    @classmethod
    def from_bytes(cls, command: bytes) -> _Command:
        opcode, namespace, data, more_data, dword10, dword11, dword12 = (
            struct.unpack("<B3xI16xQQIII12x", command)
        )
        return cls(
            opcode, namespace, data, more_data, dword10, dword11, dword12
        )


class _Extent(NamedTuple):
    """A run of bytes in the host's memory."""

    address: int
    length: int


class SsdFirmware:
    """🎭 Stand-in for an SSD's firmware, as a script for the SSD's CPU slot.

    `frontend`, `dma` and `flash` are where the three devices' register
    blocks are on the SSD's bus, and `buffer` is the SSD's own memory, of
    which the firmware uses the first two pages (8 KiB).

    It answers what a host's driver needs to use the drive: Identify, the
    number of queues, creating I/O queues, and Read, Write and Flush on
    one namespace of 512-byte blocks. `script` is the generator function
    to hand to a `ScriptedBusMaster`.

    ⚠️ It keeps its table of where the drive's pages are in Python, and
    not on the drive. A reset of the SSD's CPU starts the script again
    with an empty table, and what was written is no longer found. Real
    firmware writes the table to the NAND as well, and reads it back.
    """

    def __init__(
        self, *, frontend: int, dma: int, flash: int, buffer: int
    ) -> None:
        self._frontend = frontend
        self._dma = dma
        self._flash = flash
        #: One page of the drive, as it is being read or written.
        self._page_buffer = buffer
        #: A page of scratch, for what is made up to send to the host, and
        #: for what is fetched from the host to be read.
        self._scratch = buffer + _HOST_PAGE
        # What the hardware says it has, asked when the script starts.
        self._page_size = 0
        self._pages_per_block = 0
        self._pages = 0
        self._io_queue_pairs = 0
        self._vectors = 0
        # The I/O queues the host has had created, by identifier.
        self._completion_queues: set[int] = set()
        self._submission_queues: set[int] = set()
        # The flash translation layer: for each page of the drive that was
        # ever written, the NAND page that holds it. And the next NAND
        # page nobody has.
        self._where: dict[int, int] = {}
        self._next_free_nand_page = 0

    @property
    def page_map(self) -> dict[int, int]:
        """Where the drive's pages are: the NAND page that holds each.

        Only pages that were ever written are in it. A page here is a NAND
        page's worth of the drive's blocks, and a NAND page is numbered
        through the whole chip.
        """
        return dict(self._where)

    # ---- The firmware.

    def script(self) -> Steps[None]:
        """What the firmware does, for ever: hand it to a ScriptedBusMaster."""
        yield from self._start_up()
        while True:
            yield wait_irq()
            status = yield read32(self._frontend + _STATUS)
            # The reset first: what the host enabled is the controller as
            # it is after it.
            if status & _DISABLED:
                yield from self._the_host_reset_the_controller()
            if status & _ENABLED:
                yield from self._the_host_enabled_the_controller()
            if status & _COMMAND_WAITING:
                yield from self._deal_with_the_command()

    def _start_up(self) -> Steps[None]:
        # A reset of the SSD's CPU starts the script again, and with it
        # the firmware's memory of what it had.
        self._completion_queues.clear()
        self._submission_queues.clear()
        self._where.clear()
        self._next_free_nand_page = 0
        # What is the chip, and what has the frontend got?
        yield from self._do(self._flash, _IDENTIFY_THE_CHIP)
        self._page_size = yield read32(self._flash + _PAGE_SIZE)
        self._pages_per_block = yield read32(self._flash + _PAGES_PER_BLOCK)
        blocks = yield read32(self._flash + _BLOCKS)
        self._pages = self._pages_per_block * blocks
        limits = yield read32(self._frontend + _LIMITS)
        self._io_queue_pairs = limits & 0xFFFF
        self._vectors = limits >> 16
        # From here on the frontend's line says when there is work.
        yield write32(
            self._frontend + _INTERRUPT_ENABLE,
            _ENABLED | _DISABLED | _COMMAND_WAITING,
        )

    def _the_host_reset_the_controller(self) -> Steps[None]:
        # The queues are gone, and what is on the drive stays. The
        # acknowledgement comes last, because it says the firmware has let
        # go of everything from before the reset.
        self._completion_queues.clear()
        self._submission_queues.clear()
        yield write32(self._frontend + _STATUS, _DISABLED)

    def _the_host_enabled_the_controller(self) -> Steps[None]:
        # There is nothing to start up, so the firmware is ready at once.
        # If the host has changed its mind again by now, the frontend does
        # not hear this, and says so in its own time.
        yield write32(self._frontend + _STATUS, _ENABLED)
        yield write32(self._frontend + _CONTROL, _READY)

    def _deal_with_the_command(self) -> Steps[None]:
        command = _Command.from_bytes(
            (yield read(self._frontend + _COMMAND, _COMMAND_SIZE))
        )
        # Queue 0 is the admin queue. The same opcode means one thing
        # there and another on an I/O queue.
        from_queue = yield read32(self._frontend + _COMMAND_QUEUE)
        if from_queue == 0:
            outcome = yield from self._admin(command)
        else:
            outcome = yield from self._io(command)
        yield write32(self._frontend + _COMPLETION_RESULT, outcome.result)
        yield write32(
            self._frontend + _COMPLETION_STATUS,
            outcome.status_type << 8 | outcome.status,
        )
        yield write32(self._frontend + _COMPLETION_POST, 1)

    # ---- Admin commands.

    def _admin(self, command: _Command) -> Steps[_Outcome]:
        if command.opcode == _CREATE_IO_COMPLETION_QUEUE:
            return (yield from self._create_completion_queue(command))
        if command.opcode == _CREATE_IO_SUBMISSION_QUEUE:
            return (yield from self._create_submission_queue(command))
        if command.opcode == _IDENTIFY:
            return (yield from self._identify(command))
        if command.opcode == _SET_FEATURES:
            return self._set_features(command)
        return _INVALID_OPCODE

    def _is_an_io_queue(self, queue_id: int) -> bool:
        """Whether the host may have an I/O queue with this identifier.

        Queue 0 is the admin queue, and there are only so many.
        """
        return 1 <= queue_id <= self._io_queue_pairs

    def _create_completion_queue(self, command: _Command) -> Steps[_Outcome]:
        # Both kinds of queue are asked for the same way: the identifier
        # in the low half of dword 10, its size, counted from zero, in the
        # high half, and where the queue is in the first data pointer.
        queue_id, last_slot = command.dword10 & 0xFFFF, command.dword10 >> 16
        if (
            not self._is_an_io_queue(queue_id)
            or queue_id in self._completion_queues
        ):
            return _INVALID_QUEUE_IDENTIFIER
        # A queue keeps one slot empty, so one of a single entry holds
        # nothing.
        if last_slot == 0:
            return _INVALID_QUEUE_SIZE
        # The host is told about the queue's completions on the interrupt
        # vector it names, which has to be one the drive has.
        vector = command.dword11 >> 16
        if vector >= self._vectors:
            return _INVALID_INTERRUPT_VECTOR
        yield from self._have_it_created(
            _A_COMPLETION_QUEUE, queue_id, command.data, last_slot, vector
        )
        self._completion_queues.add(queue_id)
        return _SUCCESS

    def _create_submission_queue(self, command: _Command) -> Steps[_Outcome]:
        queue_id, last_slot = command.dword10 & 0xFFFF, command.dword10 >> 16
        if (
            not self._is_an_io_queue(queue_id)
            or queue_id in self._submission_queues
        ):
            return _INVALID_QUEUE_IDENTIFIER
        if last_slot == 0:
            return _INVALID_QUEUE_SIZE
        # Its commands' completions go to a completion queue, which has to
        # be there first. The admin completion queue always is.
        completion_queue = command.dword11 >> 16
        if (
            completion_queue != 0
            and completion_queue not in self._completion_queues
        ):
            return _COMPLETION_QUEUE_INVALID
        yield from self._have_it_created(
            _A_SUBMISSION_QUEUE,
            queue_id,
            command.data,
            last_slot,
            completion_queue,
        )
        self._submission_queues.add(queue_id)
        return _SUCCESS

    def _have_it_created(
        self, kind: int, queue_id: int, base: int, last_slot: int, link: int
    ) -> Steps[None]:
        """Tell the frontend about a queue the firmware has agreed to."""
        yield write32(self._frontend + _QUEUE_ID, queue_id)
        yield write32(self._frontend + _QUEUE_BASE_LOW, base & 0xFFFF_FFFF)
        yield write32(self._frontend + _QUEUE_BASE_HIGH, base >> 32)
        yield write32(self._frontend + _QUEUE_LAST, last_slot)
        yield write32(self._frontend + _QUEUE_LINK, link)
        yield write32(self._frontend + _QUEUE_CREATE, kind)

    def _identify(self, command: _Command) -> Steps[_Outcome]:
        """Identify: a 4 KiB page that describes something of the drive."""
        page = bytearray(_HOST_PAGE)
        what = command.dword10 & 0xFF
        if what == _THE_CONTROLLER:
            # How many namespaces there are, at offset 516.
            struct.pack_into("<I", page, 516, 1)
        elif what == _THE_NAMESPACE_ITSELF:
            if command.namespace != _THE_NAMESPACE:
                return _INVALID_NAMESPACE
            # Its size and its capacity in blocks, and at offset 128 the
            # first block format, whose third byte is the block size as a
            # power of two: 2 to the 9th is 512.
            struct.pack_into("<QQ", page, 0, self._blocks(), self._blocks())
            page[130] = 9
        elif what == _THE_ACTIVE_NAMESPACES:
            struct.pack_into("<I", page, 0, _THE_NAMESPACE)
        else:
            return _INVALID_FIELD
        yield write(self._scratch, bytes(page))
        return (yield from self._send_to_the_host(command, self._scratch))

    def _set_features(self, command: _Command) -> _Outcome:
        if command.dword10 & 0xFF != _NUMBER_OF_QUEUES:
            return _INVALID_FIELD
        # The answer is how many I/O queues the drive has, whatever the
        # host asked for, counted from zero: submission queues in the low
        # half, completion queues in the high half.
        from_zero = self._io_queue_pairs - 1
        return _Outcome(result=from_zero << 16 | from_zero)

    # ---- I/O commands.

    def _io(self, command: _Command) -> Steps[_Outcome]:
        if command.opcode == _FLUSH:
            # Everything written is already in the NAND.
            return _SUCCESS
        if command.opcode in (_READ, _WRITE):
            return (yield from self._read_or_write(command))
        return _INVALID_OPCODE

    def _blocks(self) -> int:
        """How many 512-byte blocks the drive holds."""
        return self._pages * (self._page_size // _BLOCK_SIZE)

    def _read_or_write(self, command: _Command) -> Steps[_Outcome]:
        if command.namespace != _THE_NAMESPACE:
            return _INVALID_NAMESPACE
        # The first block is in dwords 10 and 11, and how many, counted
        # from zero, in the low half of dword 12.
        first = command.dword11 << 32 | command.dword10
        count = (command.dword12 & 0xFFFF) + 1
        if first + count > self._blocks():
            return _LBA_OUT_OF_RANGE
        extents = yield from self._data_of(command, count * _BLOCK_SIZE)
        if extents is None:
            return _DATA_TRANSFER_ERROR
        # Through the host's memory an extent at a time, and through the
        # drive a page at a time, whichever ends first.
        at = first * _BLOCK_SIZE
        for address, extent_length in extents:
            while extent_length:
                page, offset = divmod(at, self._page_size)
                length = min(extent_length, self._page_size - offset)
                if command.opcode == _WRITE:
                    ok = yield from self._write_into_page(
                        page, offset, address, length
                    )
                else:
                    ok = yield from self._read_from_page(
                        page, offset, address, length
                    )
                if not ok:
                    return _DATA_TRANSFER_ERROR
                at += length
                address += length
                extent_length -= length
        return _SUCCESS

    def _load(self, page: int) -> Steps[bool]:
        """Put one of the drive's pages in the page buffer.

        From the NAND, or as zeros if it was never written. 🎓 An erased
        NAND page reads as all ones, so the zeros a host expects of a new
        drive come from the firmware, which knows what was never written.
        """
        nand_page = self._where.get(page)
        if nand_page is None:
            yield write(self._page_buffer, bytes(self._page_size))
            return True
        return (yield from self._flash_page(_READ_PAGE, nand_page))

    def _read_from_page(
        self, page: int, offset: int, host_address: int, length: int
    ) -> Steps[bool]:
        return (yield from self._load(page)) and (
            yield from self._copy(
                _TO_HOST, host_address, self._page_buffer + offset, length
            )
        )

    def _write_into_page(
        self, page: int, offset: int, host_address: int, length: int
    ) -> Steps[bool]:
        """Change part of one of the drive's pages.

        What is not being written has to survive, so the page is read,
        changed and programmed again. A page written for the first time
        takes the next NAND page nobody has. One written again is
        programmed where it is, which only an ideal NAND allows: a real
        one has to be given a fresh page, and that is where garbage
        collection begins.
        """
        if not (yield from self._load(page)) or not (
            yield from self._copy(
                _FROM_HOST, host_address, self._page_buffer + offset, length
            )
        ):
            return False
        if page not in self._where:
            self._where[page] = self._next_free_nand_page
            self._next_free_nand_page += 1
        return (yield from self._flash_page(_PROGRAM_PAGE, self._where[page]))

    # ---- A command's data.

    def _data_of(
        self, command: _Command, length: int
    ) -> Steps[list[_Extent] | None]:
        """Where in the host's memory `length` bytes of a command's data are.

        None if the host's list of them could not be fetched.

        🎓 NVMe says where data is page by page (PRPs, physical region
        pages). The first pointer is to the data itself, and may start
        anywhere in a page. If what is left fits in one page, the second
        pointer is to that page. Otherwise it is to a list of pointers, a
        page each, whose last entry points on to more of the list if the
        list fills its own page.
        """
        in_the_first = min(length, _HOST_PAGE - command.data % _HOST_PAGE)
        extents = [_Extent(command.data, in_the_first)]
        left = length - in_the_first
        if left == 0:
            return extents
        if left <= _HOST_PAGE:
            extents.append(_Extent(command.more_data, left))
            return extents
        pointers = command.more_data
        while left:
            # As much of the list as its page holds, fetched into the
            # scratch page to be read.
            list_bytes = _HOST_PAGE - pointers % _HOST_PAGE
            if not (
                yield from self._copy(
                    _FROM_HOST, pointers, self._scratch, list_bytes
                )
            ):
                return None
            fetched = yield read(self._scratch, list_bytes)
            entries = struct.unpack(f"<{list_bytes // 8}Q", fetched)
            for index, entry in enumerate(entries):
                if left == 0:
                    break
                # The last entry of a full list points on, if more than
                # one page of data is still to come.
                if index == len(entries) - 1 and left > _HOST_PAGE:
                    pointers = entry
                    break
                here = min(left, _HOST_PAGE)
                extents.append(_Extent(entry, here))
                left -= here
        return extents

    def _send_to_the_host(
        self, command: _Command, local_address: int
    ) -> Steps[_Outcome]:
        """Send a page of the buffer to where a command's data goes."""
        extents = yield from self._data_of(command, _HOST_PAGE)
        if extents is None:
            return _DATA_TRANSFER_ERROR
        for address, length in extents:
            if not (
                yield from self._copy(_TO_HOST, address, local_address, length)
            ):
                return _DATA_TRANSFER_ERROR
            local_address += length
        return _SUCCESS

    # ---- The two devices that move data.

    def _copy(
        self, direction: int, host_address: int, local_address: int, length: int
    ) -> Steps[bool]:
        """Copy between the host's memory and the buffer, by the DMA engine."""
        yield write32(self._dma + _HOST_ADDRESS_LOW, host_address & 0xFFFF_FFFF)
        yield write32(self._dma + _HOST_ADDRESS_HIGH, host_address >> 32)
        yield write32(self._dma + _DMA_LOCAL_ADDRESS, local_address)
        yield write32(self._dma + _LENGTH, length)
        return (yield from self._do(self._dma, direction))

    def _flash_page(self, command: int, nand_page: int) -> Steps[bool]:
        """Move a NAND page between the chip and the page buffer."""
        block, page = divmod(nand_page, self._pages_per_block)
        yield write32(self._flash + _BLOCK, block)
        yield write32(self._flash + _PAGE, page)
        yield write32(self._flash + _FLASH_LOCAL_ADDRESS, self._page_buffer)
        return (yield from self._do(self._flash, command))

    def _do(self, device: int, command: int) -> Steps[bool]:
        """Give a device a command and wait for it. True if it was carried out.

        The device does its work a moment after the write returns, and
        says it is busy until then, so the firmware asks until it is not.
        """
        yield write32(device + _DEVICE_COMMAND, command)
        for _ in range(_PATIENCE):
            status = yield read32(device + _DEVICE_STATUS)
            if not status & _BUSY:
                return not status & _ERROR
        raise RuntimeError(
            f"The device at {device:#x} is still busy after being asked "
            f"{_PATIENCE} times whether it has finished command {command}."
        )
